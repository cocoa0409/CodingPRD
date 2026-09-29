"""Non-linear lifecycles: bounded rework loops, twin state dimensions, branching tunes."""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_instant_equals
from test_helpers.constants import CLOCK_DEFAULT_UTC
from test_helpers.factories import liner_qa_resubmit_payload
from test_helpers.test_users import TEST_USERS, make_site_operator_headers

CQA = TEST_USERS["cqa_engineer_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
UNDER_SCORE_COUNTERS = {"passing_test_count": 16}


def _package_under_review():
    """A package scoring 80.00 — below the approval threshold — sitting in review.

    Sixteen of twenty destructive tests pass, so returning is the reviewer's only move.
    """
    landfill = fixtures.create_landfill()
    cell = fixtures.create_cell_under_construction(landfill["id"])
    package = fixtures.submit_liner_qa_package(
        landfill["id"], cell["id"], **UNDER_SCORE_COUNTERS
    )
    assert_amount(package["qa_conformance_score"], 80.00, "conformance score")
    assert package["revision_round"] == 1
    package = fixtures.begin_liner_review(package["id"])
    return landfill, cell, package


def _return_package(package_id, note):
    return get_success_data(
        api_client.return_liner_qa_package(package_id, {"return_note": note}, CQA)
    )


def _resubmit(landfill_id, package_id):
    return get_success_data(
        api_client.resubmit_liner_qa_package(
            package_id,
            liner_qa_resubmit_payload(**UNDER_SCORE_COUNTERS),
            make_site_operator_headers(landfill_id),
        )
    )


def test_a_return_pushes_the_round_counter_and_reverts_the_parent_cell():
    """Round 1 of 3 rework: RETURNED, round 2, and the cell goes back to construction.

    PRD: "When the current `revision_round` is fewer than 3 rework rounds, the package
    moves `UNDER_REVIEW → RETURNED`, its `revision_round` is incremented by 1 and its
    `version` is incremented by 1, and — caused by that return — the parent cell reverts
    `QA_REVIEW → UNDER_CONSTRUCTION` with its own `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/liner_qa_return_resubmit_cycle_rejects_cell_on_third_round
    """
    landfill, cell, package = _package_under_review()

    returned = _return_package(package["id"], "Seam log incomplete on panels 12-18.")

    assert returned["status"] == "RETURNED"
    assert returned["revision_round"] == 2
    refreshed_cell = get_success_data(
        api_client.get_cell(cell["id"], make_site_operator_headers(landfill["id"]))
    )
    assert refreshed_cell["status"] == "UNDER_CONSTRUCTION"
    assert_amount(
        fixtures.read_landfill(landfill["id"])["certified_airspace_cy"],
        0,
        "certified airspace after a return",
    )


def test_resubmission_reopens_the_cycle_and_drops_the_reviewer_stamp():
    """RETURNED goes back to SUBMITTED and the cell revisits QA_REVIEW.

    PRD: "The package moves `RETURNED → SUBMITTED` and, caused by that resubmission, the
    parent cell moves `UNDER_CONSTRUCTION → QA_REVIEW` with its `version` incremented by
    1, closing the cycle `SUBMITTED → UNDER_REVIEW → RETURNED → SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/liner_qa_return_resubmit_cycle_rejects_cell_on_third_round
    """
    landfill, cell, package = _package_under_review()
    _return_package(package["id"], "Seam log incomplete on panels 12-18.")

    resubmitted = _resubmit(landfill["id"], package["id"])

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["reviewed_by_user_id"] is None
    assert resubmitted["revision_round"] == 2
    refreshed_cell = get_success_data(
        api_client.get_cell(cell["id"], make_site_operator_headers(landfill["id"]))
    )
    assert refreshed_cell["status"] == "QA_REVIEW"


def test_the_third_return_takes_the_rejection_branch_of_the_same_action():
    """The identical return action rejects the package and its cell on round 3.

    PRD: "When the current `revision_round` has already reached 3, the same action takes
    the *other* branch: the package moves `UNDER_REVIEW → REJECTED`, which is terminal, its
    `version` is incremented by 1, and the parent cell is driven `QA_REVIEW → REJECTED`,
    also terminal, with its own `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/liner_qa_return_resubmit_cycle_rejects_cell_on_third_round
    """
    landfill, cell, package = _package_under_review()
    first = _return_package(package["id"], "Seam log incomplete on panels 12-18.")
    assert first["revision_round"] == 2
    _resubmit(landfill["id"], package["id"])
    fixtures.begin_liner_review(package["id"])
    second = _return_package(package["id"], "Destructive test coverage still short.")
    assert second["status"] == "RETURNED" and second["revision_round"] == 3
    _resubmit(landfill["id"], package["id"])
    fixtures.begin_liner_review(package["id"])

    third = _return_package(package["id"], "Third round exhausted; liner not certifiable.")

    assert third["status"] == "REJECTED"
    assert third["revision_round"] == 3, "the counter is not pushed past three rework rounds"
    refreshed_cell = get_success_data(
        api_client.get_cell(cell["id"], make_site_operator_headers(landfill["id"]))
    )
    assert refreshed_cell["status"] == "REJECTED"
    assert_amount(
        fixtures.read_landfill(landfill["id"])["certified_airspace_cy"],
        0,
        "certified airspace after a rejection",
    )


def test_a_rejected_package_cannot_be_reopened_for_review():
    """The terminal state is locked: review may only be opened from SUBMITTED.

    PRD: "Review is opened by a `CqaEngineer`, moving the package `SUBMITTED →
    UNDER_REVIEW` and stamping `reviewed_by_user_id` with the reviewing `X-User-ID`, with
    `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/liner_qa_return_resubmit_cycle_rejects_cell_on_third_round
    """
    landfill, cell, package = _package_under_review()
    _return_package(package["id"], "Round one.")
    _resubmit(landfill["id"], package["id"])
    fixtures.begin_liner_review(package["id"])
    _return_package(package["id"], "Round two.")
    _resubmit(landfill["id"], package["id"])
    fixtures.begin_liner_review(package["id"])
    _return_package(package["id"], "Round three.")

    response = api_client.begin_liner_qa_review(package["id"], CQA)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)


def _day_with_two_loads():
    """An OPEN day carrying a 100 t truck and a 60 t truck, both PENDING and UNBILLED."""
    site = fixtures.setup_open_day(
        agreement_overrides={
            "posted_tipping_fee_per_ton": 42.5,
            "host_fee_per_ton": 3.75,
            "tier1_monthly_tons": 100,
            "royalty_tier1_pct": 0.04,
            "royalty_tier2_pct": 0.07,
        },
        day_overrides={
            "operating_date": "2026-08-05T00:00:00Z",
            "working_face_area_sf": 5000,
            "cover_material_type": "ALTERNATIVE_TARP",
        },
    )
    site["load_one"] = fixtures.receive_load(
        site["landfill"]["id"], site["day"]["id"], hauler_ref="H-1", manifest_tons=100.0
    )
    site["load_two"] = fixtures.receive_load(
        site["landfill"]["id"], site["day"]["id"], hauler_ref="H-2", manifest_tons=60.0
    )
    assert site["load_one"]["screening_status"] == "PENDING"
    assert site["load_one"]["billing_status"] == "UNBILLED"
    return site


def test_flagging_moves_screening_alone_then_clearance_moves_both_dimensions():
    """FLAGGED leaves billing UNBILLED; one clearance call then advances both.

    PRD: "Flagging touches nothing on the billing dimension, which stays `UNBILLED`, and
    the load's `version` is incremented by 1."

    Design: Difficulty/non_linear_state_machine/waste_load_screening_and_billing_dimensions_advance_independently
    """
    site = _day_with_two_loads()

    flagged = fixtures.flag_load(
        site["landfill"]["id"],
        site["load_one"]["id"],
        "Tarp obscured the load; visual re-check required.",
    )
    assert flagged["screening_status"] == "FLAGGED"
    assert flagged["billing_status"] == "UNBILLED"

    cleared = fixtures.clear_screening(site["landfill"]["id"], site["load_one"]["id"])

    assert cleared["screening_status"] == "CLEARED"
    assert cleared["billing_status"] == "PROVISIONAL"
    assert_amount(cleared["gate_charge_amount"], 4625.00, "gate charge")


def test_rejection_voids_the_billing_dimension_on_the_same_call():
    """A turned-away truck reads REJECTED and VOID with its gate price cleared.

    PRD: "On the same request the billing dimension is voided: `billing_status` becomes
    `VOID` and any `gate_charge_amount` already written is reset to null."

    Design: Difficulty/non_linear_state_machine/waste_load_screening_and_billing_dimensions_advance_independently
    """
    site = _day_with_two_loads()

    rejected = fixtures.reject_load(
        site["landfill"]["id"], site["load_two"]["id"], "Unmanifested drum in the load."
    )

    assert rejected["screening_status"] == "REJECTED"
    assert rejected["billing_status"] == "VOID"
    assert rejected["gate_charge_amount"] is None


def test_day_close_advances_only_the_billing_dimension():
    """Screening stays CLEARED while billing walks PROVISIONAL to FINALIZED.

    PRD: "The final pricing runs at day close and bills the *certified* tonnage; it moves
    the load's billing dimension `PROVISIONAL → FINALIZED` and increments the load's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/waste_load_screening_and_billing_dimensions_advance_independently
    """
    site = _day_with_two_loads()
    fixtures.clear_screening(site["landfill"]["id"], site["load_one"]["id"])
    fixtures.certify_weight(site["landfill"]["id"], site["load_one"]["id"], 100.0)
    fixtures.reject_load(
        site["landfill"]["id"], site["load_two"]["id"], "Unmanifested drum in the load."
    )

    closed = fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    assert_amount(closed["tons_placed"], 100.00, "tons placed excludes the rejected load")
    assert_amount(closed["airspace_consumed_cy"], 117.65, "airspace consumed")
    load = get_success_data(
        api_client.get_waste_load(site["load_one"]["id"], site["scale_headers"])
    )
    assert load["screening_status"] == "CLEARED"
    assert load["billing_status"] == "FINALIZED"
    assert_amount(load["host_royalty_amount"], 170.00, "host royalty")
    assert_amount(load["final_charge_amount"], 4795.00, "final charge")


def test_amending_the_day_walks_billing_back_without_touching_screening():
    """Billing returns to PROVISIONAL, the final charge clears, the gate price stands.

    PRD: "`gate_charge_amount` is deliberately left untouched — the provisional gate price
    stands, because the truck really did cross the scale at the manifest weight."

    Design: Difficulty/non_linear_state_machine/waste_load_screening_and_billing_dimensions_advance_independently
    """
    site = _day_with_two_loads()
    fixtures.clear_screening(site["landfill"]["id"], site["load_one"]["id"])
    fixtures.certify_weight(site["landfill"]["id"], site["load_one"]["id"], 100.0)
    fixtures.reject_load(
        site["landfill"]["id"], site["load_two"]["id"], "Unmanifested drum in the load."
    )
    fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    fixtures.amend_operating_day(
        site["landfill"]["id"], site["day"]["id"], "Scale ticket 88 re-weighed."
    )

    load = get_success_data(
        api_client.get_waste_load(site["load_one"]["id"], site["scale_headers"])
    )
    assert load["screening_status"] == "CLEARED"
    assert load["billing_status"] == "PROVISIONAL"
    assert load["final_charge_amount"] is None
    assert load["host_royalty_amount"] is None
    assert_amount(load["gate_charge_amount"], 4625.00, "gate charge survives the amend")


def _site_with_connected_well():
    """An ACTIVE cell carrying one CONNECTED well on a COMPLIANT site."""
    site = fixtures.setup_active_site(with_host_agreement=False)
    well = fixtures.drill_gas_well(site["cell"]["id"], well_code="W-1", depth_ft=85)
    assert well["status"] == "DRILLED"
    site["well"] = fixtures.connect_gas_well(well["id"])
    assert site["well"]["status"] == "CONNECTED"
    assert fixtures.read_landfill(site["landfill"]["id"])["gas_collection_status"] == "COMPLIANT"
    return site


def test_an_out_of_specification_tune_drives_the_well_and_the_site_off_compliance():
    """Methane 40.0 and vacuum 8.0 both miss specification, so the well needs tuning.

    PRD: "When any one of those three fails, that is, when methane is below 45.0 or oxygen
    is above 5.0 or vacuum is below 10.0, the well moves to `TUNING_REQUIRED` instead."

    Design: Difficulty/non_linear_state_machine/gas_well_tune_branches_on_readings_then_cycles_through_exceedance
    """
    site = _site_with_connected_well()

    tuned = fixtures.tune_gas_well(
        site["well"]["id"], last_vacuum_in_h2o=8.0, last_methane_pct=40.0, last_oxygen_pct=4.0
    )

    assert tuned["status"] == "TUNING_REQUIRED"
    assert_instant_equals(tuned["last_tuned_at"], CLOCK_DEFAULT_UTC, "last tuned at")
    assert (
        fixtures.read_landfill(site["landfill"]["id"])["gas_collection_status"]
        == "CORRECTIVE_ACTION"
    )


def test_the_same_tune_action_returns_the_well_to_specification():
    """Readings inside every bound take the other branch of the identical action.

    PRD: "When the methane percentage is at least 45.0 **and** the oxygen percentage is at
    most 5.0 **and** the vacuum is at least 10.0 inches of water column — all three bounds
    inclusive — the well is within specification and moves to `ONLINE`."

    Design: Difficulty/non_linear_state_machine/gas_well_tune_branches_on_readings_then_cycles_through_exceedance
    """
    site = _site_with_connected_well()
    fixtures.tune_gas_well(
        site["well"]["id"], last_vacuum_in_h2o=8.0, last_methane_pct=40.0, last_oxygen_pct=4.0
    )

    retuned = fixtures.tune_gas_well(
        site["well"]["id"], last_vacuum_in_h2o=15.0, last_methane_pct=52.0, last_oxygen_pct=2.0
    )

    assert retuned["status"] == "ONLINE"
    assert fixtures.read_landfill(site["landfill"]["id"])["gas_collection_status"] == "COMPLIANT"


def test_a_surface_exceedance_re_enters_tuning_required_through_a_different_trigger():
    """A 500 ppm walkover nominates the online well and blocks a premature resolution.

    PRD: "The first-ranked well is moved `ONLINE → TUNING_REQUIRED`, its `version` is
    incremented by 1, and its `id` is written to the scan's `corrective_well_id`."

    Design: Difficulty/non_linear_state_machine/gas_well_tune_branches_on_readings_then_cycles_through_exceedance
    """
    site = _site_with_connected_well()
    fixtures.tune_gas_well(site["well"]["id"])

    scan = fixtures.record_surface_scan(
        site["landfill"]["id"],
        scanned_on="2026-08-01T00:00:00Z",
        grid_points_count=240,
        max_reading_ppm=500.0,
        exceedance_point_ref="GRID-118",
    )

    assert scan["status"] == "EXCEEDANCE_OPEN"
    assert scan["corrective_well_id"] == site["well"]["id"]
    well = get_success_data(api_client.get_gas_well(site["well"]["id"], ENV_MANAGER))
    assert well["status"] == "TUNING_REQUIRED"

    response = api_client.resolve_surface_emission_scan(
        scan["id"], {"remediation_note": "Premature closure attempt."}, ENV_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)


def test_the_site_posture_clears_only_once_the_scan_itself_is_resolved():
    """The well can be back ONLINE while the site stays in corrective action.

    PRD: "On success the note is stored and the scan's `version` is incremented by 1, and if
    no other scan of the site remains in `EXCEEDANCE_OPEN` and no well in any of its cells
    remains in `TUNING_REQUIRED`, the site's `gas_collection_status` returns to `COMPLIANT`
    with the landfill's `version` incremented by 1."

    Design: Difficulty/non_linear_state_machine/gas_well_tune_branches_on_readings_then_cycles_through_exceedance
    """
    site = _site_with_connected_well()
    fixtures.tune_gas_well(site["well"]["id"])
    scan = fixtures.record_surface_scan(
        site["landfill"]["id"],
        scanned_on="2026-08-01T00:00:00Z",
        grid_points_count=240,
        max_reading_ppm=500.0,
        exceedance_point_ref="GRID-118",
    )

    back_online = fixtures.tune_gas_well(site["well"]["id"])
    assert back_online["status"] == "ONLINE"
    assert (
        fixtures.read_landfill(site["landfill"]["id"])["gas_collection_status"]
        == "CORRECTIVE_ACTION"
    ), "the open exceedance keeps the site in corrective action"

    resolved = fixtures.resolve_surface_scan(
        scan["id"], "Cover regraded at GRID-118 and wellfield re-tuned."
    )

    assert resolved["status"] == "RESOLVED"
    assert fixtures.read_landfill(site["landfill"]["id"])["gas_collection_status"] == "COMPLIANT"
