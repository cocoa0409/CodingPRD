"""Corner coverage — calculations: budget aggregation, completion report,
complaint variance boundary, bench low-flow floor, comm window filtering,
invoice penalty cap (PRD 3.1, 3.6, 3.8, 3.9)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, create_complaint_payload,
    create_invoice, fc, get_success_data, record_for_cause_fail,
    register_endpoint, ingest_reads, setup_program_wave_contractor,
    setup_work_order_created, setup_work_order_qa_review,
    setup_work_order_reconciled, setup_work_order_swapped, submit_rework,
    validate_error, validate_paginated, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]
CS = TEST_USERS["customer_service_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]
AMI = TEST_USERS["ami_operator_headers"]


def test_budget_position_aggregation(api):
    """PRD §3.1: "`budget_committed_cents` is the sum of
    `committed_amount_cents` over the program's work orders whose
    `lifecycle_status` is neither `CLOSED` nor `CANCELLED` (a work order
    belongs to the program through its wave)."
    PRD §3.3: "each assignment reprices the work order's
    `committed_amount_cents` to the contractor's `unit_price_cents`,
    recomputes the program budget, and bumps the work order's `version`."

    Design: Corner/calculations/budget_position_aggregation
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    from test_helpers import create_installed_account, create_work_order, assign_contractor
    acct1, _ = create_installed_account()
    wo1 = create_work_order(wave["id"], acct1["id"])
    assign_contractor(wo1["id"], contr["id"])  # repriced 20000 -> 18500
    acct2, _ = create_installed_account()
    create_work_order(wave["id"], acct2["id"])  # stays at allowance 20000
    p = get_success_data(api_client.get_program(prog["id"], PM))
    assert p["budget_committed_cents"] == 38500
    assert p["budget_spent_cents"] == 0
    assert p["budget_available_cents"] == 961500
    assert p["budget_posture"] == "FUNDED"


def test_completion_report_computed_read(api):
    """PRD §3.1: "A program-manager-only completion report returns
    `completed_meter_count`, `target_meter_count`, the `completion_pct`
    derived from completed against target meters, the four budget figures
    `budget_total_cents`, `budget_committed_cents`, `budget_spent_cents`, and
    `budget_available_cents`, the current `budget_posture`, and two forecast
    dates computed in different ways."

    Design: Corner/calculations/completion_report_computed_read
    """
    prog, wave, contr = setup_program_wave_contractor(
        budget_total_cents=1000000, target_meter_count=100)
    from test_helpers import create_installed_account, create_work_order
    acct, _ = create_installed_account()
    create_work_order(wave["id"], acct["id"])
    report = validate_success(api.get_completion_report(prog["id"], PM))
    assert report["completed_meter_count"] == 0
    assert report["target_meter_count"] == 100
    assert report["completion_pct"] == 0
    assert report["budget_total_cents"] == 1000000
    assert report["budget_committed_cents"] == 20000
    assert report["budget_available_cents"] == 980000
    assert report["budget_posture"] == "FUNDED"
    assert "forecast_run_rate_date" in report
    assert "forecast_stage_weighted_date" in report


def _two_swapped_work_orders(prog, wave, contr):
    ctxA = setup_work_order_swapped(contr["id"], program=prog, wave=wave)
    ctxB = setup_work_order_swapped(contr["id"], program=prog, wave=wave,
                                    slot_date="2026-05-07",
                                    clock="2026-05-07T09:00:00Z")
    return ctxA, ctxB


def test_complaint_variance_boundary_filing(api):
    """PRD §3.8: "At filing the `variance_pct` is computed as the claimed bill
    minus the baseline, divided by the baseline, times one hundred, rounded
    half up to two decimal places, and a variance below 25 percent is refused
    with `ERR_COMPLAINT_VARIANCE_BELOW_THRESHOLD`."

    Design: Corner/calculations/complaint_variance_boundary_filing
    """
    prog, wave, contr = setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 3})
    ctxA, ctxB = _two_swapped_work_orders(prog, wave, contr)
    # Exactly 25.00: accepted.
    resp = api.create_complaint(create_complaint_payload(
        ctxA["account"]["id"], ctxA["work_order"]["id"],
        claimed_bill_cents=15000, baseline_bill_cents=12000), CS)
    cmp = validate_success(resp, expected_status=201)
    assert cmp["variance_pct"] == pytest.approx(25.0, abs=0.005)
    assert cmp["status"] == "FILED"
    # 24.99 (one cent less): rejected.
    resp = api.create_complaint(create_complaint_payload(
        ctxB["account"]["id"], ctxB["work_order"]["id"],
        claimed_bill_cents=14999, baseline_bill_cents=12000), CS)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_VARIANCE_BELOW_THRESHOLD.value)


def test_bench_low_flow_floor_isolated(api):
    """PRD §3.8: "The `result` is a two-sided band verdict: `PASS` only when
    `weighted_accuracy_pct` is at least 98.5 and at most 101.5 and
    `accuracy_low_pct` is at least 95.0 and at most 105.0; anything outside
    either bound is a `FAIL`, so over-registration fails just as
    under-registration does. The verdict moves the meter to `BENCH_PASSED` or
    `BENCH_FAILED`"

    Design: Corner/calculations/bench_low_flow_floor_isolated
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_swapped(contr["id"])
    bt = validate_success(api.create_bench_test({
        "meter_id": ctx["old_meter"]["id"],
        "work_order_id": ctx["work_order"]["id"],
        "measured_low_ccf": 1.89,    # 94.50 < 95.0 floor
        "measured_mid_ccf": 20.0,    # 100.00
        "measured_high_ccf": 30.0,   # 100.00
    }, AUDITOR), expected_status=201)
    assert bt["accuracy_low_pct"] == pytest.approx(94.50, abs=0.005)
    assert bt["accuracy_mid_pct"] == pytest.approx(100.00, abs=0.005)
    assert bt["accuracy_high_pct"] == pytest.approx(100.00, abs=0.005)
    # Weighted 98.90 is inside [98.5, 101.5], yet the low-flow floor binds.
    assert bt["weighted_accuracy_pct"] == pytest.approx(98.90, abs=0.005)
    assert bt["result"] == "FAIL"
    meter = get_success_data(api_client.get_meter(ctx["old_meter"]["id"], SCHED))
    assert meter["status"] == "BENCH_FAILED"


def test_comm_window_excludes_late_reads(api):
    """PRD §3.6: "Verification evaluates a fixed threshold over the
    seventy-two-hour window that opens at `registered_at`: reads whose
    `read_at` falls no earlier than `registered_at` and no later than
    seventy-two hours after it — both bounds inclusive — count toward the
    window."
    And: "A failing verification moves the registration `REGISTERED` →
    `COMM_FAILED` with no work-order effect."

    Design: Corner/calculations/comm_window_excludes_late_reads
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_reconciled(contr["id"])
    # Registration stamped at the current clock 2026-05-06T09:00:00Z; the
    # window ends 2026-05-09T09:00:00Z.
    reg = register_endpoint(ctx["work_order"]["id"])
    ingest_reads(reg["id"], 3, rssi_dbm=-90,
                 read_ats=["2026-05-06T12:00:00Z", "2026-05-07T06:00:00Z",
                           "2026-05-08T06:00:00Z"])
    # Two reads past the 72h window: counted by the raw counter, excluded by
    # the window rule.
    ingest_reads(reg["id"], 2, rssi_dbm=-85,
                 read_ats=["2026-05-10T12:00:00Z", "2026-05-10T13:00:00Z"])
    data = validate_success(api.verify_endpoint_registration(reg["id"], AMI))
    assert data["reads_received_count"] == 5
    assert data["status"] == "COMM_FAILED"
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["lifecycle_status"] == "RECONCILED"


def test_invoice_penalty_cap_bound(api):
    """PRD §3.9: "The penalty counts the contractor's `FAIL` audits whose
    `recorded_at` falls in the same half-open period: `penalty_cents` is the
    smaller of that failure count times one percent of the gross (rounded half
    up to whole cents) and ten percent of the gross (rounded half up to whole
    cents). The `retainage_cents` is ten percent of the gross, rounded half up
    to whole cents, when the contractor is `SUSPENDED` at submit, and five
    percent of the gross otherwise. The `net_amount_cents` is then the gross
    plus the bonus minus the penalty minus the retainage."

    Design: Corner/calculations/invoice_penalty_cap_bound
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_qa_review(contr["id"])
    wo_id = ctx["work_order"]["id"]
    for _ in range(11):
        record_for_cause_fail(wo_id, contr["id"])
        submit_rework(wo_id, contr["id"])
    # Drain any PENDING audits (e.g. auto-created SAMPLED ones) so close-out
    # is not gated on a pending audit; record them PASS (no FAIL added).
    pending, meta = validate_paginated(api_client.list_quality_audits(
        AUDITOR, params={"work_order_id": wo_id, "result_status": "PENDING"}))
    for a in pending:
        get_success_data(api_client.record_quality_audit(
            a["id"], {"checks_total": 10, "checks_passed": 10,
                      "defects_found": 0}, AUDITOR))
    c = get_success_data(api_client.get_contractor(contr["id"], PM))
    assert c["quality_score_bp"] == 5600  # 10000 - 11 x 400
    assert c["status"] == "SUSPENDED"
    get_success_data(api_client.close_work_order(wo_id, SCHED))
    inv = create_invoice(contr["id"])
    data = validate_success(api.submit_invoice(inv["id"], fc(contr["id"])))
    assert data["units_completed"] == 1
    assert data["gross_amount_cents"] == 18500
    # 11 x round(18500 x 0.01) = 2035, but the 10% cap 1850 binds.
    assert data["penalty_cents"] == 1850
    assert data["retainage_cents"] == 1850  # SUSPENDED -> 10%
    assert data["bonus_cents"] == 0         # 5600 < 9800
    assert data["net_amount_cents"] == 14800
