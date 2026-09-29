"""Multi-link cascades where each link is caused by the one before it."""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_density, assert_instant_equals
from test_helpers.test_users import TEST_USERS

ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
FINANCE = TEST_USERS["finance_filer_headers"]
AGENCY = TEST_USERS["regulatory_agency_headers"]

SMALL_CELL = {
    "cell_code": "C-2",
    "design_airspace_cy": 200,
    "design_area_sf": 45001,
    "construction_end_date": "2026-07-20T00:00:00Z",
}


def _site_at_the_brink():
    """A 200 cy cell, an unrelated approved profile, and a day holding 166.60 t.

    At the 0.8500 capped density those tons burn 196.00 cubic yards, which is exactly
    98 percent of the cell.
    """
    site = fixtures.setup_active_site(
        cell_overrides=dict(SMALL_CELL),
        agreement_overrides={
            "posted_tipping_fee_per_ton": 42.5,
            "host_fee_per_ton": 3.75,
            "tier1_monthly_tons": 100,
            "royalty_tier1_pct": 0.04,
            "royalty_tier2_pct": 0.07,
        },
    )
    site["approval"] = fixtures.setup_approved_special_waste(
        site["landfill"]["id"],
        waste_code="IND-221",
        approved_tons_cap=500,
        effective_from="2026-01-01T00:00:00Z",
        expires_on="2027-01-01T00:00:00Z",
    )
    assert site["approval"]["status"] == "APPROVED"
    site["day"] = fixtures.open_operating_day(
        site["landfill"]["id"],
        site["cell"]["id"],
        operating_date="2026-08-05T00:00:00Z",
        working_face_area_sf=5000,
        cover_material_type="ALTERNATIVE_TARP",
    )
    site["load"] = fixtures.place_certified_load(
        site["landfill"]["id"], site["day"]["id"], 166.6, hauler_ref="H-9", manifest_tons=166.6
    )
    return site


def test_day_close_fills_the_cell_to_exactly_ninety_eight_percent():
    """196.00 of 200 cubic yards reaches the inclusive full-cell fraction.

    PRD: "**Link 2**, caused by link 1. If the recomputed cell consumption has reached at
    least 98 percent of the cell's `design_airspace_cy` — that is, at or above the
    full-cell fraction of 0.98, with exact equality counting as full — the cell moves
    `ACTIVE → FULL` and its `version` is incremented by 1."

    Design: Difficulty/transitive_cascade/day_close_cascades_four_links_to_special_waste_suspension
    """
    site = _site_at_the_brink()

    closed = fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    assert closed["status"] == "CLOSED"
    assert_amount(closed["tons_placed"], 166.60, "tons placed")
    assert_density(closed["effective_density_tons_per_cy"], 0.8500, "effective density")
    assert_amount(closed["airspace_consumed_cy"], 196.00, "airspace consumed")

    cell = get_success_data(api_client.get_cell(site["cell"]["id"], site["site_headers"]))
    assert_amount(cell["consumed_airspace_cy"], 196.00, "cell consumed airspace")
    assert_amount(cell["fill_pct"], 98.00, "cell fill percentage")
    assert cell["status"] == "FULL"


def test_the_full_cell_suspends_the_site_and_then_its_special_waste_profiles():
    """Link 4 suspends a profile that no load in this test ever referenced.

    PRD: "**Link 4**, caused by link 3, and only because the site stopped accepting waste.
    Every special-waste approval of the site sitting in `APPROVED` is moved to `SUSPENDED`
    and has its `version` incremented by 1."

    Design: Difficulty/transitive_cascade/day_close_cascades_four_links_to_special_waste_suspension
    """
    site = _site_at_the_brink()

    fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    landfill = fixtures.read_landfill(site["landfill"]["id"])
    assert landfill["active_cell_count"] == 0
    assert landfill["operating_status"] == "SUSPENDED_NO_AIRSPACE"

    approval = get_success_data(
        api_client.get_special_waste_approval(site["approval"]["id"], ENV_MANAGER)
    )
    assert approval["status"] == "SUSPENDED"
    assert_amount(approval["consumed_tons"], 0, "consumed tons")


def test_the_ledger_sync_does_not_overwrite_the_suspended_posture():
    """0.00 remaining years would restrict an OPEN site, but this one is already suspended.

    PRD: "The **ledger sync** recomputes the site's `consumed_airspace_cy`,
    `remaining_airspace_cy` and `remaining_life_years`; if the recomputed
    `remaining_life_years` is below 2.0 years and the site is currently `OPEN`, its
    `operating_status` is set to `RESTRICTED_AIRSPACE` — the site keeps taking waste, but
    the shortening life is now visible in its posture."

    Design: Difficulty/transitive_cascade/day_close_cascades_four_links_to_special_waste_suspension
    """
    site = _site_at_the_brink()

    fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    landfill = fixtures.read_landfill(site["landfill"]["id"])
    assert_amount(landfill["consumed_airspace_cy"], 196.00, "site consumed airspace")
    assert_amount(landfill["remaining_airspace_cy"], 4.00, "site remaining airspace")
    assert_amount(landfill["remaining_life_years"], 0.00, "remaining life years")
    assert landfill["operating_status"] == "SUSPENDED_NO_AIRSPACE", (
        "the suspended posture is not overwritten with RESTRICTED_AIRSPACE"
    )


def test_the_same_close_finalises_the_load_across_both_royalty_tiers():
    """166.60 certified tons split 100 tier-1 and 66.60 tier-2 into 8073.39.

    PRD: "`host_royalty_amount` is the sum of those two already-rounded components, rounded
    to 2 decimal places."

    Design: Difficulty/transitive_cascade/day_close_cascades_four_links_to_special_waste_suspension
    """
    site = _site_at_the_brink()

    fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    load = get_success_data(
        api_client.get_waste_load(site["load"]["id"], site["scale_headers"])
    )
    assert load["billing_status"] == "FINALIZED"
    assert_amount(load["final_charge_amount"], 8073.39, "final charge")


def _funded_site_with_a_second_liner_in_review():
    """A funded site whose second cell's liner package is sitting in review."""
    landfill = fixtures.create_landfill()
    fixtures.setup_qa_certified_cell(
        landfill["id"],
        cell_overrides={"cell_code": "C-1", "design_airspace_cy": 1000000, "design_area_sf": 120001},
    )
    estimate = fixtures.setup_funded_assurance(
        landfill["id"], instrument_type="LETTER_OF_CREDIT"
    )
    assert estimate["status"] == "CERTIFIED"
    assert_amount(estimate["funding_shortfall"], 0.00, "shortfall once fully funded")
    assert_amount(estimate["required_assurance_amount"], 4742266.36, "required assurance")
    before = fixtures.read_landfill(landfill["id"])
    assert before["financial_assurance_status"] == "FUNDED"
    assert_amount(before["certified_airspace_cy"], 1000000, "certified airspace")

    second = fixtures.create_cell_under_construction(landfill["id"], **SMALL_CELL)
    package = fixtures.submit_liner_qa_package(landfill["id"], second["id"])
    package = fixtures.begin_liner_review(package["id"])
    return {"landfill": landfill, "estimate": estimate, "cell": second, "package": package}


def test_approving_a_liner_certifies_its_cell_and_widens_the_certified_basis():
    """Links 1 and 2: the cell joins the certified set and the site's airspace grows.

    PRD: "**Link 2**, caused by link 1. Because the cell has entered the certified set, the
    site's `certified_airspace_cy` is recomputed and now includes this cell's
    `design_airspace_cy`; `remaining_airspace_cy` and `remaining_life_years` are recomputed
    from it, and the landfill's `version` is incremented by 1."

    Design: Difficulty/transitive_cascade/qa_approve_cascades_four_links_into_assurance_shortfall
    """
    state = _funded_site_with_a_second_liner_in_review()

    approved = fixtures.approve_liner_package(
        state["package"]["id"], certification_reference="CQA-2026-002"
    )

    assert approved["status"] == "APPROVED"
    cell = get_success_data(
        api_client.get_cell(state["cell"]["id"], TEST_USERS["platform_admin_headers"])
    )
    assert cell["status"] == "QA_CERTIFIED"
    assert_amount(
        fixtures.read_landfill(state["landfill"]["id"])["certified_airspace_cy"],
        1000200,
        "certified airspace after the approval",
    )


def test_the_changed_basis_stales_the_estimate_and_withdraws_the_funded_posture():
    """Links 3 and 4: a purely engineering action reaches a purely financial state.

    PRD: "**Link 4**, caused by link 3, and only when link 3 actually staled an estimate.
    The site's `financial_assurance_status` is set to `SHORTFALL_REVIEW`, and the landfill's
    `version` is incremented by 1 a second time on the same request."

    Design: Difficulty/transitive_cascade/qa_approve_cascades_four_links_into_assurance_shortfall
    """
    state = _funded_site_with_a_second_liner_in_review()

    fixtures.approve_liner_package(state["package"]["id"], certification_reference="CQA-2026-002")

    estimate = get_success_data(
        api_client.get_closure_cost_estimate(state["estimate"]["id"], FINANCE)
    )
    assert estimate["status"] == "STALE"
    assert_amount(estimate["funding_shortfall"], 0.00, "shortfall is untouched by the cascade")

    landfill = fixtures.read_landfill(state["landfill"]["id"])
    assert landfill["financial_assurance_status"] == "SHORTFALL_REVIEW"
    assert_amount(
        landfill["assurance_funded_amount"], 4742266.36, "funded amount is untouched"
    )


def test_the_withdrawn_posture_blocks_authorization_of_the_cell_just_certified():
    """The fourth link is load-bearing: the agency refuses the newly certified cell.

    PRD: "And the site's `financial_assurance_status` must read `FUNDED`; a site that is
    `UNFUNDED`, in `SHORTFALL_REVIEW` or `LAPSED` must first record a sufficient assurance
    instrument, and until it does the authorization is refused with
    `ERR_FINANCIAL_ASSURANCE_SHORTFALL` (HTTP 402)."

    Design: Difficulty/transitive_cascade/qa_approve_cascades_four_links_into_assurance_shortfall
    """
    state = _funded_site_with_a_second_liner_in_review()
    fixtures.approve_liner_package(state["package"]["id"], certification_reference="CQA-2026-002")

    response = api_client.authorize_waste_placement(
        state["cell"]["id"], {"approval_reference": "AGY-2026-79"}, AGENCY
    )

    validate_error(response, ApiErrorId.ERR_FINANCIAL_ASSURANCE_SHORTFALL.value, 402)


def _site_with_two_connected_wells():
    site = fixtures.setup_active_site(with_host_agreement=False)
    first = fixtures.drill_gas_well(site["cell"]["id"], well_code="W-1", depth_ft=85)
    site["well_one"] = fixtures.connect_gas_well(first["id"])
    second = fixtures.drill_gas_well(site["cell"]["id"], well_code="W-2", depth_ft=90)
    site["well_two"] = fixtures.connect_gas_well(second["id"])
    return site


def _well(well_id):
    return get_success_data(api_client.get_gas_well(well_id, ENV_MANAGER))


def test_an_exceedance_with_no_online_well_still_moves_the_site_off_compliance():
    """The candidate pool is empty, yet the third link fires anyway.

    PRD: "**This link fires even when the candidate pool was empty**, because the exceedance
    itself is still unresolved regardless of whether a well could be nominated."

    Design: Difficulty/transitive_cascade/surface_exceedance_cascade_survives_empty_candidate_pool
    """
    site = _site_with_two_connected_wells()

    scan = fixtures.record_surface_scan(
        site["landfill"]["id"],
        scanned_on="2026-08-01T00:00:00Z",
        grid_points_count=240,
        max_reading_ppm=512.4,
        exceedance_point_ref="GRID-004",
    )

    assert scan["status"] == "EXCEEDANCE_OPEN"
    assert scan["corrective_well_id"] is None
    assert _well(site["well_one"]["id"])["status"] == "CONNECTED"
    assert _well(site["well_two"]["id"])["status"] == "CONNECTED"
    assert (
        fixtures.read_landfill(site["landfill"]["id"])["gas_collection_status"]
        == "CORRECTIVE_ACTION"
    )


def test_the_selector_nominates_the_least_recently_tuned_online_well():
    """W-1, tuned a day before W-2, is the one driven back to TUNING_REQUIRED.

    PRD: "Candidates are ranked by `last_tuned_at` ascending — the least recently attended
    well first — with a never-tuned well sorting as though its `last_tuned_at` were its
    `created_at`, and ties broken by `created_at` ascending."

    Design: Difficulty/transitive_cascade/surface_exceedance_cascade_survives_empty_candidate_pool
    """
    site = _site_with_two_connected_wells()
    fixtures.record_surface_scan(
        site["landfill"]["id"],
        scanned_on="2026-08-01T00:00:00Z",
        grid_points_count=240,
        max_reading_ppm=512.4,
        exceedance_point_ref="GRID-004",
    )
    fixtures.set_clock("2026-08-02T00:00:00Z")
    first_tuned = fixtures.tune_gas_well(site["well_one"]["id"])
    fixtures.set_clock("2026-08-03T00:00:00Z")
    second_tuned = fixtures.tune_gas_well(
        site["well_two"]["id"],
        last_vacuum_in_h2o=16.0,
        last_methane_pct=55.0,
        last_oxygen_pct=1.5,
    )
    assert_instant_equals(first_tuned["last_tuned_at"], "2026-08-02T00:00:00Z", "W-1 tuned at")
    assert_instant_equals(second_tuned["last_tuned_at"], "2026-08-03T00:00:00Z", "W-2 tuned at")
    fixtures.set_clock("2026-08-04T00:00:00Z")

    scan = fixtures.record_surface_scan(
        site["landfill"]["id"],
        scanned_on="2026-08-04T00:00:00Z",
        grid_points_count=240,
        max_reading_ppm=640.0,
        exceedance_point_ref="GRID-118",
    )

    assert scan["status"] == "EXCEEDANCE_OPEN"
    assert scan["corrective_well_id"] == site["well_one"]["id"]
    assert _well(site["well_one"]["id"])["status"] == "TUNING_REQUIRED"
    assert _well(site["well_two"]["id"])["status"] == "ONLINE"


def test_an_earlier_open_scan_is_not_retro_fitted_with_the_nominated_well():
    """Only the scan being recorded writes a corrective well id.

    PRD: "**Link 2**, caused by link 1. One well is deterministically selected for
    re-tuning."

    Design: Difficulty/transitive_cascade/surface_exceedance_cascade_survives_empty_candidate_pool
    """
    site = _site_with_two_connected_wells()
    first_scan = fixtures.record_surface_scan(
        site["landfill"]["id"],
        scanned_on="2026-08-01T00:00:00Z",
        grid_points_count=240,
        max_reading_ppm=512.4,
        exceedance_point_ref="GRID-004",
    )
    fixtures.set_clock("2026-08-02T00:00:00Z")
    fixtures.tune_gas_well(site["well_one"]["id"])
    fixtures.set_clock("2026-08-04T00:00:00Z")

    fixtures.record_surface_scan(
        site["landfill"]["id"],
        scanned_on="2026-08-04T00:00:00Z",
        grid_points_count=240,
        max_reading_ppm=640.0,
        exceedance_point_ref="GRID-118",
    )

    refreshed = get_success_data(
        api_client.get_surface_emission_scan(first_scan["id"], ENV_MANAGER)
    )
    assert refreshed["status"] == "EXCEEDANCE_OPEN"
    assert refreshed["corrective_well_id"] is None
