"""A shelf one tenth of a millimetre short of what the traced frame needs."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import MANAGER_A_HEADERS, TECHNICIAN_A_HEADERS

SHORT_LOT = {"blank_sku": "BLK-167-769", "diameter_mm": 76.9, "received_qty": 2}
EXACT_LOT = {
    "blank_sku": "BLK-167-770",
    "diameter_mm": 77.0,
    "received_qty": 1,
    "received_on": "2026-06-20",
}


def _order_needing_seventy_seven_millimetres(api):
    """A traced progressive order whose only stock is 76.9 mm."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api, MANAGER_A_HEADERS)
    plan = fixtures.create_plan(api)
    patient = fixtures.create_insured_patient(api, plan["id"])
    design = fixtures.create_progressive_design(api)
    short_lot = fixtures.create_blank_lot(api, design["id"], **SHORT_LOT)
    scenario = {
        "prescriber_id": prescriber["id"],
        "plan_id": plan["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
        "lot_id": short_lot["id"],
        "short_lot_id": short_lot["id"],
    }
    scenario = fixtures.surfaced_verified_prescription(api, scenario)
    scenario = fixtures.surfaced_draft_order(api, scenario)
    scenario = fixtures.surfaced_layout_ready_order(api, scenario)
    assert scenario["layout"]["required_blank_diameter_mm"] == 77.0
    assert scenario["layout"]["layout_status"] == "COMPUTED"
    return scenario


def _add_exact_lot(api, scenario):
    lot = validate_success(
        api.create_lens_blank_lot(
            f.create_lens_blank_lot_payload(scenario["design_id"], **EXACT_LOT),
            MANAGER_A_HEADERS,
        ),
        expected_status=201,
    )
    scenario["exact_lot_id"] = lot["id"]
    return lot


def test_a_lot_one_tenth_short_is_not_a_candidate_at_all(api):
    """76.9 mm cannot serve a 77.0 mm requirement, so commitment is refused.

    PRD 3.5: "For a surfacing job, the candidate lots are those whose
    `lens_design_id` matches the order's `lens_design_id`, whose `status` is
    `AVAILABLE`, whose `on_hand_qty` is greater than zero, and whose `diameter_mm` is
    greater than or equal to the layout's `required_blank_diameter_mm`."

    Design: Difficulty/boundary_precision_check/blank_lot_diameter_one_tenth_short_blocks_job_creation_and_exact_match_allocates
    """
    scenario = _order_needing_seventy_seven_millimetres(api)

    validate_error(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        ),
        ApiErrorId.NO_ELIGIBLE_BLANK_LOT.value,
        409,
    )

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["fulfillment_status"] == "LAYOUT_READY"

    _, meta = validate_paginated(api.list_lab_jobs(TECHNICIAN_A_HEADERS))
    assert meta["total_count"] == 0


def test_a_lot_of_exactly_the_required_diameter_is_allocated(api):
    """The comparison is inclusive, so 77.0 mm satisfies 77.0 mm.

    PRD 3.5: "For a surfacing job, one unit is reserved from the chosen lot — its
    `on_hand_qty` falls by 1 and its `allocated_qty` rises by 1 — and `blank_lot_id`
    is set to that lot; if the reservation drives the lot's `on_hand_qty` to 0, the
    lot moves `AVAILABLE → DEPLETED` and stops being an eligible candidate."

    Design: Difficulty/boundary_precision_check/blank_lot_diameter_one_tenth_short_blocks_job_creation_and_exact_match_allocates
    """
    scenario = _order_needing_seventy_seven_millimetres(api)
    validate_error(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        ),
        ApiErrorId.NO_ELIGIBLE_BLANK_LOT.value,
        409,
    )

    _add_exact_lot(api, scenario)
    scenario = fixtures.surfaced_queued_job(api, scenario)

    job = scenario["job"]
    assert job["route"] == "SURFACE_AND_EDGE"
    assert job["status"] == "QUEUED"
    assert job["blank_lot_id"] == scenario["exact_lot_id"]

    exact = fixtures.read_lot(api, scenario["exact_lot_id"])
    assertions.assert_lot_quantities(
        exact, on_hand=0, allocated=1, consumed=0, scrapped=0, status="DEPLETED"
    )
    assert fixtures.read_order(api, scenario["order_id"])["fulfillment_status"] == "IN_LAB"


def test_the_short_lot_is_never_touched(api):
    """The 76.9 mm units stay on the shelf, unreserved, throughout.

    PRD 3.1: "`on_hand_qty` counts units physically on the shelf and not yet
    reserved; `allocated_qty` counts units reserved by jobs that have neither
    consumed nor released them; `consumed_qty` counts units surfaced successfully
    into a finished lens; `scrapped_qty` counts units destroyed by a reported
    breakage or by a job that ran out of rework budget."

    Design: Difficulty/boundary_precision_check/blank_lot_diameter_one_tenth_short_blocks_job_creation_and_exact_match_allocates
    """
    scenario = _order_needing_seventy_seven_millimetres(api)
    validate_error(
        api.create_lab_job(
            f.create_lab_job_payload(scenario["order_id"]), TECHNICIAN_A_HEADERS
        ),
        ApiErrorId.NO_ELIGIBLE_BLANK_LOT.value,
        409,
    )
    _add_exact_lot(api, scenario)
    fixtures.surfaced_queued_job(api, scenario)

    short = fixtures.read_lot(api, scenario["short_lot_id"])
    assertions.assert_lot_quantities(
        short, on_hand=2, allocated=0, consumed=0, scrapped=0, status="AVAILABLE"
    )
    assertions.assert_blank_ledger_conserved(short)
