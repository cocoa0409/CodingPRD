"""Cross-entity state dependencies: swap needs a COMPLETED appointment;
ADJUSTED with high variance needs a linked FAIL bench test (PRD 3.5, 3.8)."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, complete_appointment, create_meter,
    fc, get_success_data, setup_filed_complaint, setup_program_wave_contractor,
    setup_work_order_scheduled, setup_work_order_swapped, validate_error,
    validate_success,
)

SCHED = TEST_USERS["scheduler_headers"]
CS = TEST_USERS["customer_service_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]


def test_swap_rejected_while_appointment_booked(api):
    """PRD §3.5: "The assigned `FieldContractor` records the swap on a
    `SCHEDULED` work order whose `hold_status` is `CLEAR` and which has an
    appointment in `COMPLETED` status"

    Design: Difficulty/cross_entity_state_dependency/swap_requires_completed_appointment
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_scheduled(contr["id"])
    newm = create_meter(technology="AMI")
    wo = ctx["work_order"]
    resp = api.swap_work_order(wo["id"], {
        "expected_work_order_version": wo["version"],
        "new_meter_id": newm["id"],
        "final_read_value": 1060,
        "initial_read_value": 0,
    }, fc(contr["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api_client.get_work_order(wo["id"], SCHED))
    assert after["lifecycle_status"] == "SCHEDULED"


def test_swap_succeeds_after_appointment_completed(api):
    """PRD §3.5: "The swap then lands its full cascade at once: the old meter
    moves `INSTALLED` → `REMOVED` with its `service_account_id` cleared; the
    new meter moves `IN_STOCK` → `INSTALLED` with `service_account_id` set to
    the account and `installed_read_value` set to the declared
    `initial_read_value`; the work order records `new_meter_id`; the account
    moves `IN_PROGRAM` → `REPLACED`; and the work order moves `SCHEDULED` →
    `SWAPPED`."

    Design: Difficulty/cross_entity_state_dependency/swap_requires_completed_appointment
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_scheduled(contr["id"])
    complete_appointment(ctx["appointment"]["id"], contr["id"])
    newm = create_meter(technology="AMI")
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    resp = api.swap_work_order(wo["id"], {
        "expected_work_order_version": wo["version"],
        "new_meter_id": newm["id"],
        "final_read_value": 1060,
        "initial_read_value": 0,
    }, fc(contr["id"]))
    data = validate_success(resp)
    assert data["lifecycle_status"] == "SWAPPED"
    assert data["new_meter_id"] == newm["id"]


def _high_variance_complaint_with_pass_bench(contr):
    ctx = setup_work_order_swapped(contr["id"])
    cmp = setup_filed_complaint(ctx, claimed_bill_cents=19200,
                                baseline_bill_cents=12000, triage=True)
    get_success_data(api_client.order_bench_test(cmp["id"], CS))
    bt = get_success_data(api_client.create_bench_test({
        "meter_id": ctx["old_meter"]["id"],
        "work_order_id": ctx["work_order"]["id"],
        "complaint_id": cmp["id"],
        "measured_low_ccf": 1.96,   # PASS band (weighted 99.29)
        "measured_mid_ccf": 19.90,
        "measured_high_ccf": 29.90,
    }, AUDITOR))
    return ctx, cmp, bt


def test_adjusted_rejected_with_pass_bench_at_high_variance(api):
    """PRD §3.8: "adjudicating `ADJUSTED` on a complaint whose `variance_pct`
    is 50 or greater requires a linked `FAIL` bench test, failing with
    `ERR_BENCH_TEST_REQUIRED` otherwise."

    Design: Difficulty/cross_entity_state_dependency/complaint_adjusted_requires_fail_bench
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx, cmp, bt = _high_variance_complaint_with_pass_bench(contr)
    assert bt["result"] == "PASS"
    assert cmp["variance_pct"] == pytest.approx(60.0, abs=0.005)
    resp = api.adjudicate_complaint(cmp["id"], {"decision": "ADJUSTED"}, CS)
    validate_error(resp, ApiErrorId.ERR_BENCH_TEST_REQUIRED.value)
    after = get_success_data(api_client.get_complaint(cmp["id"], CS))
    assert after["status"] == "UNDER_REVIEW"


def test_denied_succeeds_and_releases_hold(api):
    """PRD §3.8: "A denial simply moves the complaint to `DENIED`." And:
    "`ADJUSTED`, `DENIED`, and `WITHDRAWN` are all terminal, and each releases
    the hold dimension: when a complaint reaching one of those states was the
    work order's last open complaint, `hold_status` moves `ON_HOLD` →
    `CLEAR`, unblocking booking, swap, and close."

    Design: Difficulty/cross_entity_state_dependency/complaint_adjusted_requires_fail_bench
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx, cmp, bt = _high_variance_complaint_with_pass_bench(contr)
    # Hold was flipped ON_HOLD at filing
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["hold_status"] == "ON_HOLD"
    resp = api.adjudicate_complaint(cmp["id"], {"decision": "DENIED"}, CS)
    data = validate_success(resp)
    assert data["status"] == "DENIED"
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["hold_status"] == "CLEAR"
