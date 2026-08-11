"""Entity-level coverage: required fields, creation shape, defaults, 404s,
append-only ledger shape, listing/pagination (PRD §2.3, §2.4, §3.1–§3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_gift_post,
    assert_iso_instant,
    assert_member,
    assert_reputation_event,
    create_gift_post_payload,
    create_wishlist_payload,
    get_post,
    join_group,
    make_admin_headers,
    make_anonymous_headers,
    make_member_headers,
    publish_post,
    register_member,
    create_claim,
    create_post,
    create_group,
    set_clock,
    setup_group_with_members,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Corner/entities
# ---------------------------------------------------------------------------

def test_member_creation_missing_email_returns_invalid_request(api):
    """PRD §3.1: "A new member supplies an `email` — unique across the platform,
    compared case-insensitively — and a `display_name`."

    Design: Corner/entities/member_creation_missing_email_returns_invalid_request
    """
    res = api.create_member({"display_name": "No Email"}, make_anonymous_headers())
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_member_created_with_system_defaults(api):
    """PRD §2.8: "It starts from a base of 50, gains 2 points per gift the member
    has completed within the trailing 90 whole days, loses 3 points per item
    received within the trailing 90 whole days, loses 10 points per active
    strike point, and gains a 5-point seniority bonus once the member's own
    account is at least 180 days old (measured in whole days from the member's
    `created_at`)."
    PRD §3.1: "The account is born `ACTIVE`, and the system immediately records
    a `WELCOME_BONUS` reputation event worth 5 points in `PENDING` status, so
    newcomers begin with a small provisional standing that only becomes official
    after it settles."

    Design: Corner/entities/member_created_with_system_defaults
    """
    m = register_member("def@x.com", "Def")
    assert_member(m)
    fetched = validate_success(api.get_member(m["id"], make_member_headers(m["id"])), 200)
    assert fetched["status"] == "ACTIVE"
    assert fetched["active_strike_points"] == 0
    assert fetched["fairness_score"] == 50
    assert fetched["given_count_90d"] == 0
    assert fetched["received_count_90d"] == 0
    assert fetched["version"] == 1
    assert fetched["suspension_ends_at"] is None


def test_gift_post_created_in_draft_echoes_inputs(api):
    """PRD §3.2: "The post is born in `DRAFT`, invisible to claimants, with the
    creating member recorded as `giver_id`."

    Design: Corner/entities/gift_post_created_in_draft_echoes_inputs
    """
    group, members = setup_group_with_members([("eg@x.com", "G")], name="Echo Group",
                                              zip_code="98201")
    g = members["eg@x.com"]
    res = api.create_gift_post(
        create_gift_post_payload(
            group["id"], title="Rain boots", category="CLOTHING",
            claim_mode="FIRST_COME", expires_at="2026-06-10T00:00:00Z",
        ),
        make_member_headers(g["id"]),
    )
    post = validate_success(res, 201)
    assert_gift_post(post)
    assert post["status"] == "DRAFT"
    assert post["title"] == "Rain boots"
    assert post["category"] == "CLOTHING"
    assert post["claim_mode"] == "FIRST_COME"
    assert post["giver_id"] == g["id"]
    assert post["version"] == 1
    assert post["current_claim_id"] is None
    assert post["current_offer_expires_at"] is None


def test_gift_post_invalid_category_returns_invalid_request(api):
    """PRD §3.2: "a `category` drawn from `FURNITURE`, `CLOTHING`, `FOOD`,
    `HOUSEHOLD`, `ELECTRONICS`, or `OTHER`"
    PRD §2.6: "required fields are present, types are valid, enum values are in
    range, email and datetime formats are valid, and unknown fields are
    rejected; failures yield `ERR_VALIDATION`."

    Design: Corner/entities/gift_post_invalid_category_returns_invalid_request
    """
    group, members = setup_group_with_members(
        [("tg@x.com", "G")], name="Type Group", zip_code="98202", clock=None
    )
    g = members["tg@x.com"]
    res = api.create_gift_post(
        create_gift_post_payload(
            group["id"], title="Car", category="VEHICLE",
            claim_mode="FIRST_COME", expires_at="2026-06-10T00:00:00Z",
        ),
        make_member_headers(g["id"]),
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_wishlist_default_expiry_thirty_days(api):
    """PRD §2.5: "Before any administrative intervention, the logical clock
    reads exactly `2026-05-01T00:00:00Z`; the server must never fall back to
    wall-clock time."
    PRD §3.5: "The wishing member is recorded as `member_id`, and the entry is
    born `ACTIVE` with an `expires_at` set exactly 30 days after creation."

    Design: Corner/entities/wishlist_default_expiry_thirty_days
    """
    # NOTE: no set_clock call — the logical clock defaults to 2026-05-01T00:00:00Z.
    w = register_member("wl@x.com", "W")
    group = create_group("Wish Group", "98203")
    join_group(w, group)
    res = api.create_wishlist(
        create_wishlist_payload(group["id"], keyword="stroller"),
        make_member_headers(w["id"]),
    )
    wl = validate_success(res, 201)
    assert wl["status"] == "ACTIVE"
    assert_iso_instant(
        wl["expires_at"], "2026-05-31T00:00:00Z",
        f"expires_at must be created_at + 30 days (default clock 2026-05-01), "
        f"got {wl['expires_at']}",
    )


def test_member_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Existence — every referenced resource exists, validated left
    to right: path identifiers first, then body foreign keys such as `group_id`,
    `post_id`, `claim_id`, and a report's `target_id` (interpreted according to
    `target_type`). Each missing resource surfaces its own not-found error, from
    `ERR_MEMBER_NOT_FOUND` through `ERR_MODERATION_ACTION_NOT_FOUND`."

    Design: Corner/entities/member_not_found_returns_404
    """
    res = api.get_member(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_MEMBER_NOT_FOUND, expected_status=404)


def test_reputation_event_immutable_shape(api):
    """PRD §2.4: "`ReputationEvent` is the lone exception: as an append-only
    ledger entry it carries only `id` and `created_at`; both `updated_at` and
    `version` are absent from it."
    PRD §3.1: "The account is born `ACTIVE`, and the system immediately records
    a `WELCOME_BONUS` reputation event worth 5 points in `PENDING` status, so
    newcomers begin with a small provisional standing that only becomes official
    after it settles."

    Design: Corner/entities/reputation_event_immutable_shape
    """
    m = register_member("rev@x.com", "Rev")
    res = api.list_reputation_events_of_member(m["id"], make_member_headers(m["id"]))
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1, f"expected exactly 1 event, got {meta['total_count']}"
    event = data[0]
    assert_reputation_event(event)
    assert event["event_type"] == "WELCOME_BONUS"
    assert event["base_points"] == 5
    assert event["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner/endpoints
# ---------------------------------------------------------------------------

def test_gift_post_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items to skip and defaults to 0.
    Unless otherwise specified, every list endpoint returns resources sorted by
    `created_at` in ascending order. The `meta` object of a list response
    carries the pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/gift_post_list_pagination_defaults
    """
    g = register_member("plg@x.com", "G")
    group = create_group("Page Group", "98232")
    join_group(g, group)
    post = create_post(g, group, title="Rug", category="HOUSEHOLD")
    data, meta = validate_paginated(
        api.list_gift_posts(make_member_headers(g["id"]), params={"group_id": group["id"]})
    )
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [p["id"] for p in data] == [post["id"]]


def test_claims_filtered_by_status_returns_only_matching(api):
    """PRD §3.3: "Claims can be listed filtered by `post_id`, `claimer_id`, or
    `status`."
    PRD §3.3: "Under `GIVER_PICK` there is no automatic promotion at all: the
    giver explicitly selects any `QUEUED` claim of the post, and attempting to
    offer a claim that is not `QUEUED` on that post fails with
    `ERR_CLAIM_NOT_QUEUED`."

    Design: Corner/endpoints/claims_filtered_by_status_returns_only_matching
    """
    group, members = setup_group_with_members(
        [("flg@x.com", "G"), ("flc1@x.com", "C1"), ("flc2@x.com", "C2")],
        name="Filter Group", zip_code="98233",
    )
    g, c1, c2 = members["flg@x.com"], members["flc1@x.com"], members["flc2@x.com"]
    post = create_post(g, group, title="Printer", category="ELECTRONICS",
                       claim_mode="GIVER_PICK")
    publish_post(g, post)
    cl1 = create_claim(c1, post)
    cl2 = create_claim(c2, post)
    assert cl1["status"] == "QUEUED" and cl2["status"] == "QUEUED"
    offered = validate_success(
        api.offer_gift_post(post["id"], {"claim_id": cl1["id"]},
                            make_member_headers(g["id"])), 200
    )
    assert offered["status"] == "OFFERED"
    data, meta = validate_paginated(
        api.list_claims(
            make_member_headers(c2["id"]),
            params={"post_id": post["id"], "status": "QUEUED"},
        )
    )
    assert meta["total_count"] == 1
    assert [c["id"] for c in data] == [cl2["id"]], (
        f"the OFFERED claim {cl1['id']} must be filtered out, got {[c['id'] for c in data]}"
    )
