"""Gift-post lifecycle, claim creation rules, queue promotion modes, and the
24-hour offer window (PRD §3.2, §3.3, §2.11)."""
from test_helpers import (
    ApiErrorId,
    assert_iso_instant,
    complete_gift_cycle,
    create_and_publish_post,
    create_claim,
    create_post,
    get_claim,
    get_post,
    make_member_headers,
    publish_post,
    register_member,
    set_clock,
    setup_group_with_members,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Corner/state_machines — gift post
# ---------------------------------------------------------------------------

def test_publish_twice_returns_post_not_draft(api):
    """PRD §3.2: "publishing a post that is not in `DRAFT` fails with
    `ERR_POST_NOT_DRAFT`."

    Design: Corner/state_machines/publish_twice_returns_post_not_draft
    """
    group, members = setup_group_with_members([("ppg@x.com", "G")], name="Pub Group",
                                              zip_code="98204")
    g = members["ppg@x.com"]
    post = create_and_publish_post(g, group, title="Plates", category="HOUSEHOLD")
    res = api.publish_gift_post(post["id"], make_member_headers(g["id"]))
    validate_error(res, ApiErrorId.ERR_POST_NOT_DRAFT, expected_status=409)
    after = get_post(post["id"], make_member_headers(g["id"]))
    assert after["status"] == "OPEN", "re-publish must not change the post state"


def test_withdraw_fulfilled_post_returns_not_withdrawable(api):
    """PRD §3.2: "Withdrawal is forbidden once a claim stands `ACCEPTED` or the
    post has reached a terminal state, both rejected with
    `ERR_POST_NOT_WITHDRAWABLE`."

    Design: Corner/state_machines/withdraw_fulfilled_post_returns_not_withdrawable
    """
    group, members = setup_group_with_members(
        [("fg@x.com", "G"), ("fm@x.com", "M")], name="Fulfill Group", zip_code="98205"
    )
    g, m = members["fg@x.com"], members["fm@x.com"]
    post, claim, plan = complete_gift_cycle(
        g, m, group, title="High chair", category="FURNITURE"
    )
    assert post["status"] == "FULFILLED" and claim["status"] == "FULFILLED"
    res = api.withdraw_gift_post(post["id"], make_member_headers(g["id"]))
    validate_error(res, ApiErrorId.ERR_POST_NOT_WITHDRAWABLE, expected_status=409)
    post_after = get_post(post["id"], make_member_headers(g["id"]))
    claim_after = get_claim(claim["id"], make_member_headers(m["id"]))
    assert post_after["status"] == "FULFILLED"
    assert claim_after["status"] == "FULFILLED"


def test_claim_withdraw_after_accept_returns_not_withdrawable(api):
    """PRD §3.3: "A claimer may also voluntarily withdraw a claim while it is
    `QUEUED` or `OFFERED`, moving it to `WITHDRAWN`; withdrawing from any other
    state fails with `ERR_CLAIM_NOT_WITHDRAWABLE`."

    Design: Corner/state_machines/claim_withdraw_after_accept_returns_not_withdrawable
    """
    group, members = setup_group_with_members(
        [("wag@x.com", "G"), ("wam@x.com", "M")], name="Withdraw Group", zip_code="98207"
    )
    g, m = members["wag@x.com"], members["wam@x.com"]
    post = create_and_publish_post(g, group, title="Sled")
    claim = create_claim(m, post)
    validate_success(api.accept_claim(claim["id"], make_member_headers(m["id"])), 200)
    res = api.withdraw_claim(claim["id"], make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_WITHDRAWABLE, expected_status=409)
    after = get_claim(claim["id"], make_member_headers(m["id"]))
    assert after["status"] == "ACCEPTED"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency
# ---------------------------------------------------------------------------

def test_claim_against_draft_post_rejected(api):
    """PRD §3.3: "Claiming an `OPEN` post creates the claim in `QUEUED` status —
    claiming a post in any other state fails with `ERR_POST_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/claim_requires_post_open
    """
    group, members = setup_group_with_members(
        [("xg@x.com", "G"), ("xm@x.com", "M")], name="XEntity Group", zip_code="98112"
    )
    g, m = members["xg@x.com"], members["xm@x.com"]
    post = create_post(g, group, title="Stroller")
    assert post["status"] == "DRAFT"
    res = api.create_claim({"post_id": post["id"]}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_POST_NOT_OPEN, expected_status=409)


def test_claim_succeeds_immediately_after_publish(api):
    """PRD §3.3: "Claiming an `OPEN` post creates the claim in `QUEUED` status —
    claiming a post in any other state fails with `ERR_POST_NOT_OPEN`."
    PRD §3.3: "A brand-new claim on a vacant post under `FIRST_COME` or
    `FAIRNESS_DRAW` is promoted to `OFFERED` in the very same request that
    creates it."
    PRD §3.2: "Whenever exactly one claim holds `OFFERED` status, the post sits
    in `RESERVED` with `current_claim_id` naming that claim and
    `current_offer_expires_at` mirroring the claim's own `offer_expires_at`"

    Design: Difficulty/cross_entity_state_dependency/claim_requires_post_open
    """
    group, members = setup_group_with_members(
        [("xg2@x.com", "G"), ("xm2@x.com", "M")], name="XEntity Group 2", zip_code="98112"
    )
    g, m = members["xg2@x.com"], members["xm2@x.com"]
    post = create_post(g, group, title="Stroller")
    publish_post(g, post)
    res = api.create_claim({"post_id": post["id"]}, make_member_headers(m["id"]))
    claim = validate_success(res, 201)
    assert claim["status"] == "OFFERED", "head slot vacant -> auto-promotion in the same request"
    post_after = get_post(post["id"], make_member_headers(g["id"]))
    assert post_after["status"] == "RESERVED"
    assert post_after["current_claim_id"] == claim["id"]


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine — post re-offer cycle
# ---------------------------------------------------------------------------

def test_gift_post_reserved_to_open_on_head_withdraw(api):
    """PRD §3.2: "When the head slot empties with nothing to promote, the post
    returns to `OPEN` and both mirror fields clear to null. This `OPEN` →
    `RESERVED` → `OPEN` cycle is the post's re-offer loop, and a post finally
    reaches `FULFILLED` only through a completed porch pickup."

    Design: Difficulty/non_linear_state_machine/gift_post_open_reserved_open_cycle
    """
    group, members = setup_group_with_members(
        [("cg@x.com", "GV"), ("cm@x.com", "M")], name="Cycle Group", zip_code="98104"
    )
    g, m = members["cg@x.com"], members["cm@x.com"]
    post = create_and_publish_post(g, group, title="Bike pump")
    c1 = create_claim(m, post)
    assert c1["status"] == "OFFERED"

    validate_success(api.withdraw_claim(c1["id"], make_member_headers(m["id"])), 200)
    post_after = get_post(post["id"], make_member_headers(g["id"]))
    c1_after = get_claim(c1["id"], make_member_headers(m["id"]))
    assert post_after["status"] == "OPEN", "queue empty -> post falls back to OPEN"
    assert post_after["current_claim_id"] is None
    assert post_after["current_offer_expires_at"] is None
    assert c1_after["status"] == "WITHDRAWN"


def test_gift_post_reopens_then_reserves_again(api):
    """PRD §3.2: "When the head slot empties with nothing to promote, the post
    returns to `OPEN` and both mirror fields clear to null. This `OPEN` →
    `RESERVED` → `OPEN` cycle is the post's re-offer loop, and a post finally
    reaches `FULFILLED` only through a completed porch pickup."
    PRD §3.3: "A brand-new claim on a vacant post under `FIRST_COME` or
    `FAIRNESS_DRAW` is promoted to `OFFERED` in the very same request that
    creates it."

    Design: Difficulty/non_linear_state_machine/gift_post_open_reserved_open_cycle
    """
    group, members = setup_group_with_members(
        [("cg2@x.com", "GV"), ("cm2@x.com", "M")], name="Cycle Group 2", zip_code="98104"
    )
    g, m = members["cg2@x.com"], members["cm2@x.com"]
    post = create_and_publish_post(g, group, title="Bike pump")
    c1 = create_claim(m, post)
    validate_success(api.withdraw_claim(c1["id"], make_member_headers(m["id"])), 200)
    assert get_post(post["id"], make_member_headers(g["id"]))["status"] == "OPEN"

    # The cycle re-joins: a fresh claim on the re-opened post promotes and re-reserves.
    c2 = create_claim(m, post)
    assert c2["status"] == "OFFERED"
    post_after = get_post(post["id"], make_member_headers(g["id"]))
    assert post_after["status"] == "RESERVED"
    assert post_after["current_claim_id"] == c2["id"]


# ---------------------------------------------------------------------------
# Corner/validations — claim creation rules
# ---------------------------------------------------------------------------

def test_duplicate_claim_returns_duplicate_claim(api):
    """PRD §3.3: "the same member may hold at most one live claim — `QUEUED`,
    `OFFERED`, or `ACCEPTED` — per post (`ERR_DUPLICATE_CLAIM`)"

    Design: Corner/validations/duplicate_claim_returns_duplicate_claim
    """
    group, members = setup_group_with_members(
        [("dpg@x.com", "G"), ("dpc1@x.com", "C1"), ("dpm@x.com", "M")],
        name="Dup Group", zip_code="98224",
    )
    g, c1, m = members["dpg@x.com"], members["dpc1@x.com"], members["dpm@x.com"]
    post = create_and_publish_post(g, group, title="Mirror", category="HOUSEHOLD",
                                   claim_mode="GIVER_PICK")
    create_claim(c1, post)
    first = create_claim(m, post)
    assert first["status"] == "QUEUED"
    res = api.create_claim({"post_id": post["id"]}, make_member_headers(m["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CLAIM, expected_status=409)


def test_self_claim_returns_self_claim(api):
    """PRD §3.3: "the claimer must not be the post's own giver
    (`ERR_SELF_CLAIM`, HTTP 422)"

    Design: Corner/validations/self_claim_returns_self_claim
    """
    group, members = setup_group_with_members([("scg@x.com", "G")], name="Self Group",
                                              zip_code="98225")
    g = members["scg@x.com"]
    post = create_and_publish_post(g, group, title="Vase", category="HOUSEHOLD")
    res = api.create_claim({"post_id": post["id"]}, make_member_headers(g["id"]))
    validate_error(res, ApiErrorId.ERR_SELF_CLAIM, expected_status=422)


def test_non_member_claim_returns_not_group_member(api):
    """PRD §3.1: "acting within a group context — moderating memberships,
    claiming, coordinating pickups, giver offers — presupposes an `APPROVED`
    membership, with `ERR_NOT_GROUP_MEMBER` (HTTP 403) greeting actors who lack
    one."

    Design: Corner/validations/non_member_claim_returns_not_group_member
    """
    group, members = setup_group_with_members([("nmg@x.com", "G")], name="Closed Group",
                                              zip_code="98226")
    g = members["nmg@x.com"]
    nm = register_member("nmn@x.com", "NM")  # registered, never joined the group
    post = create_and_publish_post(g, group, title="Clock", category="HOUSEHOLD")
    res = api.create_claim({"post_id": post["id"]}, make_member_headers(nm["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_GROUP_MEMBER, expected_status=403)


def test_offer_window_exactly_24h(api):
    """PRD §3.3: "Promotion stamps `offered_at` with the logical now and sets
    `offer_expires_at` exactly 24 hours later; simultaneously the post moves
    `OPEN` → `RESERVED` with its mirror fields set."

    Design: Corner/calculations/offer_window_exactly_24h
    """
    group, members = setup_group_with_members(
        [("owg@x.com", "G"), ("owm@x.com", "M")], name="Offer Window Group",
        zip_code="98223",
    )
    g, m = members["owg@x.com"], members["owm@x.com"]
    post = create_and_publish_post(g, group, title="Iron", category="HOUSEHOLD")
    res = api.create_claim({"post_id": post["id"]}, make_member_headers(m["id"]))
    claim = validate_success(res, 201)
    assert claim["status"] == "OFFERED"
    assert_iso_instant(claim["offered_at"], "2026-05-10T09:00:00Z")
    assert_iso_instant(
        claim["offer_expires_at"], "2026-05-11T09:00:00Z",
        f"offer window must be exactly +24h, got {claim['offer_expires_at']}",
    )
