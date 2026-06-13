"""Campaign skeleton: creation, validation, RBAC, listing, immediate consistency.

Translates queue-B (Corner) instances from the entities, validations, rbac, endpoints,
and consistency_model sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_creator_headers, make_backer_headers,
    create_creator_payload, create_backer_payload, create_campaign_payload,
    create_tier_payload, create_pledge_payload,
    register_creator, register_backer, create_draft_campaign,
    create_live_campaign_with_tier, set_clock,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_campaign_minimal_returns_201_with_system_fields(api):
    """PRD §3.1: "At creation, the campaign's currency is copied from the owning creator's
    payout_currency and thereafter governs every tier, add-on, and pledge beneath it; its
    status is DRAFT; ... and its version is 1."

    Design: Corner/entities/create_campaign_minimal_returns_201_with_system_fields
    """
    creator = register_creator(api, payout_currency="USD")
    creator_headers = make_creator_headers(creator["id"])
    resp = api.create_campaign(
        create_campaign_payload(
            creator["id"], title="Camp", funding_goal_cents=50000,
            funding_model="ALL_OR_NOTHING", deadline_utc="2026-09-01T00:00:00.000Z",
        ),
        creator_headers,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT", f"Expected DRAFT, got {data['status']}"
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"
    assert data["currency"] == "USD", f"Expected currency USD, got {data['currency']}"


def test_get_campaign_nonexistent_returns_not_found(api):
    """PRD §2.6: "if any identifier in the path names a resource that does not exist, the
    request is rejected with ERR_NOT_FOUND (HTTP 404) before deeper identifiers or the
    request body are examined."

    Design: Corner/entities/get_campaign_nonexistent_returns_not_found
    """
    register_creator(api)
    resp = api.get_campaign(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_campaign_missing_required_field_returns_invalid_request(api):
    """PRD §3.5: "Then the body is checked for well-formedness — required fields present,
    enums valid, integers positive where required — failing with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_campaign_missing_required_field_returns_invalid_request
    """
    creator = register_creator(api)
    creator_headers = make_creator_headers(creator["id"])
    payload = {
        "creator_id": creator["id"],
        "title": "Camp",
        "funding_goal_cents": 50000,
        "deadline_utc": "2026-09-01T00:00:00.000Z",
    }  # funding_model omitted
    resp = api.create_campaign(payload, creator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_campaign_invalid_enum_funding_model_rejected(api):
    """PRD §3.1: "The funding_model is one of exactly two values, ALL_OR_NOTHING or FLEXIBLE."
    PRD §3.5: "Then the body is checked for well-formedness — required fields present,
    enums valid, integers positive where required — failing with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_campaign_invalid_enum_funding_model_rejected
    """
    creator = register_creator(api)
    creator_headers = make_creator_headers(creator["id"])
    resp = api.create_campaign(
        create_campaign_payload(
            creator["id"], funding_model="HYBRID",
            funding_goal_cents=50000, deadline_utc="2026-09-01T00:00:00.000Z",
        ),
        creator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_pledge_committed_amount_is_computed(api):
    """PRD §3.5: "the pledge's committed_amount_cents — the amount that will be authorized at
    close — is the items subtotal plus the shipping."
    PRD §3.6: "For a DOMESTIC destination, the shipping is a base of 500 cents plus 150 cents
    for every billable kilogram."

    Design: Corner/entities/pledge_committed_amount_is_computed_input_ignored
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, funding_model="FLEXIBLE", funding_goal_cents=1000,
        tier_overrides={"price_cents": 5000, "weight_grams": 800},
    )
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    resp = api.create_pledge(
        campaign["id"],
        create_pledge_payload(backer["id"], tier["id"], campaign["version"],
                              pledge_amount_cents=5000, destination_zone="DOMESTIC"),
        backer_headers,
    )
    data = validate_success(resp, 201)
    # items 5000 + ship(ceil(800/1000)=1kg -> 500 + 1*150 = 650) = 5650
    assert data["committed_amount_cents"] == 5650, (
        f"Expected committed 5650, got {data['committed_amount_cents']}"
    )


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers identifying the caller: X-User-ID and
    X-User-Role. If either header is absent, the request is rejected with ERR_MISSING_AUTH
    (HTTP 401) before any other processing."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    creator = register_creator(api)
    creator_headers = make_creator_headers(creator["id"])
    campaign = validate_success(
        api.create_campaign(create_campaign_payload(creator["id"]), creator_headers), 201
    )
    # Send the GET with no auth headers at all.
    resp = api.get_campaign(campaign["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


def test_pagination_limit_out_of_range_returns_validation_pagination(api):
    """PRD §2.3: "A request whose limit falls outside the inclusive range from 1 to 100, or
    whose offset is negative, is rejected with ERR_VALIDATION_PAGINATION (HTTP 422)."

    Design: Corner/validations/pagination_limit_out_of_range_returns_validation_pagination
    """
    register_creator(api)
    resp = api.list_campaigns(ADMIN, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)


def test_backer_cannot_create_campaign_returns_role_forbidden(api):
    """PRD §2.1: "If both headers are present but the role named in X-User-Role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_ROLE_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/backer_cannot_create_campaign_returns_role_forbidden
    """
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    resp = api.create_campaign(create_campaign_payload(backer["id"]), backer_headers)
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)


def test_creator_cannot_create_pledge_returns_role_forbidden(api):
    """PRD §2.1: "If both headers are present but the role named in X-User-Role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_ROLE_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/creator_cannot_create_pledge_returns_role_forbidden
    """
    creator, campaign, tier = create_live_campaign_with_tier(api)
    creator_headers = make_creator_headers(creator["id"])
    # Pledge create is Backer-exclusive; calling it as Creator must be rejected on role.
    resp = api.create_pledge(
        campaign["id"],
        create_pledge_payload(creator["id"], tier["id"], campaign["version"]),
        creator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)


def test_non_owner_creator_cannot_launch_returns_not_owner(api):
    """PRD §2.1: "When an entity-backed user is authenticated and authorized for the operation
    type but is not the owner of the specific target resource, the request is rejected with
    ERR_NOT_OWNER (HTTP 403). This applies to creator-owned actions (launching, ...)."

    Design: Corner/rbac/non_owner_creator_cannot_launch_returns_not_owner
    """
    set_clock(api, "2026-06-01T00:00:00.000Z")
    c1 = register_creator(api, display_name="C1")
    c2 = register_creator(api, display_name="C2")
    _, campaign = create_draft_campaign(api, creator=c1, set_clock_to=None)
    # tier so launch passes the ERR_NO_TIERS gate before ownership would matter — but
    # ownership (priority 6) is checked before state; assert wrong-owner is rejected.
    c1_headers = make_creator_headers(c1["id"])
    validate_success(api.create_tier(campaign["id"], create_tier_payload(), c1_headers), 201)
    c2_headers = make_creator_headers(c2["id"])
    resp = api.launch_campaign(campaign["id"], c2_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


def test_list_campaigns_paginated_envelope_shape(api):
    """PRD §2.3: "The pagination fields reported back in the meta object are limit, offset,
    total_count, and has_more, where total_count is the count of all matching records before
    the limit/offset window is applied and has_more indicates whether records remain beyond
    the returned page."

    Design: Corner/endpoints/list_campaigns_paginated_envelope_shape
    """
    creator = register_creator(api)
    creator_headers = make_creator_headers(creator["id"])
    validate_success(api.create_campaign(
        create_campaign_payload(creator["id"], title="A", funding_goal_cents=1000,
                                funding_model="FLEXIBLE", deadline_utc="2026-07-01T00:00:00.000Z"),
        creator_headers), 201)
    validate_success(api.create_campaign(
        create_campaign_payload(creator["id"], title="B", funding_goal_cents=2000,
                                funding_model="ALL_OR_NOTHING", deadline_utc="2026-08-01T00:00:00.000Z"),
        creator_headers), 201)
    resp = api.list_campaigns(ADMIN, params={"creator_id": creator["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"Expected 2 campaigns, got {len(data)}"
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False, f"Expected has_more False, got {meta['has_more']}"


def test_filtered_list_pledges_by_backer_id(api):
    """PRD §4: "List pledges, filterable by campaign_id, backer_id, tier_id".
    PRD §2.3: "List endpoints return their results sorted by created_at in ascending order."

    Design: Corner/endpoints/filtered_list_pledges_by_backer_id_reverse_reachability
    """
    creator, campaign, tier = create_live_campaign_with_tier(api)
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    pledge = validate_success(api.create_pledge(
        campaign["id"],
        create_pledge_payload(backer["id"], tier["id"], campaign["version"]),
        backer_headers), 201)
    resp = api.list_pledges(backer_headers, params={"backer_id": backer["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"Expected exactly 1 pledge, got {len(data)}"
    assert data[0]["id"] == pledge["id"]
    assert data[0]["backer_id"] == backer["id"]


def test_derived_committed_amount_visible_same_request(api):
    """PRD §2.8: "This system maintains a number of fields whose values are derived from other
    records and must always be reconciled in the same request that changes their inputs —
    never lazily. A campaign's projected and settled raise ... are all derived fields."

    Design: Corner/consistency_model/derived_committed_amount_visible_same_request
    """
    creator, campaign, tier = create_live_campaign_with_tier(
        api, tier_overrides={"price_cents": 5000, "weight_grams": 800})
    backer = register_backer(api)
    backer_headers = make_backer_headers(backer["id"])
    validate_success(api.create_pledge(
        campaign["id"],
        create_pledge_payload(backer["id"], tier["id"], campaign["version"],
                              pledge_amount_cents=5000, destination_zone="DOMESTIC"),
        backer_headers), 201)
    data = validate_success(api.get_campaign(campaign["id"], ADMIN), 200)
    assert data["committed_amount_cents"] == 5650, (
        f"Expected committed 5650 immediately after pledge, got {data['committed_amount_cents']}"
    )
