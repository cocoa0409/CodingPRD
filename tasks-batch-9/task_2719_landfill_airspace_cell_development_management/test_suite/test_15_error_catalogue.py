"""Breadth over the error catalogue: every declared id reachable on its own request."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_error_envelope_only
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.factories import (
    cell_payload,
    closure_cost_estimate_payload,
    gas_well_payload,
    landfill_payload,
    operating_day_payload,
    waste_load_payload,
)
from test_helpers.test_users import (
    TEST_USERS,
    headers_without_auth,
    headers_without_role,
    headers_without_user_id,
    make_scale_operator_headers,
    make_site_operator_headers,
)

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CQA_ENGINEER = TEST_USERS["cqa_engineer_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]
FINANCE_FILER = TEST_USERS["finance_filer_headers"]


def _every_by_id_read(landfill_id):
    """One by-id read per resource type, each addressed to an id nobody ever minted."""
    site = make_site_operator_headers(landfill_id)
    scale = make_scale_operator_headers(landfill_id)
    return [
        (api_client.get_landfill(UNKNOWN_UUID, PLATFORM_ADMIN),
         ApiErrorId.ERR_LANDFILL_NOT_FOUND.value),
        (api_client.get_cell(UNKNOWN_UUID, site),
         ApiErrorId.ERR_CELL_NOT_FOUND.value),
        (api_client.get_liner_qa_package(UNKNOWN_UUID, CQA_ENGINEER),
         ApiErrorId.ERR_LINER_QA_PACKAGE_NOT_FOUND.value),
        (api_client.get_aerial_survey(UNKNOWN_UUID, SURVEYOR),
         ApiErrorId.ERR_AERIAL_SURVEY_NOT_FOUND.value),
        (api_client.get_operating_day(UNKNOWN_UUID, site),
         ApiErrorId.ERR_OPERATING_DAY_NOT_FOUND.value),
        (api_client.get_waste_load(UNKNOWN_UUID, scale),
         ApiErrorId.ERR_WASTE_LOAD_NOT_FOUND.value),
        (api_client.get_special_waste_approval(UNKNOWN_UUID, ENV_MANAGER),
         ApiErrorId.ERR_SPECIAL_WASTE_APPROVAL_NOT_FOUND.value),
        (api_client.get_treatment_agreement(UNKNOWN_UUID, ENV_MANAGER),
         ApiErrorId.ERR_TREATMENT_AGREEMENT_NOT_FOUND.value),
        (api_client.get_leachate_shipment(UNKNOWN_UUID, site),
         ApiErrorId.ERR_LEACHATE_SHIPMENT_NOT_FOUND.value),
        (api_client.get_gas_well(UNKNOWN_UUID, ENV_MANAGER),
         ApiErrorId.ERR_GAS_WELL_NOT_FOUND.value),
        (api_client.get_surface_emission_scan(UNKNOWN_UUID, ENV_MANAGER),
         ApiErrorId.ERR_SURFACE_EMISSION_SCAN_NOT_FOUND.value),
        (api_client.get_closure_cost_estimate(UNKNOWN_UUID, FINANCE_FILER),
         ApiErrorId.ERR_CLOSURE_COST_ESTIMATE_NOT_FOUND.value),
        (api_client.get_host_community_agreement(UNKNOWN_UUID, FINANCE_FILER),
         ApiErrorId.ERR_HOST_COMMUNITY_AGREEMENT_NOT_FOUND.value),
    ]


def test_each_resource_type_answers_a_missing_id_with_its_own_error():
    """Thirteen by-id reads, thirteen distinct 404 ids — no shared not-found id.

    PRD: "Each miss returns that resource type's own not-found error:
    `ERR_LANDFILL_NOT_FOUND`, `ERR_CELL_NOT_FOUND`, `ERR_LINER_QA_PACKAGE_NOT_FOUND`,
    `ERR_AERIAL_SURVEY_NOT_FOUND`, `ERR_OPERATING_DAY_NOT_FOUND`,
    `ERR_WASTE_LOAD_NOT_FOUND`, `ERR_SPECIAL_WASTE_APPROVAL_NOT_FOUND`,
    `ERR_TREATMENT_AGREEMENT_NOT_FOUND`, `ERR_LEACHATE_SHIPMENT_NOT_FOUND`,
    `ERR_GAS_WELL_NOT_FOUND`, `ERR_SURFACE_EMISSION_SCAN_NOT_FOUND`,
    `ERR_CLOSURE_COST_ESTIMATE_NOT_FOUND` or `ERR_HOST_COMMUNITY_AGREEMENT_NOT_FOUND`, each
    with HTTP 404."

    Design: Corner/errors/every_entity_type_reports_its_own_not_found_error_id
    """
    landfill = fixtures.create_landfill()

    reads = _every_by_id_read(landfill["id"])

    assert len(reads) == 13, "one by-id read per resource type in the PRD"
    reported = []
    for response, expected_error_id in reads:
        validate_error(response, expected_error_id, 404)
        reported.append(response.json()["data"]["error_id"])
    assert len(set(reported)) == 13, f"the thirteen ids must all differ, got {reported}"


def test_a_missing_id_answers_with_an_error_body_and_no_partial_resource():
    """The 404 body carries the two error fields and nothing that looks like a row.

    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/errors/every_entity_type_reports_its_own_not_found_error_id
    """
    landfill = fixtures.create_landfill()

    reads = _every_by_id_read(landfill["id"])

    for response, _expected_error_id in reads:
        assert_error_envelope_only(response.json())
    still_there = fixtures.read_landfill(landfill["id"])
    assert still_there["id"] == landfill["id"], "the real row was never in question"


BIG_CELL = {
    "cell_code": "C-1",
    "design_airspace_cy": 1000000,
    "design_area_sf": 120001,
    "liner_type": "DOUBLE_COMPOSITE",
}
SMALL_CELL = {
    "cell_code": "C-2",
    "design_airspace_cy": 200,
    "design_area_sf": 45001,
    "liner_type": "DOUBLE_COMPOSITE",
    "construction_end_date": "2026-07-20T00:00:00Z",
}


def _site_holding_every_scoped_key():
    """One site, two cells, a well on the first cell and a 2026 estimate on file."""
    landfill = fixtures.create_landfill()
    first = fixtures.create_cell(landfill["id"], **BIG_CELL)
    second = fixtures.create_cell(landfill["id"], **SMALL_CELL)
    well = fixtures.drill_gas_well(first["id"], well_code="W-1", depth_ft=85)
    estimate = fixtures.file_closure_estimate(landfill["id"], estimate_year=2026)
    return {
        "landfill": landfill,
        "first": first,
        "second": second,
        "well": well,
        "estimate": estimate,
        "site_headers": make_site_operator_headers(landfill["id"]),
    }


def test_the_global_and_the_per_landfill_code_scopes_report_their_own_ids():
    """A permit number collides system-wide; a cell code collides only inside its site.

    PRD: "A `permit_number` is unique across all landfills, else
    `ERR_DUPLICATE_PERMIT_NUMBER`; a `cell_code` is unique within its landfill, else
    `ERR_DUPLICATE_CELL_CODE`; an `operating_date` is unique within its landfill, else
    `ERR_DUPLICATE_OPERATING_DATE`; a `well_code` is unique across every cell of one landfill,
    else `ERR_DUPLICATE_WELL_CODE`; an `estimate_year` is unique within its landfill, else
    `ERR_DUPLICATE_ESTIMATE_YEAR`."

    Design: Corner/errors/duplicate_scoped_keys_are_rejected_with_their_own_error_ids
    """
    world = _site_holding_every_scoped_key()

    permit_clash = api_client.create_landfill(
        landfill_payload(
            name="Copycat MSW",
            permit_number="MSW-4417",
            permitted_total_airspace_cy=100000,
            design_footprint_sf=50000,
            planned_density_tons_per_cy=0.80,
            annual_tonnage_forecast=10000,
        ),
        PLATFORM_ADMIN,
    )
    code_clash = api_client.create_cell(
        cell_payload(
            world["landfill"]["id"],
            cell_code="C-1",
            design_airspace_cy=300,
            design_area_sf=45001,
            liner_type="GCL_ONLY",
        ),
        world["site_headers"],
    )

    validate_error(permit_clash, ApiErrorId.ERR_DUPLICATE_PERMIT_NUMBER.value, 409)
    validate_error(code_clash, ApiErrorId.ERR_DUPLICATE_CELL_CODE.value, 409)
    _rows, meta = validate_paginated(api_client.list_landfills(PLATFORM_ADMIN))
    assert meta["total_count"] == 1, "the refused registration stored nothing"
    _cells, cell_meta = validate_paginated(
        api_client.list_cells(AGENCY, {"landfill_id": world["landfill"]["id"]})
    )
    assert cell_meta["total_count"] == 2, "only the two accepted cells exist"


def test_a_well_code_collides_across_two_cells_of_the_same_landfill():
    """The second cell is a different parent, and the code still belongs to the site.

    PRD: "An `EnvironmentalManager` records a new extraction well by naming the `cell_id` it
    is drilled into, its `well_code` wellfield designation (1 to 20 characters, unique across
    every cell of the owning landfill — a collision anywhere on the site is refused with
    `ERR_DUPLICATE_WELL_CODE`), and its drilled `depth_ft` in feet, which must be greater
    than zero."

    Design: Corner/errors/duplicate_scoped_keys_are_rejected_with_their_own_error_ids
    """
    world = _site_holding_every_scoped_key()

    response = api_client.create_gas_well(
        gas_well_payload(world["second"]["id"], well_code="W-1", depth_ft=70), ENV_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_WELL_CODE.value, 409)
    _rows, meta = validate_paginated(
        api_client.list_gas_wells(ENV_MANAGER, {"cell_id": world["second"]["id"]})
    )
    assert meta["total_count"] == 0, "the second cell has no wellfield of its own"
    _kept, kept_meta = validate_paginated(
        api_client.list_gas_wells(ENV_MANAGER, {"cell_id": world["first"]["id"]})
    )
    assert kept_meta["total_count"] == 1


def test_a_second_estimate_for_a_year_already_on_file_is_rejected():
    """The request carries the current landfill version, so it reaches the uniqueness rung.

    PRD: "A `FinanceOfficer` files the annual update naming the `landfill_id`, the
    `estimate_year` of the update (between 2000 and 2100, and unique per landfill — a second
    update for the same year is refused with `ERR_DUPLICATE_ESTIMATE_YEAR`), the
    `closure_unit_cost_per_sf` for final-cover construction in dollars per square foot of
    lined area, the `post_closure_annual_cost` for the first year of post-closure care in
    dollars, the `inflation_pct` applied annually to post-closure care as a decimal fraction
    between 0 and 0.20 inclusive, and `expected_landfill_version` for the
    optimistic-concurrency guard of §2.8."

    Design: Corner/errors/duplicate_scoped_keys_are_rejected_with_their_own_error_ids
    """
    world = _site_holding_every_scoped_key()
    current_version = fixtures.landfill_version(world["landfill"]["id"])

    response = api_client.create_closure_cost_estimate(
        closure_cost_estimate_payload(
            world["landfill"]["id"],
            current_version,
            estimate_year=2026,
            closure_unit_cost_per_sf=1.900,
            post_closure_annual_cost=96000.00,
        ),
        FINANCE_FILER,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_ESTIMATE_YEAR.value, 409)
    _rows, meta = validate_paginated(
        api_client.list_closure_cost_estimates(FINANCE_FILER, {"estimate_year": 2026})
    )
    assert meta["total_count"] == 1, "the year still holds exactly one filing"


FEE_SCHEDULE_A = {
    "community_name": "Ridgeview Township",
    "posted_tipping_fee_per_ton": 42.50,
    "host_fee_per_ton": 3.75,
    "tier1_monthly_tons": 100,
    "royalty_tier1_pct": 0.04,
    "royalty_tier2_pct": 0.07,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2030-12-31T00:00:00Z",
}
FEE_SCHEDULE_B = dict(
    FEE_SCHEDULE_A,
    posted_tipping_fee_per_ton=44.00,
    host_fee_per_ton=4.00,
    tier1_monthly_tons=120,
    royalty_tier1_pct=0.05,
    royalty_tier2_pct=0.08,
    effective_from="2027-01-01T00:00:00Z",
    expires_on="2031-12-31T00:00:00Z",
)
FEE_SCHEDULE_C = dict(
    FEE_SCHEDULE_A,
    posted_tipping_fee_per_ton=45.00,
    host_fee_per_ton=4.25,
    tier1_monthly_tons=130,
    royalty_tier1_pct=0.05,
    royalty_tier2_pct=0.09,
    effective_from="2028-01-01T00:00:00Z",
    expires_on="2032-12-31T00:00:00Z",
)
FIRST_REOPENER = "Annual fee reopener"


def _three_draft_agreements():
    """One site carrying three unexecuted host agreements."""
    landfill = fixtures.create_landfill()
    drafts = [
        fixtures.draft_host_agreement(landfill["id"], **schedule)
        for schedule in (FEE_SCHEDULE_A, FEE_SCHEDULE_B, FEE_SCHEDULE_C)
    ]
    for draft in drafts:
        assert draft["status"] == "DRAFT"
    return landfill, drafts


def _second_agreement_live():
    """The first agreement has been superseded; the second one is the live schedule."""
    landfill, drafts = _three_draft_agreements()
    fixtures.execute_host_agreement(drafts[0]["id"], landfill["id"])
    live = fixtures.execute_host_agreement(drafts[1]["id"], landfill["id"])
    assert live["status"] == "EXECUTED"
    return landfill, drafts


def test_executing_a_second_agreement_supersedes_the_merely_executed_first():
    """Nothing is refused here: an EXECUTED predecessor is terminated, not a blocker.

    PRD: "An agreement that is merely `EXECUTED` does **not** block: on success every other
    agreement of the landfill in `EXECUTED` is moved to `TERMINATED` with its
    `termination_reason` recorded as the phrase `SUPERSEDED_BY_NEW_AGREEMENT` and its
    `version` incremented by 1."

    Design: Corner/errors/host_agreement_amendment_conflicts_are_rejected
    """
    landfill, drafts = _three_draft_agreements()
    first = fixtures.execute_host_agreement(drafts[0]["id"], landfill["id"])
    assert first["status"] == "EXECUTED"

    second = fixtures.execute_host_agreement(drafts[1]["id"], landfill["id"])

    assert second["status"] == "EXECUTED"
    superseded = get_success_data(
        api_client.get_host_community_agreement(drafts[0]["id"], FINANCE_FILER)
    )
    assert superseded["status"] == "TERMINATED"
    assert superseded["termination_reason"] == "SUPERSEDED_BY_NEW_AGREEMENT"
    assert int(superseded["version"]) == int(first["version"]) + 1
    still_draft = get_success_data(
        api_client.get_host_community_agreement(drafts[2]["id"], FINANCE_FILER)
    )
    assert still_draft["status"] == "DRAFT"


def test_a_second_amendment_on_an_amending_agreement_is_rejected():
    """The re-negotiation already open is not replaced by the second request.

    PRD: "Addressing an amendment-opening request to an agreement that is *already*
    `UNDER_AMENDMENT` is reported specifically as `ERR_AMENDMENT_IN_PROGRESS` rather than as a
    generic state-transition refusal."

    Design: Corner/errors/host_agreement_amendment_conflicts_are_rejected
    """
    _landfill, drafts = _second_agreement_live()
    amending = validate_success(
        api_client.open_host_agreement_amendment(
            drafts[1]["id"], {"amendment_reason": FIRST_REOPENER}, FINANCE_FILER
        ),
        200,
    )
    assert amending["status"] == "UNDER_AMENDMENT"
    assert amending["amendment_reason"] == FIRST_REOPENER

    response = api_client.open_host_agreement_amendment(
        drafts[1]["id"], {"amendment_reason": "Second reopener"}, FINANCE_FILER
    )

    validate_error(response, ApiErrorId.ERR_AMENDMENT_IN_PROGRESS.value, 409)
    unchanged = get_success_data(
        api_client.get_host_community_agreement(drafts[1]["id"], FINANCE_FILER)
    )
    assert unchanged["status"] == "UNDER_AMENDMENT"
    assert unchanged["amendment_reason"] == FIRST_REOPENER, "the first reason still stands"
    assert int(unchanged["amendment_round"]) == 0, "no round closed on a refused request"
    assert int(unchanged["version"]) == int(amending["version"])


def test_a_draft_cannot_be_executed_while_the_live_agreement_is_amending():
    """The open re-negotiation blocks a fresh execution even from a clean DRAFT.

    PRD: "Two further conditions apply: the agreement must be in `DRAFT`, and no agreement of
    the same landfill may currently be sitting in `UNDER_AMENDMENT` — a live re-negotiation
    blocks a fresh execution, and the attempt is refused with
    `ERR_HOST_AGREEMENT_ALREADY_LIVE`."

    Design: Corner/errors/host_agreement_amendment_conflicts_are_rejected
    """
    landfill, drafts = _second_agreement_live()
    validate_success(
        api_client.open_host_agreement_amendment(
            drafts[1]["id"], {"amendment_reason": FIRST_REOPENER}, FINANCE_FILER
        ),
        200,
    )
    version_before = fixtures.landfill_version(landfill["id"])

    response = api_client.execute_host_community_agreement(
        drafts[2]["id"], {"expected_landfill_version": version_before}, FINANCE_FILER
    )

    validate_error(response, ApiErrorId.ERR_HOST_AGREEMENT_ALREADY_LIVE.value, 409)
    still_draft = get_success_data(
        api_client.get_host_community_agreement(drafts[2]["id"], FINANCE_FILER)
    )
    assert still_draft["status"] == "DRAFT"
    assert int(still_draft["version"]) == 1
    assert fixtures.landfill_version(landfill["id"]) == version_before


HEADERLESS_SITE = {
    "name": "Headerless MSW",
    "permit_number": "MSW-0000",
    "permitted_total_airspace_cy": 100,
    "design_footprint_sf": 100,
    "planned_density_tons_per_cy": 0.90,
    "annual_tonnage_forecast": 100,
}


def test_requests_missing_either_auth_header_are_unauthenticated():
    """Three shapes of absence — both, the id alone, the role alone — all answer 401.

    PRD: "If either header is absent, or if `X-User-Role` does not spell one of the eight
    roles below exactly, the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/requests_with_missing_auth_headers_are_unauthenticated
    """
    landfill = fixtures.create_landfill()

    both_absent = api_client.get_landfill(landfill["id"], headers_without_auth())
    id_absent = api_client.get_cell(UNKNOWN_UUID, headers_without_user_id("SiteOperator"))
    role_absent = api_client.create_landfill(
        landfill_payload(**HEADERLESS_SITE), headers_without_role("platform-admin-1")
    )

    validate_error(both_absent, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    validate_error(id_absent, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    validate_error(role_absent, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    _rows, meta = validate_paginated(api_client.list_landfills(PLATFORM_ADMIN))
    assert meta["total_count"] == 1, "the headerless registration created nothing"


def test_the_identical_three_requests_carrying_headers_are_answered_on_their_merits():
    """With headers restored the same three calls give 200, a resource 404 and a 201.

    PRD: "These two checks run before anything else in the system, ahead of body parsing and
    ahead of any lookup."

    Design: Corner/errors/requests_with_missing_auth_headers_are_unauthenticated
    """
    landfill = fixtures.create_landfill()

    read = api_client.get_landfill(landfill["id"], PLATFORM_ADMIN)
    missing_cell = api_client.get_cell(
        UNKNOWN_UUID, make_site_operator_headers(landfill["id"])
    )
    created = api_client.create_landfill(landfill_payload(**HEADERLESS_SITE), PLATFORM_ADMIN)

    assert validate_success(read, 200)["id"] == landfill["id"]
    validate_error(missing_cell, ApiErrorId.ERR_CELL_NOT_FOUND.value, 404)
    second_site = validate_success(created, 201)
    assert second_site["permit_number"] == "MSW-0000"
    _rows, meta = validate_paginated(api_client.list_landfills(PLATFORM_ADMIN))
    assert meta["total_count"] == 2


DAY_SHAPE = {
    "operating_date": "2026-08-01T00:00:00Z",
    "working_face_area_sf": 5000,
    "cover_material_type": "ALTERNATIVE_TARP",
}


def _open_day_capped_at_three_loads():
    """An activated site limited to three loads a day, with a CONNECTED well on the face.

    The day already carries one cleared and weighed truck plus a second one that has
    not been screened at all.
    """
    site = fixtures.setup_active_site(
        landfill_overrides={"daily_load_limit": 3},
        cell_overrides=dict(BIG_CELL),
        agreement_overrides=dict(FEE_SCHEDULE_A),
    )
    landfill_id = site["landfill"]["id"]
    site["well"] = fixtures.setup_connected_well(
        site["cell"]["id"], well_code="W-1", depth_ft=85
    )
    assert site["well"]["status"] == "CONNECTED"
    site["day"] = fixtures.open_operating_day(landfill_id, site["cell"]["id"], **DAY_SHAPE)
    site["first"] = fixtures.place_certified_load(
        landfill_id, site["day"]["id"], 40.00, hauler_ref="H-1", manifest_tons=40.00
    )
    site["second"] = fixtures.receive_load(
        landfill_id, site["day"]["id"], hauler_ref="H-2", manifest_tons=30.00
    )
    assert site["second"]["screening_status"] == "PENDING"
    return site


def test_a_load_still_in_screening_blocks_the_day_close():
    """One unscreened truck stops the close even though the other one is fully weighed.

    PRD: "No load of the day may still be sitting in screening `PENDING` or `FLAGGED`, else
    `ERR_PENDING_SCREENING_PRESENT`."

    Design: Corner/errors/daily_operations_errors_are_each_reachable_on_one_open_day
    """
    site = _open_day_capped_at_three_loads()

    response = api_client.close_operating_day(site["day"]["id"], site["site_headers"])

    validate_error(response, ApiErrorId.ERR_PENDING_SCREENING_PRESENT.value, 409)
    day = get_success_data(api_client.get_operating_day(site["day"]["id"], site["site_headers"]))
    assert day["status"] == "OPEN"
    assert_amount(day["tons_placed"], 0, "tons placed")


def test_a_cleared_load_lacking_a_certified_weight_still_blocks_the_day_close():
    """Screening is finished on every truck and the close is still refused.

    PRD: "Every load of the day that reached `CLEARED` must carry a non-null
    `certified_net_tons`, else `ERR_UNCERTIFIED_LOADS_PRESENT`."

    Design: Corner/errors/daily_operations_errors_are_each_reachable_on_one_open_day
    """
    site = _open_day_capped_at_three_loads()
    cleared = fixtures.clear_screening(site["landfill"]["id"], site["second"]["id"])
    assert cleared["screening_status"] == "CLEARED"
    assert cleared["certified_net_tons"] is None

    response = api_client.close_operating_day(site["day"]["id"], site["site_headers"])

    validate_error(response, ApiErrorId.ERR_UNCERTIFIED_LOADS_PRESENT.value, 409)
    day = get_success_data(api_client.get_operating_day(site["day"]["id"], site["site_headers"]))
    assert day["status"] == "OPEN"
    assert_amount(day["tons_placed"], 0, "tons placed")


def test_a_third_truck_lands_exactly_on_the_daily_load_limit():
    """Three non-rejected loads is the limit itself, and the limit is inclusive.

    PRD: "Exact equality with the limit is allowed; one more than the limit is refused with
    `ERR_DAILY_LOAD_LIMIT_EXCEEDED`."

    Design: Corner/errors/daily_operations_errors_are_each_reachable_on_one_open_day
    """
    site = _open_day_capped_at_three_loads()

    third = validate_success(
        api_client.create_waste_load(
            waste_load_payload(
                site["day"]["id"], hauler_ref="H-3", waste_stream="CD", manifest_tons=10.00
            ),
            site["scale_headers"],
        ),
        201,
    )

    assert third["screening_status"] == "PENDING"
    _rows, meta = validate_paginated(
        api_client.list_operating_day_waste_loads(site["day"]["id"], site["scale_headers"])
    )
    assert meta["total_count"] == 3


def test_a_fourth_truck_past_the_daily_load_limit_is_turned_away():
    """The count is over the ceiling and the row is never written.

    PRD: "There is also a throughput ceiling: counting the new truck, the number of loads
    attached to that operating day whose screening has not been rejected may not exceed the
    site's `daily_load_limit`."

    Design: Corner/errors/daily_operations_errors_are_each_reachable_on_one_open_day
    """
    site = _open_day_capped_at_three_loads()
    fixtures.receive_load(
        site["landfill"]["id"],
        site["day"]["id"],
        hauler_ref="H-3",
        waste_stream="CD",
        manifest_tons=10.00,
    )

    response = api_client.create_waste_load(
        waste_load_payload(site["day"]["id"], hauler_ref="H-4", manifest_tons=12.00),
        site["scale_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DAILY_LOAD_LIMIT_EXCEEDED.value, 409)
    _rows, meta = validate_paginated(
        api_client.list_operating_day_waste_loads(site["day"]["id"], site["scale_headers"])
    )
    assert meta["total_count"] == 3, "the fourth truck left no row behind"


def test_a_second_operating_day_on_the_same_date_is_rejected():
    """A different working face and a different cover do not make it a different date.

    PRD: "A `permit_number` is unique across all landfills, else
    `ERR_DUPLICATE_PERMIT_NUMBER`; a `cell_code` is unique within its landfill, else
    `ERR_DUPLICATE_CELL_CODE`; an `operating_date` is unique within its landfill, else
    `ERR_DUPLICATE_OPERATING_DATE`; a `well_code` is unique across every cell of one landfill,
    else `ERR_DUPLICATE_WELL_CODE`; an `estimate_year` is unique within its landfill, else
    `ERR_DUPLICATE_ESTIMATE_YEAR`."

    Design: Corner/errors/daily_operations_errors_are_each_reachable_on_one_open_day
    """
    site = _open_day_capped_at_three_loads()

    response = api_client.create_operating_day(
        operating_day_payload(
            site["landfill"]["id"],
            site["cell"]["id"],
            operating_date="2026-08-01T00:00:00Z",
            working_face_area_sf=6000,
            cover_material_type="SOIL_6IN",
        ),
        site["site_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_OPERATING_DATE.value, 409)
    _rows, meta = validate_paginated(
        api_client.list_operating_days(
            site["site_headers"], {"landfill_id": site["landfill"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_an_oxygen_reading_at_the_critical_constant_stores_nothing():
    """Twelve percent is itself critical, so the visit is not recorded as a tune at all.

    PRD: "The request is refused with `ERR_WELL_OXYGEN_CRITICAL`, the well's state does not
    change, and no reading is stored; the correct response is to valve the well out instead."

    Design: Corner/errors/daily_operations_errors_are_each_reachable_on_one_open_day
    """
    site = _open_day_capped_at_three_loads()

    response = api_client.tune_gas_well(
        site["well"]["id"],
        {"last_vacuum_in_h2o": 15.0, "last_methane_pct": 52.0, "last_oxygen_pct": 12.0},
        ENV_MANAGER,
    )

    validate_error(response, ApiErrorId.ERR_WELL_OXYGEN_CRITICAL.value, 422)
    well = get_success_data(api_client.get_gas_well(site["well"]["id"], ENV_MANAGER))
    assert well["status"] == "CONNECTED"
    assert well["last_oxygen_pct"] is None
    assert well["last_methane_pct"] is None
    assert well["last_vacuum_in_h2o"] is None
    assert well["last_tuned_at"] is None
    assert int(well["version"]) == int(site["well"]["version"])


def test_an_oxygen_reading_just_below_the_constant_is_tuned_out_of_specification():
    """Eleven point nine records, and thin methane drives the whole site into correction.

    PRD: "On the out-of-specification branch, the site's `gas_collection_status` is set to
    `CORRECTIVE_ACTION` and the landfill's `version` is incremented by 1 — which, per §3.4,
    immediately blocks authorization and activation of any cell on that site."

    Design: Corner/errors/daily_operations_errors_are_each_reachable_on_one_open_day
    """
    site = _open_day_capped_at_three_loads()

    tuned = fixtures.tune_gas_well(
        site["well"]["id"], last_vacuum_in_h2o=8.0, last_methane_pct=40.0, last_oxygen_pct=11.9
    )

    assert tuned["status"] == "TUNING_REQUIRED"
    assert tuned["last_tuned_at"] is not None
    posture = fixtures.read_landfill(site["landfill"]["id"])
    assert posture["gas_collection_status"] == "CORRECTIVE_ACTION"


def _day_ready_to_close(permit_number, permitted_total_airspace_cy):
    """One 166.60-ton truck certified on an open day; closing it would burn 196.00 cy."""
    site = fixtures.setup_active_site(
        landfill_overrides={
            "permit_number": permit_number,
            "permitted_total_airspace_cy": permitted_total_airspace_cy,
        },
        cell_overrides=dict(SMALL_CELL),
        agreement_overrides=dict(FEE_SCHEDULE_A),
    )
    landfill_id = site["landfill"]["id"]
    site["day"] = fixtures.open_operating_day(landfill_id, site["cell"]["id"], **DAY_SHAPE)
    site["load"] = fixtures.place_certified_load(
        landfill_id, site["day"]["id"], 166.60, hauler_ref="H-1", manifest_tons=166.60
    )
    assert_amount(site["load"]["gate_charge_amount"], 7705.25, "gate charge")
    assert site["load"]["billing_status"] == "PROVISIONAL"
    return site


def test_a_close_that_would_overrun_the_permit_is_refused_and_cascades_nothing():
    """The consumption is computed, compared and then thrown away entirely.

    PRD: "And the close may not drive the site's `consumed_airspace_cy` above its
    `permitted_total_airspace_cy` once the day's computed consumption is added; exact equality
    with the permit is allowed, and an overrun is refused with
    `ERR_PERMITTED_AIRSPACE_EXCEEDED` no matter how fully the loads were paid for."

    Design: Corner/errors/closing_a_day_past_the_permit_ceiling_is_rejected_without_cascade
    """
    site = _day_ready_to_close("MSW-0190", 190)

    response = api_client.close_operating_day(site["day"]["id"], site["site_headers"])

    validate_error(response, ApiErrorId.ERR_PERMITTED_AIRSPACE_EXCEEDED.value, 422)
    cell = get_success_data(api_client.get_cell(site["cell"]["id"], site["site_headers"]))
    assert cell["status"] == "ACTIVE"
    assert_amount(cell["consumed_airspace_cy"], 0, "cell consumed airspace")
    assert_amount(cell["fill_pct"], 0, "cell fill")
    landfill = fixtures.read_landfill(site["landfill"]["id"])
    assert_amount(landfill["consumed_airspace_cy"], 0, "site consumed airspace")
    assert landfill["operating_status"] == "OPEN"
    load = get_success_data(api_client.get_waste_load(site["load"]["id"], site["scale_headers"]))
    assert load["billing_status"] == "PROVISIONAL"
    assert load["final_charge_amount"] is None
    assert_amount(load["gate_charge_amount"], 7705.25, "gate charge after the refusal")
    day = get_success_data(api_client.get_operating_day(site["day"]["id"], site["site_headers"]))
    assert day["status"] == "OPEN"
    assert_amount(day["tons_placed"], 0, "tons placed")
    assert_amount(day["airspace_consumed_cy"], 0, "airspace consumed")


def test_the_same_day_closes_when_the_permit_exactly_equals_the_consumption():
    """196.00 against a 196 cy permit is equality, and equality is allowed.

    PRD: "`airspace_consumed_cy` is then the day's `tons_placed` divided by that
    **already-rounded** four-decimal density, rounded to 2 decimal places — except that when
    `tons_placed` is zero the consumption is exactly 0.00 and no division is attempted."

    Design: Corner/errors/closing_a_day_past_the_permit_ceiling_is_rejected_without_cascade
    """
    site = _day_ready_to_close("MSW-0196", 196)

    closed = fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    assert closed["status"] == "CLOSED"
    assert_amount(closed["tons_placed"], 166.60, "tons placed")
    assert_amount(closed["airspace_consumed_cy"], 196.00, "airspace consumed")
    landfill = fixtures.read_landfill(site["landfill"]["id"])
    assert_amount(landfill["consumed_airspace_cy"], 196.00, "site consumed airspace")
    cell = get_success_data(api_client.get_cell(site["cell"]["id"], site["site_headers"]))
    assert cell["status"] == "FULL"
    assert_amount(cell["fill_pct"], 98.00, "cell fill")


def _full_cell_with_one_drilled_well():
    """A cell driven to 98 percent with a single well still sitting in DRILLED."""
    site = fixtures.setup_active_site(
        cell_overrides=dict(SMALL_CELL), agreement_overrides=dict(FEE_SCHEDULE_A)
    )
    landfill_id = site["landfill"]["id"]
    site["well"] = fixtures.drill_gas_well(
        site["cell"]["id"], well_code="W-1", depth_ft=60
    )
    assert site["well"]["status"] == "DRILLED"
    site["day"] = fixtures.open_operating_day(landfill_id, site["cell"]["id"], **DAY_SHAPE)
    fixtures.place_certified_load(
        landfill_id, site["day"]["id"], 166.60, hauler_ref="H-1", manifest_tons=166.60
    )
    closed = fixtures.close_operating_day(landfill_id, site["day"]["id"])
    assert_amount(closed["airspace_consumed_cy"], 196.00, "airspace consumed")
    site["cell"] = get_success_data(
        api_client.get_cell(site["cell"]["id"], site["site_headers"])
    )
    assert site["cell"]["status"] == "FULL"
    assert_amount(site["cell"]["fill_pct"], 98.00, "cell fill")
    return site


def test_a_full_cell_cannot_be_capped_while_a_well_is_still_only_drilled():
    """The waste is in and the airspace is spent; the collection system is not finished.

    PRD: "The cell must be in `FULL`, and every gas well drilled into it must already be
    either `ONLINE` or `ABANDONED`; a well still sitting in `DRILLED`, `CONNECTED` or
    `TUNING_REQUIRED` means the collection system is unfinished and the closure is refused
    with `ERR_CELL_HAS_UNFINISHED_WELLS`."

    Design: Corner/errors/closing_a_cell_with_unfinished_wells_is_rejected_until_each_well_settles
    """
    site = _full_cell_with_one_drilled_well()

    response = api_client.close_cell(
        site["cell"]["id"], {"final_cover_reference": "FC-2026-01"}, site["site_headers"]
    )

    validate_error(response, ApiErrorId.ERR_CELL_HAS_UNFINISHED_WELLS.value, 409)
    landfill = fixtures.read_landfill(site["landfill"]["id"])
    assert landfill["operating_status"] == "SUSPENDED_NO_AIRSPACE"
    assert int(landfill["active_cell_count"]) == 0
    cell = get_success_data(api_client.get_cell(site["cell"]["id"], site["site_headers"]))
    assert cell["status"] == "FULL"
    assert cell["final_cover_reference"] is None


def test_connecting_the_well_does_not_release_the_cell_closure():
    """CONNECTED is inside the blocked set, so the second attempt repeats the refusal.

    PRD: "The parent cell must be `ACTIVE`, `FULL` or `CLOSED`; a cell that has not yet begun
    receiving waste has no gas to collect and the connection is refused with
    `ERR_CELL_NOT_READY_FOR_WELLFIELD`."

    Design: Corner/errors/closing_a_cell_with_unfinished_wells_is_rejected_until_each_well_settles
    """
    site = _full_cell_with_one_drilled_well()

    connected = fixtures.connect_gas_well(site["well"]["id"])

    assert connected["status"] == "CONNECTED"
    response = api_client.close_cell(
        site["cell"]["id"], {"final_cover_reference": "FC-2026-01"}, site["site_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CELL_HAS_UNFINISHED_WELLS.value, 409)
    cell = get_success_data(api_client.get_cell(site["cell"]["id"], site["site_headers"]))
    assert cell["status"] == "FULL"


def test_abandoning_the_last_well_lets_the_full_cell_take_its_cap():
    """OFFLINE then ABANDONED settles the wellfield and the cap is accepted.

    PRD: "On success the `final_cover_reference` is stored, the cell's `version` is
    incremented by 1, and the site's `certified_airspace_cy` and `remaining_airspace_cy` are
    recomputed with the landfill's `version` incremented by 1."

    Design: Corner/errors/closing_a_cell_with_unfinished_wells_is_rejected_until_each_well_settles
    """
    site = _full_cell_with_one_drilled_well()
    fixtures.connect_gas_well(site["well"]["id"])
    offline = fixtures.take_gas_well_offline(
        site["well"]["id"], "Wellhead damaged during final grading"
    )
    assert offline["status"] == "OFFLINE"
    abandoned = get_success_data(
        api_client.abandon_gas_well(
            site["well"]["id"],
            {"offline_reason": "Permanently abandoned and grouted"},
            ENV_MANAGER,
        )
    )
    assert abandoned["status"] == "ABANDONED"

    closed = fixtures.close_cell(site["landfill"]["id"], site["cell"]["id"])

    assert closed["status"] == "CLOSED"
    assert closed["final_cover_reference"] == "FC-2026-01"
    assert int(closed["version"]) == int(site["cell"]["version"]) + 1
    landfill = fixtures.read_landfill(site["landfill"]["id"])
    assert_amount(landfill["certified_airspace_cy"], 200, "certified airspace")
