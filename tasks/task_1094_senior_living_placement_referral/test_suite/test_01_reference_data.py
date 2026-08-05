"""Reference-data creation, request-shape validation, pagination and not-found.

Every test here translates exactly one non-stub corner-design instance; see the
Design: line at the end of each docstring.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    create_community_payload, create_family_payload, create_inventory_payload,
    create_advisor, create_community, create_family, create_inventory, set_clock,
    build_scenario,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_community_create_returns_201_with_system_defaults(api):
    """PRD §3.1: "A new community's `status` is `ACTIVE` and its three computed
    roll-ups — `fee_balance_cents`, `satisfaction_survey_count` and
    `avg_satisfaction_score` — start at 0."
    PRD §2.4: "an integer `version` that begins at 1 when the row is created".

    Design: Corner/entities/community_create_returns_201_with_system_defaults_applied
    """
    resp = api.create_community(
        create_community_payload(name="Cedar Grove", tour_slot_capacity=2), ADMIN)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["fee_balance_cents"] == 0
    assert data["satisfaction_survey_count"] == 0
    assert data["avg_satisfaction_score"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]), "id must be a dashed UUID with no type prefix"
    body = resp.json()
    assert body["response_type"] == "object"
    assert str(body["meta"]["api_request_id"]).startswith("req_")
    assert body["meta"]["api_request_timestamp"]


def test_unknown_ids_return_entity_specific_not_found_codes(api):
    """PRD §2.6: "If it fails to resolve to a stored row, the request is rejected
    with the not-found error specific to that resource type — `ERR_FAMILY_NOT_FOUND`,
    `ERR_ADVISOR_NOT_FOUND`, `ERR_COMMUNITY_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`,
    `ERR_INQUIRY_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`,
    `ERR_TOUR_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
    `ERR_GUIDANCE_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`
    or `ERR_ASSIGNMENT_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/unknown_ids_return_entity_specific_not_found_codes
    """
    u = "00000000-0000-4000-8000-0000000000{:02d}"
    cases = [
        (api.get_community(u.format(1), ADMIN), ApiErrorId.ERR_COMMUNITY_NOT_FOUND),
        (api.get_inquiry(u.format(2), ADMIN), ApiErrorId.ERR_INQUIRY_NOT_FOUND),
        (api.get_tour(u.format(3), ADMIN), ApiErrorId.ERR_TOUR_NOT_FOUND),
        (api.get_survey(u.format(4), ADMIN), ApiErrorId.ERR_SURVEY_NOT_FOUND),
        (api.get_ledger_entry(u.format(5), ADMIN), ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
        (api.get_caseload_assignment(u.format(6), ADMIN), ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        (api.get_guidance(u.format(7), ADMIN), ApiErrorId.ERR_GUIDANCE_NOT_FOUND),
        (api.get_invoice(u.format(8), ADMIN), ApiErrorId.ERR_INVOICE_NOT_FOUND),
        (api.get_placement(u.format(9), ADMIN), ApiErrorId.ERR_PLACEMENT_NOT_FOUND),
        (api.get_match(u.format(10), ADMIN), ApiErrorId.ERR_MATCH_NOT_FOUND),
        (api.get_assessment(u.format(11), ADMIN), ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        (api.get_inventory(u.format(12), ADMIN), ApiErrorId.ERR_INVENTORY_NOT_FOUND),
        (api.get_advisor(u.format(13), ADMIN), ApiErrorId.ERR_ADVISOR_NOT_FOUND),
        (api.get_family(u.format(14), ADMIN), ApiErrorId.ERR_FAMILY_NOT_FOUND),
    ]
    for resp, err in cases:
        err_data = validate_error(resp, err)
        assert err_data.get("message"), "not-found body must carry a non-empty message"


def test_advisors_list_pagination_envelope(api):
    """PRD §2.3: "`has_more` which is true exactly when `offset` plus the number of
    rows returned in this page is strictly less than `total_count`."
    PRD §2.3: "Filters offered by individual list endpoints ... combine
    conjunctively: a request supplying two filters returns only the rows satisfying
    both."

    Design: Corner/entities/advisors_list_returns_pagination_envelope_with_limit_and_offset
    """
    create_advisor(api, full_name="Ann Reyes", region_code="TX-AUS")
    create_advisor(api, full_name="Ben Cho", region_code="TX-AUS", is_va_certified=True)
    cara = create_advisor(api, full_name="Cara Diaz", region_code="TX-DAL", caseload_capacity=5)

    data, meta = validate_paginated(api.list_advisors(ADMIN, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2 and meta["offset"] == 0

    data2, meta2 = validate_paginated(api.list_advisors(ADMIN, params={"limit": 2, "offset": 2}))
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    data3, meta3 = validate_paginated(api.list_advisors(ADMIN, params={"region_code": "TX-DAL"}))
    assert len(data3) == 1
    assert data3[0]["id"] == cara["id"]
    assert data3[0]["region_code"] == "TX-DAL"
    assert meta3["total_count"] == 1


def test_inquiry_create_missing_required_budget_returns_validation(api):
    """PRD §2.7: "Request-body shape — every required field present, types correct,
    enum members legal, integers within their declared ranges, dates well-formed
    ISO 8601, and no unknown key that collides with a system- or computed-field
    name; any failure is `ERR_VALIDATION` (422)."

    Design: Corner/entities/inquiry_create_missing_required_declared_budget_returns_validation
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    family = create_family(api)
    resp = api.create_inquiry({
        "family_id": family["id"], "origin": "WEB", "region_code": "TX-AUS",
        "requested_care_level": "ASSISTED_LIVING", "target_move_in_date": "2026-06-20",
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, _ = validate_paginated(api.list_inquiries(ADMIN, params={"family_id": family["id"]}))
    assert rows == []


def test_inquiry_create_rejects_illegal_origin_enum(api):
    """PRD §2.7: "Request-body shape — every required field present, types correct,
    enum members legal, integers within their declared ranges, dates well-formed
    ISO 8601 ... any failure is `ERR_VALIDATION` (422)."

    Design: Corner/entities/inquiry_create_rejects_illegal_origin_enum_member
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    family = create_family(api)
    resp = api.create_inquiry({
        "family_id": family["id"], "origin": "MAILER", "region_code": "TX-AUS",
        "requested_care_level": "ASSISTED_LIVING", "target_move_in_date": "2026-06-20",
        "declared_budget_monthly_cents": 520000,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, _ = validate_paginated(api.list_inquiries(ADMIN, params={"family_id": family["id"]}))
    assert rows == []


def test_inventory_create_rejects_client_supplied_computed_field(api):
    """PRD §2.7: "Request-body shape — every required field present ... and no
    unknown key that collides with a system- or computed-field name; any failure
    is `ERR_VALIDATION` (422)."

    Design: Corner/entities/inventory_create_rejects_client_supplied_computed_available_units
    """
    community = create_community(api)
    resp = api.create_inventory({
        "community_id": community["id"], "care_level": "ASSISTED_LIVING",
        "total_units": 5, "monthly_rate_cents": 500000, "available_units": 99,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, _ = validate_paginated(api.list_inventories(ADMIN, params={"community_id": community["id"]}))
    assert rows == []


def test_second_inventory_same_care_level_returns_duplicate(api):
    """PRD §3.1: "At most one pool may exist per community-and-care-level
    combination; a second attempt for the same pair is rejected with
    `ERR_DUPLICATE_INVENTORY`."

    Design: Corner/validations/second_inventory_for_same_community_and_care_level_returns_duplicate_inventory
    """
    community = create_community(api)
    first = create_inventory(api, community["id"], care_level="ASSISTED_LIVING",
                             monthly_rate_cents=500000)
    resp = api.create_inventory(
        create_inventory_payload(community["id"], care_level="ASSISTED_LIVING",
                                 total_units=2, monthly_rate_cents=450000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVENTORY)
    rows, _ = validate_paginated(api.list_inventories(ADMIN, params={"community_id": community["id"]}))
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["monthly_rate_cents"] == 500000


def test_shrinking_inventory_below_allocated_returns_under_allocated(api):
    """PRD §3.1: "An edit that would drop `total_units` below the sum of
    `reserved_units` and `occupied_units` is rejected with
    `ERR_INVENTORY_UNDER_ALLOCATED`, so the platform never oversells a pool that
    already has residents or reservations."

    Design: Corner/validations/shrinking_inventory_below_allocated_units_returns_inventory_under_allocated
    """
    sc = build_scenario(api, "pending", inventory_overrides={"total_units": 5})
    inv_id = sc["inventory"]["id"]
    resp = api.update_inventory(inv_id, {"total_units": 0}, sc["cm_headers"])
    validate_error(resp, ApiErrorId.ERR_INVENTORY_UNDER_ALLOCATED)
    inv = validate_success(api.get_inventory(inv_id, ADMIN))
    assert inv["total_units"] == 5
    assert inv["reserved_units"] == 1
    assert inv["available_units"] == 4


def test_inquiry_with_past_target_move_in_date_rejected(api):
    """PRD §3.2: "The `target_move_in_date` must be on or after the logical clock's
    current UTC calendar date; a past date is rejected with
    `ERR_MOVE_IN_DATE_INVALID`."

    Design: Corner/validations/inquiry_with_past_target_move_in_date_returns_move_in_date_invalid
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    family = create_family(api)
    resp = api.create_inquiry({
        "family_id": family["id"], "origin": "WEB", "region_code": "TX-AUS",
        "requested_care_level": "ASSISTED_LIVING", "target_move_in_date": "2026-05-15",
        "declared_budget_monthly_cents": 520000,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_MOVE_IN_DATE_INVALID)
    rows, _ = validate_paginated(api.list_inquiries(ADMIN, params={"family_id": family["id"]}))
    assert rows == []
