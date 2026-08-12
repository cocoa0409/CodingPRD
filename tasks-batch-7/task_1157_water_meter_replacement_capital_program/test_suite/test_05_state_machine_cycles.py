"""Cyclic state machines: work order no-access loop, invoice dispute loop,
complaint bench-review loop (PRD 3.4, 3.8, 3.9)."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, create_invoice, fc, get_success_data,
    setup_program_wave_contractor, setup_work_order_closed,
    setup_work_order_swapped, setup_work_order_notified, book_appointment,
    no_access, setup_filed_complaint, validate_paginated, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]
CS = TEST_USERS["customer_service_headers"]


def test_no_access_cycle_returns_to_scheduled(api):
    """PRD §3.4: "When the crew cannot get in, the assigned `FieldContractor`
    reports no-access on a `BOOKED` or `CONFIRMED` appointment. The
    appointment becomes `NO_ACCESS`, the work order's `no_access_strikes`
    increments by one, and the work order moves `SCHEDULED` →
    `ACCESS_FAILED`."

    Design: Difficulty/non_linear_state_machine/work_order_no_access_cycle
    """
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 3})
    ctx = setup_work_order_notified(contractor_id=contr["id"])
    appt1 = book_appointment(ctx["work_order"]["id"], slot_date="2026-05-06")
    no_access(appt1["id"], contr["id"])
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["lifecycle_status"] == "ACCESS_FAILED"
    assert wo["no_access_strikes"] == 1
    appt1_after = get_success_data(api_client.get_appointment(appt1["id"], SCHED))
    assert appt1_after["status"] == "NO_ACCESS"


def test_rebook_after_no_access_closes_cycle_with_attempt_two(api):
    """PRD §3.4: "On success, any existing appointment of the work order in
    `BOOKED` or `CONFIRMED` is moved to `SUPERSEDED`, the new appointment
    starts `BOOKED` with `contractor_id` copied from the work order and an
    `attempt_number` one greater than the count of the work order's prior
    non-`SUPERSEDED` appointments, and the work order moves to `SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/work_order_no_access_cycle
    """
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 3})
    ctx = setup_work_order_notified(contractor_id=contr["id"])
    appt1 = book_appointment(ctx["work_order"]["id"], slot_date="2026-05-06")
    no_access(appt1["id"], contr["id"])
    appt2 = book_appointment(ctx["work_order"]["id"], slot_date="2026-05-07")
    assert appt2["status"] == "BOOKED"
    assert appt2["attempt_number"] == 2
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["lifecycle_status"] == "SCHEDULED"
    # Strike threshold is 3; after one strike no case exists.
    cases, meta = validate_paginated(api_client.list_no_access_cases(
        SCHED, params={"work_order_id": ctx["work_order"]["id"]}))
    assert meta["total_count"] == 0


def test_invoice_dispute_resubmit_cycle(api):
    """PRD §3.9: "A dispute moves `SUBMITTED` → `DISPUTED` and records the
    supplied `reason` in `dispute_reason`; the contractor's remedy is to
    correct and resubmit."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_closed(contr["id"])
    inv = create_invoice(contr["id"])
    first = validate_success(api.submit_invoice(inv["id"], fc(contr["id"])))
    # score 10000 -> bonus 2% = 370; no fails -> penalty 0; ACTIVE -> 5% = 925
    assert first["status"] == "SUBMITTED"
    assert first["units_completed"] == 1
    assert first["gross_amount_cents"] == 18500
    assert first["bonus_cents"] == 370
    assert first["penalty_cents"] == 0
    assert first["retainage_cents"] == 925
    assert first["net_amount_cents"] == 17945
    disputed = validate_success(api.dispute_invoice(
        inv["id"], {"reason": "Unit count questioned"}, PM))
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "Unit count questioned"


def test_invoice_resubmit_after_dispute_recomputes_identical(api):
    """PRD §3.9: "Submitting — from `DRAFT`, or again from `DISPUTED` after a
    program-manager dispute — re-runs the full settlement against the submit
    instant and freezes every figure."

    Design: Difficulty/non_linear_state_machine/invoice_dispute_resubmit_cycle
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_closed(contr["id"])
    inv = create_invoice(contr["id"])
    validate_success(api.submit_invoice(inv["id"], fc(contr["id"])))
    validate_success(api.dispute_invoice(inv["id"], {"reason": "Unit count questioned"}, PM))
    resubmitted = validate_success(api.submit_invoice(inv["id"], fc(contr["id"])))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["net_amount_cents"] == 17945
    assert resubmitted["gross_amount_cents"] == 18500
    assert resubmitted["bonus_cents"] == 370


def test_complaint_bench_review_loop_returns_under_review(api):
    """PRD §3.8: "When meter accuracy is in question, the desk orders a bench
    test — legal only while the work order's old meter is `REMOVED`
    (`ERR_METER_NOT_AVAILABLE`) — moving the complaint `UNDER_REVIEW` →
    `BENCH_TEST_ORDERED`, from which the recorded bench test returns it to
    `UNDER_REVIEW` as described above."

    Design: Difficulty/non_linear_state_machine/complaint_bench_review_cycle
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_swapped(contr["id"])
    cmp = setup_filed_complaint(ctx, claimed_bill_cents=19200,
                                baseline_bill_cents=12000, triage=True)
    ordered = get_success_data(api_client.order_bench_test(cmp["id"], CS))
    assert ordered["status"] == "BENCH_TEST_ORDERED"
    bt = get_success_data(api_client.create_bench_test({
        "meter_id": ctx["old_meter"]["id"],
        "work_order_id": ctx["work_order"]["id"],
        "complaint_id": cmp["id"],
        "measured_low_ccf": 1.96,
        "measured_mid_ccf": 19.90,
        "measured_high_ccf": 29.90,
    }, AUDITOR))
    after = get_success_data(api_client.get_complaint(cmp["id"], CS))
    assert after["status"] == "UNDER_REVIEW"
    assert after["bench_test_id"] == bt["id"]


def test_complaint_bench_review_loop_bench_values(api):
    """PRD §3.8: "The `weighted_accuracy_pct` is then twenty percent of
    `accuracy_low_pct` plus thirty percent of `accuracy_mid_pct` plus fifty
    percent of `accuracy_high_pct`, rounded half up to two decimal places. The
    `result` is a two-sided band verdict: `PASS` only when
    `weighted_accuracy_pct` is at least 98.5 and at most 101.5 and
    `accuracy_low_pct` is at least 95.0 and at most 105.0"

    Design: Difficulty/non_linear_state_machine/complaint_bench_review_cycle
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_swapped(contr["id"])
    cmp = setup_filed_complaint(ctx, claimed_bill_cents=19200,
                                baseline_bill_cents=12000, triage=True)
    get_success_data(api_client.order_bench_test(cmp["id"], CS))
    bt = get_success_data(api_client.create_bench_test({
        "meter_id": ctx["old_meter"]["id"],
        "work_order_id": ctx["work_order"]["id"],
        "complaint_id": cmp["id"],
        "measured_low_ccf": 1.96,   # 98.00
        "measured_mid_ccf": 19.90,  # 99.50
        "measured_high_ccf": 29.90, # 99.67 (29.90/30*100 = 99.6667 -> 99.67)
    }, AUDITOR))
    # 0.2*98.00 + 0.3*99.50 + 0.5*99.67 = 19.60 + 29.85 + 49.835 = 99.285 -> 99.29
    assert bt["accuracy_low_pct"] == pytest.approx(98.00, abs=0.005)
    assert bt["weighted_accuracy_pct"] == pytest.approx(99.29, abs=0.005)
    assert bt["result"] == "PASS"
    meter = get_success_data(api_client.get_meter(ctx["old_meter"]["id"], SCHED))
    assert meter["status"] == "BENCH_PASSED"
