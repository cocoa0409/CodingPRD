"""Breaking the last blank on the shelf during surfacing."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions, fixtures
from test_helpers.test_users import MANAGER_A_HEADERS, TECHNICIAN_A_HEADERS

BREAKAGE_REASON = "GENERATOR_CHIP_ON_FRONT_CURVE"


def _running_surfacing_on_the_only_blank(api):
    """A surfacing job holding the single blank its design has in stock."""
    fixtures.set_clock(api)
    prescriber = fixtures.create_prescriber(api, MANAGER_A_HEADERS)
    plan = fixtures.create_plan(api)
    patient = fixtures.create_insured_patient(api, plan["id"])
    design = fixtures.create_progressive_design(api)
    # A single blank on the shelf, so the replacement search finds nothing.
    lot = fixtures.create_blank_lot(api, design["id"], received_qty=1)
    machine = fixtures.create_generator(api)
    scenario = {
        "prescriber_id": prescriber["id"],
        "plan_id": plan["id"],
        "patient_id": patient["id"],
        "design_id": design["id"],
        "lot_id": lot["id"],
        "machine_id": machine["id"],
    }
    scenario = fixtures.surfaced_verified_prescription(api, scenario)
    scenario = fixtures.surfaced_draft_order(api, scenario)
    scenario = fixtures.surfaced_layout_ready_order(api, scenario)
    scenario = fixtures.surfaced_queued_job(api, scenario)
    operation = fixtures.book_surfacing(api, scenario)
    started = validate_success(
        api.start_lab_operation(operation["id"], TECHNICIAN_A_HEADERS)
    )
    assert started["status"] == "RUNNING"
    scenario["operation_id"] = operation["id"]
    return scenario


def test_breakage_destroys_the_held_blank_rather_than_returning_it(api):
    """The unit is scrapped, not shelved, and the job holds no blank afterwards.

    PRD 3.6: "Its first hop moves the occupation `RUNNING → BROKEN` with that reason
    recorded, raises the job's `breakage_count` by 1, and destroys the held blank by
    lowering the lot's `allocated_qty` by 1 and raising its `scrapped_qty` by 1 —
    the unit is gone, not returned to the shelf."

    Design: Difficulty/transitive_cascade/surfacing_breakage_without_replacement_cascades_three_hops_into_at_risk_turnaround
    """
    scenario = _running_surfacing_on_the_only_blank(api)

    operation = validate_success(
        api.report_breakage(
            scenario["operation_id"],
            {"breakage_reason": BREAKAGE_REASON},
            TECHNICIAN_A_HEADERS,
        )
    )
    assert operation["status"] == "BROKEN"

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["breakage_count"] == 1

    lot = fixtures.read_lot(api, scenario["lot_id"])
    assertions.assert_lot_quantities(
        lot, on_hand=0, allocated=0, consumed=0, scrapped=1, status="DEPLETED"
    )


def test_an_empty_replacement_search_puts_the_job_into_blank_backorder(api):
    """With no eligible lot left the job loses its allocation and waits for stock.

    PRD 3.6: "When no eligible lot exists, the second hop follows from the job now
    holding no blank at all: `blank_lot_id` is set to null and the job moves
    `SURFACING → BLANK_BACKORDER`."

    Design: Difficulty/transitive_cascade/surfacing_breakage_without_replacement_cascades_three_hops_into_at_risk_turnaround
    """
    scenario = _running_surfacing_on_the_only_blank(api)

    validate_success(
        api.report_breakage(
            scenario["operation_id"],
            {"breakage_reason": BREAKAGE_REASON},
            TECHNICIAN_A_HEADERS,
        )
    )

    job = fixtures.read_job(api, scenario["job_id"])
    assert job["status"] == "BLANK_BACKORDER"
    assert job["blank_lot_id"] is None


def test_the_backorder_pushes_the_promise_out_and_flags_the_order_at_risk(api):
    """The due date moves from 12:00 on 2 August to 12:00 on 4 August.

    PRD 3.6: "A third hop follows from that: the order's `promised_due_at` is pushed
    out by a further 48 hours and its `tat_commitment_status` becomes `AT_RISK`, so
    the store learns the promise is in danger at the moment the shop learns it."

    Design: Difficulty/transitive_cascade/surfacing_breakage_without_replacement_cascades_three_hops_into_at_risk_turnaround
    """
    scenario = _running_surfacing_on_the_only_blank(api)

    validate_success(
        api.report_breakage(
            scenario["operation_id"],
            {"breakage_reason": BREAKAGE_REASON},
            TECHNICIAN_A_HEADERS,
        )
    )

    order = fixtures.read_order(api, scenario["order_id"])
    assert order["promised_due_at"] == "2026-08-04T12:00:00.000Z"
    assert order["tat_commitment_status"] == "AT_RISK"
    assert order["promised_tat_hours"] == 36
    assert order["fulfillment_status"] == "IN_LAB"
    assert order["billing_status"] == "PROVISIONAL_QUOTED"
