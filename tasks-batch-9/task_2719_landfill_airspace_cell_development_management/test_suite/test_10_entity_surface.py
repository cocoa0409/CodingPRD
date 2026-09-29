"""Breadth over the entity surface: creation shapes, defaults, computed and system fields."""
from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_amount,
    assert_cell,
    assert_common_fields,
    assert_density,
    assert_landfill,
)
from test_helpers.constants import DECLARED_DEFAULTS, PAGINATION, UNKNOWN_UUID
from test_helpers.factories import (
    aerial_survey_payload,
    cell_payload,
    closure_cost_estimate_payload,
    gas_well_payload,
    landfill_payload,
    leachate_shipment_payload,
    liner_qa_package_payload,
    special_waste_approval_payload,
    surface_emission_scan_payload,
    treatment_agreement_payload,
    waste_load_payload,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_scale_operator_headers,
    make_site_operator_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CQA_ENGINEER = TEST_USERS["cqa_engineer_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]

RESERVE_CELL = {"cell_code": "C-1", "design_airspace_cy": 1000000, "design_area_sf": 120001}
SECOND_CELL = {"cell_code": "C-2", "design_airspace_cy": 200, "design_area_sf": 45001}
THIRD_CELL = {
    "cell_code": "C-3",
    "design_airspace_cy": 300,
    "design_area_sf": 45001,
    "liner_type": "GCL_ONLY",
}


def test_registering_a_site_returns_every_declared_field_at_its_start_value():
    """The create response carries the echoed permit inputs and the conservative posture.

    PRD: "Registration leaves the site in a deliberately empty and deliberately
    conservative posture: `operating_status` `OPEN`, `gas_collection_status` `COMPLIANT`,
    `financial_assurance_status` `UNFUNDED`, `assurance_funded_amount` zero, and every
    computed airspace figure — `certified_airspace_cy`, `consumed_airspace_cy`,
    `remaining_airspace_cy`, `remaining_life_years` and `active_cell_count` — at zero, with
    `version` at 1."

    Design: Corner/entities/landfill_creation_returns_the_full_row_inside_the_success_envelope
    """
    response = api_client.create_landfill(
        landfill_payload(daily_load_limit=250), PLATFORM_ADMIN
    )

    data = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    assert_landfill(data)
    assert_common_fields(data, expected_version=1)
    assert is_valid_uuid(data["id"]) and "_" not in data["id"]
    assert data["name"] == "Ridgeview MSW"
    assert data["permit_number"] == "MSW-4417"
    assert_amount(data["permitted_total_airspace_cy"], 5000000, "permitted total airspace")
    assert_amount(data["design_footprint_sf"], 400000, "design footprint")
    assert_density(data["planned_density_tons_per_cy"], 0.90, "planned density")
    assert_amount(data["annual_tonnage_forecast"], 300000, "annual tonnage forecast")
    assert int(data["daily_load_limit"]) == 250

    assert data["operating_status"] == "OPEN"
    assert data["gas_collection_status"] == "COMPLIANT"
    assert data["financial_assurance_status"] == "UNFUNDED"
    assert_amount(data["assurance_funded_amount"], 0, "assurance funded amount")
    assert_amount(data["certified_airspace_cy"], 0, "certified airspace")
    assert_amount(data["consumed_airspace_cy"], 0, "consumed airspace")
    assert_amount(data["remaining_airspace_cy"], 0, "remaining airspace")
    assert_amount(data["remaining_life_years"], 0, "remaining life years")
    assert int(data["active_cell_count"]) == 0


def test_reading_a_site_twice_does_not_move_its_version():
    """A GET is side-effect free, so the version stays where creation left it.

    PRD: "`version` is an integer that starts at 1 when the row is created and is
    incremented by exactly 1 on every mutation of that row, whether the mutation came from
    a direct client call or from a cascade fired by a call against some other resource."

    Design: Corner/entities/landfill_get_returns_the_stored_row_unchanged
    """
    landfill = fixtures.create_landfill()

    first = validate_success(api_client.get_landfill(landfill["id"], SURVEYOR), 200)
    second = validate_success(api_client.get_landfill(landfill["id"], SURVEYOR), 200)

    assert first["id"] == landfill["id"]
    assert first["permit_number"] == "MSW-4417"
    assert int(first["version"]) == 1
    assert int(second["version"]) == 1, "two reads do not mutate the row"
    assert second == first, "the stored row comes back unchanged"


def _two_sites_with_four_cells():
    """LF-A owns C-1 (UNDER_CONSTRUCTION), C-2 and C-3 (DESIGN); LF-B owns C-9 (DESIGN)."""
    lfa = fixtures.create_landfill()
    lfb = fixtures.create_landfill(name="Eastbank MSW", permit_number="MSW-9902")
    c1 = fixtures.create_cell(lfa["id"], **RESERVE_CELL)
    fixtures.create_cell(lfa["id"], **SECOND_CELL)
    fixtures.create_cell(lfa["id"], **THIRD_CELL)
    c9 = fixtures.create_cell(
        lfb["id"],
        cell_code="C-9",
        design_airspace_cy=500,
        design_area_sf=45001,
        liner_type="SINGLE_COMPOSITE",
    )
    fixtures.begin_construction(lfa["id"], c1["id"])
    return lfa, lfb, c1, c9


def test_the_filtered_total_count_survives_the_page_window():
    """Two pages of the same three-cell filter report total_count 3 either way.

    PRD: "List responses carry the four pagination fields inside `meta`: the effective
    `limit`, the effective `offset`, `total_count` (the number of rows matching the filter
    *before* the page window is applied) and `has_more` (true when rows remain beyond the
    current window)."

    Design: Corner/entities/cells_list_combines_filter_paging_and_totals
    """
    lfa, _lfb, _c1, _c9 = _two_sites_with_four_cells()

    first_page, first_meta = validate_paginated(
        api_client.list_cells(PLATFORM_ADMIN, {"landfill_id": lfa["id"], "limit": 2, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api_client.list_cells(PLATFORM_ADMIN, {"landfill_id": lfa["id"], "limit": 2, "offset": 2})
    )

    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2
    for row in first_page + second_page:
        assert row["landfill_id"] == lfa["id"]


def test_the_status_filter_composes_with_the_landfill_filter():
    """DESIGN on LF-A names C-2 and C-3 only: C-1 has broken ground and C-9 is elsewhere.

    PRD: "Cells may be filtered by `landfill_id`, by `piggyback_over_cell_id` and by
    `status`."

    Design: Corner/entities/cells_list_combines_filter_paging_and_totals
    """
    lfa, _lfb, c1, _c9 = _two_sites_with_four_cells()

    rows, meta = validate_paginated(
        api_client.list_cells(PLATFORM_ADMIN, {"landfill_id": lfa["id"], "status": "DESIGN"})
    )

    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert sorted(row["cell_code"] for row in rows) == ["C-2", "C-3"]
    assert c1["id"] not in [row["id"] for row in rows]
    for row in rows:
        assert row["status"] == "DESIGN"
        assert row["landfill_id"] == lfa["id"]


def test_the_sub_resource_listing_scopes_to_its_own_parent_at_the_default_window():
    """A landfill's own cells route needs no filter and defaults to limit 10, offset 0.

    PRD: "The four sub-resource listings — a landfill's cells, a cell's liner packages, a
    cell's gas wells, an operating day's waste loads and an agreement's leachate shipments —
    accept the same `limit` and `offset` plus the state filter appropriate to the child
    resource."

    Design: Corner/entities/cells_list_combines_filter_paging_and_totals
    """
    _lfa, lfb, _c1, c9 = _two_sites_with_four_cells()

    rows, meta = validate_paginated(api_client.list_landfill_cells(lfb["id"], PLATFORM_ADMIN))

    assert meta["total_count"] == 1
    assert meta["limit"] == PAGINATION["DEFAULT_LIMIT"]
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == c9["id"]
    assert rows[0]["cell_code"] == "C-9"
    assert_cell(rows[0])


def test_an_unresolvable_path_id_answers_with_that_resource_types_not_found():
    """Both a read and an action addressed to a phantom cell answer ERR_CELL_NOT_FOUND.

    PRD: "**Path ids resolve** — on every endpoint carrying an id in its path, validated
    strictly left to right. Each miss returns that resource type's own not-found error:
    `ERR_LANDFILL_NOT_FOUND`, `ERR_CELL_NOT_FOUND`, `ERR_LINER_QA_PACKAGE_NOT_FOUND`,
    `ERR_AERIAL_SURVEY_NOT_FOUND`, `ERR_OPERATING_DAY_NOT_FOUND`, `ERR_WASTE_LOAD_NOT_FOUND`,
    `ERR_SPECIAL_WASTE_APPROVAL_NOT_FOUND`, `ERR_TREATMENT_AGREEMENT_NOT_FOUND`,
    `ERR_LEACHATE_SHIPMENT_NOT_FOUND`, `ERR_GAS_WELL_NOT_FOUND`,
    `ERR_SURFACE_EMISSION_SCAN_NOT_FOUND`, `ERR_CLOSURE_COST_ESTIMATE_NOT_FOUND` or
    `ERR_HOST_COMMUNITY_AGREEMENT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/unknown_ids_in_path_and_body_return_entity_specific_not_found
    """
    landfill = fixtures.create_landfill()

    read = api_client.get_cell(UNKNOWN_UUID, PLATFORM_ADMIN)
    action = api_client.begin_cell_construction(
        UNKNOWN_UUID, make_site_operator_headers(landfill["id"])
    )

    validate_error(read, ApiErrorId.ERR_CELL_NOT_FOUND.value, 404)
    validate_error(action, ApiErrorId.ERR_CELL_NOT_FOUND.value, 404)


def test_an_unresolvable_body_foreign_key_answers_before_any_business_rule():
    """A cell aimed at a phantom site reports the landfill miss and stores nothing.

    PRD: "Body foreign keys are resolved in the order the endpoint declares its input
    fields, and each unresolved key reports its own resource type's not-found error before
    any business rule is consulted."

    Design: Corner/entities/unknown_ids_in_path_and_body_return_entity_specific_not_found
    """
    fixtures.create_landfill()

    response = api_client.create_cell(
        cell_payload(UNKNOWN_UUID, **SECOND_CELL), make_site_operator_headers(UNKNOWN_UUID)
    )

    validate_error(response, ApiErrorId.ERR_LANDFILL_NOT_FOUND.value, 404)
    _rows, meta = validate_paginated(api_client.list_cells(PLATFORM_ADMIN))
    assert meta["total_count"] == 0, "no Cell row is created by a refused create"


def test_a_cell_create_missing_a_required_field_is_refused_before_any_lookup():
    """An omitted liner_type and an omitted airspace both stop at the shape rung.

    PRD: "**Request body shape** — on every write endpoint. Every required input field must
    be present and non-null, every field must carry its declared JSON type, every enumerated
    field must carry a declared member, every ISO-8601 timestamp must parse, and every
    quantity that must be positive (tonnages, gallons, areas, counts, unit costs) must be
    greater than zero."

    Design: Corner/entities/cell_create_missing_required_fields_is_rejected
    """
    landfill = fixtures.create_landfill()
    without_liner = cell_payload(landfill["id"], **SECOND_CELL)
    without_liner.pop("liner_type")
    without_airspace = cell_payload(UNKNOWN_UUID, **SECOND_CELL)
    without_airspace.pop("design_airspace_cy")

    refused_liner = api_client.create_cell(
        without_liner, make_site_operator_headers(landfill["id"])
    )
    refused_airspace = api_client.create_cell(
        without_airspace, make_site_operator_headers(UNKNOWN_UUID)
    )

    validate_error(refused_liner, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(refused_airspace, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _rows, meta = validate_paginated(api_client.list_cells(PLATFORM_ADMIN))
    assert meta["total_count"] == 0, "neither malformed create stored a Cell row"


def test_an_omitted_daily_load_limit_takes_its_declared_default():
    """The scale-house ceiling is 200 loads a day when the registrant says nothing.

    PRD: "A registrant may also supply `daily_load_limit`, the maximum number of non-rejected
    loads the scale house may accept on one operating day; when omitted it defaults to 200,
    and it must be at least 1 and at most 2000."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    payload = landfill_payload()
    assert "daily_load_limit" not in payload

    data = validate_success(api_client.create_landfill(payload, PLATFORM_ADMIN), 201)

    assert int(data["daily_load_limit"]) == DECLARED_DEFAULTS["daily_load_limit"]
    assert int(data["daily_load_limit"]) == 200


def test_an_omitted_piggyback_parent_leaves_the_cell_standing_on_native_ground():
    """No vertical expansion was declared, so the parent reference is null.

    PRD: "Where a site expands vertically over ground it has already filled, the operator
    supplies `piggyback_over_cell_id` naming the older cell the new one is built over. The
    field is optional and defaults to null."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    landfill = fixtures.create_landfill()
    payload = cell_payload(landfill["id"], **SECOND_CELL)
    assert "piggyback_over_cell_id" not in payload

    data = validate_success(
        api_client.create_cell(payload, make_site_operator_headers(landfill["id"])), 201
    )

    assert data["piggyback_over_cell_id"] is DECLARED_DEFAULTS["piggyback_over_cell_id"]
    assert data["status"] == "DESIGN"


def test_an_omitted_slot_capacity_takes_the_two_slot_default():
    """The receiving gate holds two overlapping tankers unless the contract says otherwise.

    PRD: "`concurrent_slot_capacity` — how many non-terminal shipments may have overlapping
    delivery windows at the receiving gate — is optional and defaults to 2, and must be at
    least 1 and at most 10."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    landfill = fixtures.create_landfill()
    payload = treatment_agreement_payload(
        landfill["id"],
        facility_name="Valley POTW",
        daily_gallon_cap=20000,
        base_haul_fee=350.00,
        treatment_rate_per_kgal=62.50,
        expires_on="2026-12-31T00:00:00Z",
    )
    assert "concurrent_slot_capacity" not in payload

    data = validate_success(api_client.create_treatment_agreement(payload, ENV_MANAGER), 201)

    assert int(data["concurrent_slot_capacity"]) == DECLARED_DEFAULTS["concurrent_slot_capacity"]
    assert int(data["concurrent_slot_capacity"]) == 2
    assert_amount(data["scheduled_gallons_today"], 0, "scheduled gallons today")
    assert data["status"] == "ACTIVE"


def test_an_omitted_care_period_prices_thirty_inflated_years():
    """The 30-year default is visible in the money: 4,519,664.50 of post-closure care.

    PRD: "`post_closure_years` sets the length of the care period and is optional: when
    omitted it defaults to 30 years, and it must be at least 1 and at most 60."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    landfill = fixtures.create_landfill()
    payload = closure_cost_estimate_payload(
        landfill["id"], fixtures.landfill_version(landfill["id"])
    )
    payload.pop("post_closure_years")

    data = validate_success(
        api_client.create_closure_cost_estimate(payload, FINANCE_FILER), 201
    )

    assert int(data["post_closure_years"]) == DECLARED_DEFAULTS["post_closure_years"]
    assert data["status"] == "DRAFT"
    assert_amount(data["closure_cost_total"], 0.00, "closure cost total")
    assert_amount(data["post_closure_cost_total"], 4519664.50, "post-closure cost total")
    assert_amount(data["required_assurance_amount"], 4519664.50, "required assurance")


def test_a_scan_below_the_exceedance_reading_simply_passes():
    """499.9 ppm is under the 500 ppm trigger, so nothing but a PASSED row happens.

    PRD: "Below 500 parts per million the scan is recorded as `PASSED` and nothing else
    happens."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    landfill = fixtures.create_landfill()
    payload = surface_emission_scan_payload(
        landfill["id"], grid_points_count=40, max_reading_ppm=499.9
    )
    assert "exceedance_point_ref" not in payload

    data = validate_success(
        api_client.create_surface_emission_scan(payload, ENV_MANAGER), 201
    )

    assert data["status"] == "PASSED"
    assert data["corrective_well_id"] is None
    assert data["remediation_note"] is None
    assert fixtures.read_landfill(landfill["id"])["gas_collection_status"] == "COMPLIANT"


def test_the_conformance_score_is_computed_from_the_five_submitted_counters():
    """4,000 feet, 20 of 20 passing and 2 defects on 40 panels score exactly 100.00.

    PRD: "The score itself is one hundred multiplied by the test pass rate multiplied by the
    coverage factor, minus that already-rounded defect penalty; the difference is then
    clamped so it can be no lower than 0.0 and no higher than 100.0, and the clamped result
    is rounded to 2 decimal places."

    Design: Corner/entities/computed_fields_are_derived_server_side_from_declared_inputs
    """
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell_under_construction(landfill["id"], **RESERVE_CELL)
    payload = liner_qa_package_payload(cell["id"])
    assert "qa_conformance_score" not in payload, "the score is not a client input"

    data = validate_success(
        api_client.create_liner_qa_package(
            payload, make_site_operator_headers(landfill["id"])
        ),
        201,
    )

    assert_amount(data["qa_conformance_score"], 100.00, "qa conformance score")
    assert int(data["revision_round"]) == 1
    assert data["status"] == "SUBMITTED"


def test_a_new_cell_reports_zero_consumption_and_zero_fill():
    """Nothing has been placed yet, so both consumption figures read zero, not null.

    PRD: "At creation the cell's `status` is `DESIGN`, its `consumed_airspace_cy` and
    `fill_pct` are both zero, its `authorized_by_agency_user_id` and `final_cover_reference`
    are null, and its `version` is 1."

    Design: Corner/entities/computed_fields_are_derived_server_side_from_declared_inputs
    """
    landfill = fixtures.create_landfill()

    data = validate_success(
        api_client.create_cell(
            cell_payload(landfill["id"], **RESERVE_CELL),
            make_site_operator_headers(landfill["id"]),
        ),
        201,
    )

    assert_cell(data)
    assert_common_fields(data, expected_version=1)
    assert data["status"] == "DESIGN"
    assert_amount(data["consumed_airspace_cy"], 0, "consumed airspace")
    assert_amount(data["fill_pct"], 0, "fill percentage")


def test_the_first_survey_reduces_against_the_sites_certified_airspace():
    """1,000,000 certified less 700,000 surveyed is 300,000 cubic yards at 0.8333 tons.

    The design's own setup leaves the cell in `UNDER_CONSTRUCTION`, which would put
    `certified_airspace_cy` at zero and make the quoted 300,000 unreachable; the cell is
    therefore carried through to `QA_CERTIFIED` so the certified basis is the intended
    1,000,000 cubic yards.

    PRD: "When the site has no `RECORDED` survey — the first flight ever, or the first after
    a void left nothing behind — the consumed figure is instead the site's
    `certified_airspace_cy` minus the new survey's `measured_remaining_airspace_cy`, rounded
    to 2 decimal places."

    Design: Corner/entities/computed_fields_are_derived_server_side_from_declared_inputs
    """
    landfill = fixtures.create_landfill()
    fixtures.setup_qa_certified_cell(landfill["id"], cell_overrides=RESERVE_CELL)
    assert_amount(
        fixtures.read_landfill(landfill["id"])["certified_airspace_cy"],
        1000000,
        "certified airspace",
    )
    payload = aerial_survey_payload(
        landfill["id"],
        coverage_period_start="2026-05-01T00:00:00Z",
        coverage_period_end="2026-07-31T00:00:00Z",
        measured_remaining_airspace_cy=700000,
        tons_placed_in_period=250000,
    )
    assert "measured_density_tons_per_cy" not in payload, "the density is not a client input"

    data = validate_success(api_client.create_aerial_survey(payload, SURVEYOR), 201)

    assert data["status"] == "RECORDED"
    assert_amount(data["airspace_consumed_in_period_cy"], 300000.00, "consumed in period")
    assert_density(data["measured_density_tons_per_cy"], 0.8333, "measured density")


def test_package_creation_stamps_the_submitter_and_leaves_the_reviewer_null():
    """The SiteOperator's X-User-ID is the landfill id, and that is what is recorded.

    PRD: "On acceptance the package's `qa_conformance_score` is computed, its `status` is
    `SUBMITTED`, its `revision_round` is 1, its `submitted_by_user_id` is stamped with the
    submitting `X-User-ID`, its `reviewed_by_user_id` and `certification_reference` are null
    and its `version` is 1 — and the parent cell moves `UNDER_CONSTRUCTION → QA_REVIEW` with
    its own `version` incremented by 1."

    Design: Corner/entities/system_fields_are_server_minted_and_record_the_acting_user
    """
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell_under_construction(landfill["id"], **RESERVE_CELL)

    data = validate_success(
        api_client.create_liner_qa_package(
            liner_qa_package_payload(cell["id"]), make_site_operator_headers(landfill["id"])
        ),
        201,
    )

    assert data["submitted_by_user_id"] == landfill["id"]
    assert data["reviewed_by_user_id"] is None
    assert data["certification_reference"] is None
    assert data["status"] == "SUBMITTED"
    assert_common_fields(data, expected_version=1)
    reread_cell = get_success_data(api_client.get_cell(cell["id"], AGENCY))
    assert reread_cell["status"] == "QA_REVIEW"
    assert int(reread_cell["version"]) == int(cell["version"]) + 1


def test_opening_review_records_the_reviewing_engineer_and_bumps_the_version_by_one():
    """The reviewer id appears only once a review actually begins, at version 2.

    PRD: "Review is opened by a `CqaEngineer`, moving the package `SUBMITTED → UNDER_REVIEW`
    and stamping `reviewed_by_user_id` with the reviewing `X-User-ID`, with `version`
    incremented by 1."

    Design: Corner/entities/system_fields_are_server_minted_and_record_the_acting_user
    """
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell_under_construction(landfill["id"], **RESERVE_CELL)
    package = fixtures.submit_liner_qa_package(landfill["id"], cell["id"])
    assert int(package["version"]) == 1

    data = validate_success(
        api_client.begin_liner_qa_review(package["id"], CQA_ENGINEER), 200
    )

    assert data["reviewed_by_user_id"] == "cqa-engineer-2"
    assert data["status"] == "UNDER_REVIEW"
    assert int(data["version"]) == 2
    assert_common_fields(data, expected_version=2)
    assert data["submitted_by_user_id"] == landfill["id"], "the submitter stamp is untouched"


def test_a_new_cell_carries_no_agency_authorization_stamp():
    """Nobody from the agency has signed the cell off, so the actor field is null.

    PRD: "At creation the cell's `status` is `DESIGN`, its `consumed_airspace_cy` and
    `fill_pct` are both zero, its `authorized_by_agency_user_id` and `final_cover_reference`
    are null, and its `version` is 1."

    Design: Corner/entities/system_fields_are_server_minted_and_record_the_acting_user
    """
    landfill = fixtures.create_landfill()

    data = validate_success(
        api_client.create_cell(
            cell_payload(landfill["id"], **RESERVE_CELL),
            make_site_operator_headers(landfill["id"]),
        ),
        201,
    )

    assert data["authorized_by_agency_user_id"] is None
    assert data["final_cover_reference"] is None
    assert int(data["version"]) == 1


def test_an_undeclared_enum_member_and_an_out_of_band_number_are_both_malformed():
    """MEMBRANE_ONLY is not a liner system and 1.50 tons per cubic yard is off the band.

    PRD: "**Request body shape** — on every write endpoint. Every required input field must
    be present and non-null, every field must carry its declared JSON type, every enumerated
    field must carry a declared member, every ISO-8601 timestamp must parse, and every
    quantity that must be positive (tonnages, gallons, areas, counts, unit costs) must be
    greater than zero."

    Design: Corner/entities/invalid_enums_ranges_and_inverted_intervals_are_rejected
    """
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell_under_construction(landfill["id"], **RESERVE_CELL)

    bad_enum = api_client.create_cell(
        cell_payload(
            landfill["id"],
            cell_code="C-4",
            design_airspace_cy=200,
            design_area_sf=45001,
            liner_type="MEMBRANE_ONLY",
        ),
        make_site_operator_headers(landfill["id"]),
    )
    bad_range = api_client.create_landfill(
        landfill_payload(
            name="Overdense MSW",
            permit_number="MSW-5000",
            planned_density_tons_per_cy=1.50,
        ),
        PLATFORM_ADMIN,
    )

    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(bad_range, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _cells, cell_meta = validate_paginated(api_client.list_cells(PLATFORM_ADMIN))
    assert cell_meta["total_count"] == 1, "the malformed cell was not stored"
    _sites, site_meta = validate_paginated(api_client.list_landfills(PLATFORM_ADMIN))
    assert site_meta["total_count"] == 1, "the out-of-band landfill was not stored"
    assert get_success_data(api_client.get_cell(cell["id"], AGENCY))["status"] == (
        "UNDER_CONSTRUCTION"
    )


def test_a_cross_field_count_and_an_inverted_interval_are_both_malformed():
    """21 passing tests out of 20, and a window that closes before it opens.

    PRD: "In addition, `coverage_period_start` must be at or before `coverage_period_end`,
    `window_start` must be strictly before `window_end`, `effective_from` must be strictly
    before `expires_on`, `construction_start_date` must be at or before
    `construction_end_date`, and `passing_test_count` must not exceed
    `destructive_test_count`."

    Design: Corner/entities/invalid_enums_ranges_and_inverted_intervals_are_rejected
    """
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell_under_construction(landfill["id"], **RESERVE_CELL)

    too_many_passes = api_client.create_liner_qa_package(
        liner_qa_package_payload(cell["id"], destructive_test_count=20, passing_test_count=21),
        make_site_operator_headers(landfill["id"]),
    )
    inverted_window = api_client.create_special_waste_approval(
        special_waste_approval_payload(
            landfill["id"],
            generator_name="Ridgeview Plating Co",
            waste_code="IS-4410",
            approved_tons_cap=500,
            effective_from="2026-12-31T00:00:00Z",
            expires_on="2026-01-01T00:00:00Z",
        ),
        ENV_MANAGER,
    )

    validate_error(too_many_passes, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(inverted_window, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    _packages, package_meta = validate_paginated(
        api_client.list_liner_qa_packages(PLATFORM_ADMIN)
    )
    assert package_meta["total_count"] == 0
    _approvals, approval_meta = validate_paginated(
        api_client.list_special_waste_approvals(PLATFORM_ADMIN)
    )
    assert approval_meta["total_count"] == 0
    assert get_success_data(api_client.get_cell(cell["id"], AGENCY))["status"] == (
        "UNDER_CONSTRUCTION"
    )


def test_three_children_aimed_at_phantom_parents_each_report_their_own_parent():
    """A load, a tanker haul and a gas well each name the parent that could not be found.

    PRD: "**Body foreign keys resolve** — on every write endpoint carrying a foreign-key
    field in its body, validated in the order the fields are declared for that endpoint. Each
    miss returns the same per-resource not-found error as above, with HTTP 404."

    Design: Corner/entities/child_creation_requires_its_declared_parent_row
    """
    landfill = fixtures.create_landfill()

    orphan_load = api_client.create_waste_load(
        waste_load_payload(UNKNOWN_UUID, hauler_ref="H-1", manifest_tons=30.00),
        make_scale_operator_headers(landfill["id"]),
    )
    orphan_haul = api_client.create_leachate_shipment(
        leachate_shipment_payload(
            UNKNOWN_UUID,
            gallons=4000,
            window_start="2026-08-01T08:00:00Z",
            window_end="2026-08-01T10:00:00Z",
        ),
        make_site_operator_headers(landfill["id"]),
    )
    orphan_well = api_client.create_gas_well(gas_well_payload(UNKNOWN_UUID), ENV_MANAGER)

    validate_error(orphan_load, ApiErrorId.ERR_OPERATING_DAY_NOT_FOUND.value, 404)
    validate_error(orphan_haul, ApiErrorId.ERR_TREATMENT_AGREEMENT_NOT_FOUND.value, 404)
    validate_error(orphan_well, ApiErrorId.ERR_CELL_NOT_FOUND.value, 404)
    for lister in (
        api_client.list_waste_loads,
        api_client.list_leachate_shipments,
        api_client.list_gas_wells,
    ):
        _rows, meta = validate_paginated(lister(PLATFORM_ADMIN))
        assert meta["total_count"] == 0, "no orphan child row was stored"
