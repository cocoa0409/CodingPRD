"""Security & access control: authentication/authorization order, not-found
errors, ownership checks, validation priority pairs, and optimistic
concurrency (PRD §2.1, §2.6, §2.7, §3.1, §3.8)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_iso_instant,
    TEST_USERS,
    apply_strike,
    create_and_publish_post,
    create_curb_alert,
    create_group,
    create_member_payload,
    get_post,
    join_group,
    make_admin_headers,
    make_member_headers,
    register_member,
    set_clock,
    setup_group_with_members,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Auth / authorization
# ---------------------------------------------------------------------------

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request with missing or malformed headers is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.6: "Because authentication outranks existence, for instance, a
    request with bad headers against a nonexistent group fails with
    `ERR_UNAUTHENTICATED`, never with `ERR_GROUP_NOT_FOUND`"

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.get_group(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_member_cannot_approve_membership(api):
    """PRD §2.1: "A request whose role is not permitted for the targeted
    endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "Approval by a moderator of that group (or a `PlatformAdmin`)
    requires the membership to still be `REQUESTED` — otherwise
    `ERR_MEMBERSHIP_NOT_REQUESTED` — and the roster to be `ACCEPTING`, since
    approving into a full roster fails with `ERR_GROUP_FULL`."

    Design: Corner/rbac/member_cannot_approve_membership
    """
    m1 = register_member("ra1@x.com", "M1")
    m2 = register_member("ra2@x.com", "M2")
    group = create_group("RBAC Group", "98234", join_policy="APPROVAL_REQUIRED")
    ms1 = join_group(m1, group)
    assert ms1["status"] == "REQUESTED"
    res = api.approve_membership(ms1["id"], make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    after = validate_success(api.get_membership(ms1["id"], make_admin_headers()), 200)
    assert after["status"] == "REQUESTED"


def test_member_cannot_set_clock(api):
    """PRD §2.1: "`PlatformAdmin` creates groups, overturns moderation actions,
    drives the logical clock, and shares the moderators' membership- and
    report-handling operations across all groups."
    PRD §2.1: "A request whose role is not permitted for the targeted endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_set_clock
    """
    m = register_member("clk@x.com", "M")
    res = api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    # The logical clock must be unchanged: a wishlist created now still gets the
    # default-clock expiry (2026-05-01T00:00:00Z + 30 days).
    group = create_group("Clock Guard Group", "98250")
    join_group(m, group)
    res = api.create_wishlist(
        {"group_id": group["id"], "keyword": "lamp"}, make_member_headers(m["id"])
    )
    wl = validate_success(res, 201)
    assert_iso_instant(
        wl["expires_at"], "2026-05-31T00:00:00Z",
        f"clock must remain at the 2026-05-01T00:00:00Z default, got {wl['expires_at']}",
    )


def test_non_owner_cannot_withdraw_post(api):
    """PRD §3.2: "Publishing moves the post from `DRAFT` to `OPEN` and is
    restricted to the giver (acting as anyone else earns
    `ERR_NOT_RESOURCE_OWNER`) whose account is in good standing; publishing a
    post that is not in `DRAFT` fails with `ERR_POST_NOT_DRAFT`."
    PRD §3.2: "A giver may also withdraw a post at will, moving it to
    `WITHDRAWN` — from `DRAFT` with no further consequence; from `OPEN`, with
    the same claim-withdrawal and wishlist-release side effects as expiry; and
    from `RESERVED`, provided no claim on the post has reached `ACCEPTED`."

    Design: Corner/rbac/non_owner_cannot_withdraw_post
    """
    group, members = setup_group_with_members(
        [("nog@x.com", "G"), ("nom@x.com", "M2")], name="Owner Group", zip_code="98236"
    )
    g, m2 = members["nog@x.com"], members["nom@x.com"]
    post = create_and_publish_post(g, group, title="Shelf", category="FURNITURE")
    res = api.withdraw_gift_post(post["id"], make_member_headers(m2["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    after = get_post(post["id"], make_member_headers(g["id"]))
    assert after["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Not-found errors (Corner/errors)
# ---------------------------------------------------------------------------

def test_group_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/errors/group_not_found_returns_404
    """
    res = api.get_group(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_GROUP_NOT_FOUND, expected_status=404)


def test_membership_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/errors/membership_not_found_returns_404
    """
    res = api.get_membership(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_FOUND, expected_status=404)


def test_claim_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/errors/claim_not_found_returns_404
    """
    res = api.get_claim(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_FOUND, expected_status=404)


def test_pickup_plan_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/errors/pickup_plan_not_found_returns_404
    """
    res = api.get_pickup_plan(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_PICKUP_PLAN_NOT_FOUND, expected_status=404)


def test_wishlist_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/errors/wishlist_not_found_returns_404
    """
    res = api.get_wishlist(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_WISHLIST_NOT_FOUND, expected_status=404)


def test_curb_alert_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/errors/curb_alert_not_found_returns_404
    """
    res = api.get_curb_alert(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_CURB_ALERT_NOT_FOUND, expected_status=404)


def test_report_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/errors/report_not_found_returns_404
    """
    res = api.get_report(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_REPORT_NOT_FOUND, expected_status=404)


def test_moderation_action_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/errors/moderation_action_not_found_returns_404
    """
    res = api.get_moderation_action(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_MODERATION_ACTION_NOT_FOUND, expected_status=404)


def test_claim_nonexistent_post_returns_gift_post_not_found(api):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/validations/claim_nonexistent_post_returns_gift_post_not_found
    """
    m = register_member("nf@x.com", "M")
    res = api.create_claim({"post_id": NON_EXISTENT_UUID}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_GIFT_POST_NOT_FOUND, expected_status=404)


def test_duplicate_membership_returns_membership_exists(api):
    """PRD §3.1: "at most one membership per member–group pair may be live
    (`REQUESTED` or `APPROVED`) at a time — a second attempt is rejected with
    `ERR_MEMBERSHIP_EXISTS`"

    Design: Corner/validations/duplicate_membership_returns_membership_exists
    """
    m = register_member("dm@x.com", "M")
    group = create_group("Dup Member Group", "98229")
    join_group(m, group)  # OPEN -> APPROVED inline
    res = api.create_membership({"group_id": group["id"]}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_EXISTS, expected_status=409)


# ---------------------------------------------------------------------------
# Validation priority pairs (Difficulty/priority_pair_validation_conflict)
# ---------------------------------------------------------------------------

def _setup_suspended_member_and_withdrawn_post():
    """S is suspended (3 strike points); G's post was published then withdrawn."""
    group, members = setup_group_with_members(
        [("ps@x.com", "S"), ("pr@x.com", "R"), ("pg@x.com", "G")],
        name="Priority Group", zip_code="98108",
    )
    s, r, g = members["ps@x.com"], members["pr@x.com"], members["pg@x.com"]
    apply_strike(r, group, s, severity_points=3)
    post = create_and_publish_post(g, group, title="Floor lamp", category="HOUSEHOLD")
    validate_success(api_client.withdraw_gift_post(post["id"], make_member_headers(g["id"])), 200)
    return group, s, g, post


def test_claim_on_withdrawn_post_by_suspended_member_rejected_with_state_error(api):
    """PRD §2.6: "The order is:

    1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are
    present and well-formed; failures yield `ERR_UNAUTHENTICATED`.
    ...
    6. **State preconditions** — the target resource is in a state that permits
    the operation (for example a post must be `DRAFT` to publish, a claim
    `OFFERED` to accept); each violation surfaces its specific 409 state error.
    7. **Member standing** — content-creating operations require the acting
    member's `status` to be `ACTIVE`; a suspended actor is rejected with
    `ERR_MEMBER_SUSPENDED`, a banned actor with `ERR_MEMBER_BANNED`."
    PRD §3.3: "Claiming an `OPEN` post creates the claim in `QUEUED` status —
    claiming a post in any other state fails with `ERR_POST_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/claim_on_withdrawn_post_by_suspended_member_rejected
    """
    group, s, g, post = _setup_suspended_member_and_withdrawn_post()
    s_read = validate_success(api.get_member(s["id"], make_member_headers(s["id"])), 200)
    assert s_read["status"] == "SUSPENDED"
    res = api.create_claim({"post_id": post["id"]}, make_member_headers(s["id"]))
    # Priority-6 state (post not OPEN) outranks priority-7 member standing.
    validate_error(res, ApiErrorId.ERR_POST_NOT_OPEN, expected_status=409)


def test_claim_on_withdrawn_post_never_surfaces_member_suspended(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed priority order so that the surfaced error is
    deterministic."
    PRD §2.6: "6. **State preconditions** — the target resource is in a state
    that permits the operation (for example a post must be `DRAFT` to publish, a
    claim `OFFERED` to accept); each violation surfaces its specific 409 state
    error.
    7. **Member standing** — content-creating operations require the acting
    member's `status` to be `ACTIVE`; a suspended actor is rejected with
    `ERR_MEMBER_SUSPENDED`, a banned actor with `ERR_MEMBER_BANNED`."

    Second angle: with both rules violated, the response must not be the
    lower-priority ERR_MEMBER_SUSPENDED.

    Design: Difficulty/priority_pair_validation_conflict/claim_on_withdrawn_post_by_suspended_member_rejected
    """
    group, s, g, post = _setup_suspended_member_and_withdrawn_post()
    res = api.create_claim({"post_id": post["id"]}, make_member_headers(s["id"]))
    body = res.json()
    assert body.get("data", {}).get("error_id") != "ERR_MEMBER_SUSPENDED", (
        "the lower-priority standing check must not surface over the state error"
    )
    validate_error(res, ApiErrorId.ERR_POST_NOT_OPEN, expected_status=409)


def _setup_suspended_member_and_full_curb_zone():
    """S is suspended (3 strike points); U has created 3 mutually overlapping
    live alerts in zone MAPLE on 2026-05-12."""
    group, members = setup_group_with_members(
        [("cs@x.com", "S"), ("cr@x.com", "R"), ("cu@x.com", "U")],
        name="Curb Group", zip_code="98109",
    )
    s, r, u = members["cs@x.com"], members["cr@x.com"], members["cu@x.com"]
    apply_strike(r, group, s, severity_points=3)
    create_curb_alert(u, group, zone="MAPLE",
                      starts_at="2026-05-12T09:00:00Z", ends_at="2026-05-12T10:00:00Z")
    create_curb_alert(u, group, zone="MAPLE",
                      starts_at="2026-05-12T09:30:00Z", ends_at="2026-05-12T10:30:00Z")
    create_curb_alert(u, group, zone="MAPLE",
                      starts_at="2026-05-12T09:45:00Z", ends_at="2026-05-12T11:00:00Z")
    return group, s, u


def test_curb_alert_by_suspended_member_over_capacity_rejected_with_standing_error(api):
    """PRD §2.6: "7. **Member standing** — content-creating operations require
    the acting member's `status` to be `ACTIVE`; a suspended actor is rejected
    with `ERR_MEMBER_SUSPENDED`, a banned actor with `ERR_MEMBER_BANNED`.
    ...
    9. **Temporal rules** — interval well-formedness (`ERR_INVALID_TIME_RANGE`),
    porch-window overlap (`ERR_PICKUP_WINDOW_CONFLICT`), and curb-zone capacity
    (`ERR_CURB_ALERT_CAPACITY`)."

    Design: Difficulty/priority_pair_validation_conflict/curb_alert_by_suspended_member_over_capacity_rejected
    """
    group, s, u = _setup_suspended_member_and_full_curb_zone()
    res = api.create_curb_alert(
        {"group_id": group["id"], "zone": "MAPLE",
         "starts_at": "2026-05-12T09:50:00Z", "ends_at": "2026-05-12T10:05:00Z"},
        make_member_headers(s["id"]),
    )
    # Priority-7 member standing outranks priority-9 temporal/capacity.
    validate_error(res, ApiErrorId.ERR_MEMBER_SUSPENDED, expected_status=403)


def test_curb_alert_by_suspended_member_never_surfaces_capacity_error(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed priority order so that the surfaced error is
    deterministic."
    PRD §2.6: "7. **Member standing** — content-creating operations require the
    acting member's `status` to be `ACTIVE`; a suspended actor is rejected with
    `ERR_MEMBER_SUSPENDED`, a banned actor with `ERR_MEMBER_BANNED`.
    ...
    9. **Temporal rules** — interval well-formedness (`ERR_INVALID_TIME_RANGE`),
    porch-window overlap (`ERR_PICKUP_WINDOW_CONFLICT`), and curb-zone capacity
    (`ERR_CURB_ALERT_CAPACITY`)."

    Second angle: with both rules violated, the response must not be the
    lower-priority ERR_CURB_ALERT_CAPACITY.

    Design: Difficulty/priority_pair_validation_conflict/curb_alert_by_suspended_member_over_capacity_rejected
    """
    group, s, u = _setup_suspended_member_and_full_curb_zone()
    res = api.create_curb_alert(
        {"group_id": group["id"], "zone": "MAPLE",
         "starts_at": "2026-05-12T09:50:00Z", "ends_at": "2026-05-12T10:05:00Z"},
        make_member_headers(s["id"]),
    )
    body = res.json()
    assert body.get("data", {}).get("error_id") != "ERR_CURB_ALERT_CAPACITY", (
        "the lower-priority capacity check must not surface over the standing error"
    )
    validate_error(res, ApiErrorId.ERR_MEMBER_SUSPENDED, expected_status=403)


# ---------------------------------------------------------------------------
# Optimistic concurrency (Corner/complexity_layers)
# ---------------------------------------------------------------------------

def test_occ_gift_post_stale_version_returns_412(api):
    """PRD §2.7: "Editing a gift post requires the non-optional request field
    `expected_gift_post_version`, carrying the client's last observed `version`
    of the post; if the post's current `version` has advanced beyond that value
    — through another edit or through any cascade that mutated the post — the
    update is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "While a post remains `DRAFT` or `OPEN` its author may edit the
    `title`, `description`, `category`, or `expires_at` through the versioned
    update of §2.7, each successful edit incrementing the post's `version` by
    one; posts past those states no longer accept edits."

    Design: Corner/complexity_layers/occ_gift_post_stale_version_returns_412
    """
    group, members = setup_group_with_members([("ocg@x.com", "G")], name="OCC Group",
                                              zip_code="98238")
    g = members["ocg@x.com"]
    from test_helpers import create_gift_post_payload
    res = api.create_gift_post(
        create_gift_post_payload(group["id"], title="Old title"),
        make_member_headers(g["id"]),
    )
    post = validate_success(res, 201)
    assert post["version"] == 1

    # First write with the observed version succeeds: 1 -> 2.
    res = api.update_gift_post(
        post["id"], {"title": "New title", "expected_gift_post_version": post["version"]},
        make_member_headers(g["id"]),
    )
    updated = validate_success(res, 200)
    assert updated["version"] == 2
    assert updated["title"] == "New title"

    # Second write carrying the same (now stale) version is rejected.
    res = api.update_gift_post(
        post["id"], {"title": "Third title", "expected_gift_post_version": post["version"]},
        make_member_headers(g["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = get_post(post["id"], make_member_headers(g["id"]))
    assert after["version"] == 2
    assert after["title"] == "New title", "the loser's write must not be applied"


def test_occ_group_policy_stale_version_returns_412(api, admin_headers):
    """PRD §2.7: "Updating a neighborhood group's policy likewise requires the
    non-optional `expected_group_version` field matching the group's current
    `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on
    mismatch, obliging the writer to re-read the group and resubmit against the
    fresh version."
    PRD §3.1: "A group's `name`, `join_policy`, and `capacity` may later be
    updated by a moderator of that group or a `PlatformAdmin` through the
    versioned policy update described in §2.7; such an update increments the
    group's `version` by one and recomputes `roster_status` whenever `capacity`
    changes."

    Design: Corner/complexity_layers/occ_group_policy_stale_version_returns_412
    """
    group = create_group("Policy Group", "98239")
    assert group["version"] == 1

    res = api.update_group(
        group["id"],
        {"join_policy": "APPROVAL_REQUIRED", "expected_group_version": group["version"]},
        admin_headers,
    )
    updated = validate_success(res, 200)
    assert updated["version"] == 2
    assert updated["join_policy"] == "APPROVAL_REQUIRED"

    res = api.update_group(
        group["id"],
        {"capacity": 200, "expected_group_version": group["version"]},
        admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    after = validate_success(api.get_group(group["id"], admin_headers), 200)
    assert after["capacity"] == 150, "the loser's write must not be applied"
    assert after["version"] == 2
