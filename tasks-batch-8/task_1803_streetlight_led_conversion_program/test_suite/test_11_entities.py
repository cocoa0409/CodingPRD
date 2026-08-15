"""Corner coverage: entity creation defaults, computed zone fields, uniqueness,
not-found, listing pagination/filtering, request-shape validation, and
salvage-item weight shape."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_district,
    assert_pole,
    assert_program,
    attest_pole_nameplate,
    create_account,
    create_active_program,
    create_batch,
    create_crew,
    create_district,
    create_pole,
    dispatch_and_complete,
    find_salvage_item_for_pole,
    get_salvage_item,
    setup_cleared_pole,
    setup_program_district_crew,
    setup_released_route,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]


def test_program_create_defaults_and_envelope(api):
    """PRD section 3.1: "The program is born DRAFT, its budget_balance_cents
    starts equal to program_budget_cents, and its computed rollups —
    current_billing_run_estimated_cents, converted_pole_count, and
    pending_salvage_item_count — start at zero."
    PRD section 2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format"; PRD section 4: "Endpoints that create
    a new resource respond 201".

    Design: Corner/entities/entity_program_create_defaults_envelope
    """
    resp = api.list_programs(PM)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0 and meta["has_more"] is False and data == []

    resp = api.create_program(
        {
            "program_name": "P0",
            "program_budget_cents": 1000000,
            "fy_rebate_cap_cents": 50000,
            "rebate_cents_per_kwh": 25,
        },
        PM,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    program = body["data"]
    assert_program(program)
    assert program["status"] == "DRAFT"
    assert program["budget_balance_cents"] == 1000000
    assert program["current_billing_run_estimated_cents"] == 0
    assert program["converted_pole_count"] == 0
    assert program["pending_salvage_item_count"] == 0
    assert program["version"] == 1


def test_district_zone_derived_fields(api):
    """PRD section 2.6: "The district's cct_cap_kelvin is 3000 for RESIDENTIAL,
    4000 for ARTERIAL, 2700 for DOWNTOWN, and 2200 for RURAL. Its
    full_cutoff_required flag is true in RESIDENTIAL and RURAL districts and
    false in ARTERIAL and DOWNTOWN districts. Both values are derived at
    district creation".

    Design: Corner/entities/entity_district_zone_derived_fields
    """
    program = create_active_program()
    rural = create_district(program["id"], zone="RURAL", district_name="DR")
    arterial = create_district(program["id"], zone="ARTERIAL", district_name="DA")
    assert_district(rural)
    assert_district(arterial)
    assert rural["cct_cap_kelvin"] == 2200 and rural["full_cutoff_required"] is True
    assert arterial["cct_cap_kelvin"] == 4000 and arterial["full_cutoff_required"] is False


def test_pole_duplicate_number_rejected_across_districts(api):
    """PRD section 3.1: "a pole_number that must be unique across the whole
    program regardless of district (a collision is ERR_DUPLICATE_POLE_NUMBER)".

    Design: Corner/entities/entity_pole_duplicate_number_rejected
    """
    program = create_active_program()
    d1 = create_district(program["id"], zone="RESIDENTIAL", district_name="D1")
    d2 = create_district(program["id"], zone="RURAL", district_name="D2")
    create_pole(d1["id"], pole_number="M-001", ownership_type="MUNICIPAL",
                fixture_class="COBRA_HEAD", nameplate_wattage=250)
    resp = api.create_pole(
        {
            "district_id": d2["id"],
            "pole_number": "M-001",
            "ownership_type": "UTILITY_OWNED",
            "fixture_class": "FLOOD",
            "nameplate_wattage": 150,
        },
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLE_NUMBER, expected_status=409)
    resp = api.list_poles(PM, params={"district_id": d2["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 0


def test_pole_get_not_found_returns_404(api):
    """PRD section 2.9: "Each missing resource yields its own 404: an unknown
    program id yields `ERR_PROGRAM_NOT_FOUND`, district
    `ERR_DISTRICT_NOT_FOUND`, pole `ERR_POLE_NOT_FOUND`".

    Design: Corner/entities/entity_pole_get_not_found_returns_404
    """
    resp = api.get_pole(NON_EXISTENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_POLE_NOT_FOUND, expected_status=404)
    assert resp.json()["response_type"] == "error"


def test_pole_list_pagination_and_status_filter(api):
    """PRD section 2.3: "The limit parameter defaults to 10, with a minimum of 1
    and a maximum of 100; offset defaults to 0. The meta object of a list
    response carries the pagination fields limit, offset, total_count, and
    has_more."; PRD section 3.1: "The pole listing filters by district_id,
    status, and ownership_type."

    Design: Corner/entities/entity_list_pagination_and_status_filter
    """
    program = create_active_program()
    district = create_district(program["id"], zone="RESIDENTIAL", district_name="D1")
    for i in range(1, 13):
        pole = create_pole(district["id"], pole_number=f"L-{i:02d}",
                           ownership_type="UTILITY_OWNED", fixture_class="COBRA_HEAD",
                           nameplate_wattage=250)
        if i <= 3:
            attest_pole_nameplate(pole["id"])

    resp = api.list_poles(BA, params={"district_id": district["id"], "limit": 5, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert len(page1) == 5
    assert meta1["total_count"] == 12 and meta1["has_more"] is True
    for pole in page1:
        assert_pole(pole)

    resp = api.list_poles(BA, params={"district_id": district["id"], "limit": 5, "offset": 10})
    page3, meta3 = validate_paginated(resp)
    assert len(page3) == 2 and meta3["has_more"] is False

    resp = api.list_poles(BA, params={"district_id": district["id"], "status": "AUDIT_CLEARED"})
    _data, meta_f = validate_paginated(resp)
    assert meta_f["total_count"] == 3


def test_district_invalid_enum_and_missing_required_rejected(api):
    """PRD section 2.10: "2. Request shape: the body parses; required fields are
    present; types match; enum values are valid; date strings are ISO ... any
    failure is ERR_INVALID_REQUEST" — and request shape (stage 2) precedes
    "4. Existence: path and body identifiers resolve, per §2.9."

    Design: Corner/entities/entity_district_invalid_enum_and_missing_required_rejected
    """
    program = create_active_program()
    # bad enum zone AND a bogus program_id: shape beats existence
    resp = api.create_district(
        {"program_id": NON_EXISTENT_UUID, "district_name": "BAD", "zone": "UPTOWN"}, PM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    # missing required district_name
    resp = api.create_district({"program_id": program["id"], "zone": "RURAL"}, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_salvage_item_weight_two_decimals_rejected(api):
    """PRD section 2.10: "a provided weight_lbs is positive with at most one
    decimal place ... any failure is ERR_INVALID_REQUEST"; PRD section 3.7:
    "a provided weight_lbs positive with at most one decimal place
    (ERR_INVALID_REQUEST)."

    Design: Corner/entities/entity_salvage_item_weight_invalid_request
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="W-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-02", end="2026-08-02")
    dispatch_and_complete(wos[0]["id"], crew["id"], wattage=90, cct=2700,
                          shielding="FULL_CUTOFF")
    item = find_salvage_item_for_pole(pole["id"])
    batch = create_batch(program["id"], batch_label="B-W")

    resp = api.add_salvage_item(
        batch["id"],
        {"salvage_item_id": item["id"], "weight_lbs": 10.55, "mercury_flag": False},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    # rejected add leaves the pool unchanged
    assert get_salvage_item(item["id"])["batch_id"] is None
