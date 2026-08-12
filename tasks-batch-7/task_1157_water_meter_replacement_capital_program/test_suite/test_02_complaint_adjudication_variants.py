"""Complaint adjudication: REGISTRATION_ERROR vs GOODWILL_TIERED (PRD 3.8)."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, create_complaint_payload, fc, get_success_data,
    setup_program_wave_contractor, setup_work_order_swapped, validate_success,
)

CS = TEST_USERS["customer_service_headers"]
AUDITOR = TEST_USERS["quality_auditor_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def _complaint_under_review(contr):
    """Swapped work order + complaint claimed 16800 / baseline 12000
    (variance 40.00), triaged to UNDER_REVIEW. Returns (ctx, complaint)."""
    ctx = setup_work_order_swapped(contr["id"])
    cmp = get_success_data(api_client.create_complaint(
        create_complaint_payload(ctx["account"]["id"], ctx["work_order"]["id"],
                                 claimed_bill_cents=16800,
                                 baseline_bill_cents=12000), CS))
    cmp = get_success_data(api_client.triage_complaint(cmp["id"], CS))
    return ctx, cmp


def test_goodwill_tiered_adjustment_without_fail_bench(api):
    """PRD §3.8: "Otherwise the `GOODWILL_TIERED` variant applies: the excess
    of `claimed_bill_cents` over `baseline_bill_cents` is credited at a tiered
    rate on the variance — ten percent when the variance is at least 25 and
    below 50, twenty percent when at least 50 and below 100, thirty percent
    when at least 100 — with the product rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/complaint_registration_error_vs_goodwill_variants
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx, cmp = _complaint_under_review(contr)
    resp = api.adjudicate_complaint(cmp["id"], {"decision": "ADJUSTED"}, CS)
    data = validate_success(resp)
    # excess 4800 x 0.10 = 480
    assert data["adjustment_cents"] == 480, (
        f"Expected GOODWILL_TIERED adjustment 480, got {data['adjustment_cents']}")
    assert data["adjudication_variant"] == "GOODWILL_TIERED"
    assert data["status"] == "ADJUSTED"
    # Last open complaint closed -> hold released
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["hold_status"] == "CLEAR"


def test_registration_error_adjustment_with_fail_bench(api):
    """PRD §3.8: "if a bench test linked to the complaint recorded `FAIL`, the
    `REGISTRATION_ERROR` variant applies — the claimed bill is multiplied by
    one hundred, divided by the test's `weighted_accuracy_pct`, and rounded
    half up to whole cents to recover what the bill would have been at perfect
    registration, and the adjustment is the claimed bill minus that amount."

    Design: Difficulty/dual_variant_calc/complaint_registration_error_vs_goodwill_variants
    """
    prog, wave, contr = setup_program_wave_contractor()
    ctx, cmp = _complaint_under_review(contr)
    get_success_data(api_client.order_bench_test(cmp["id"], CS))
    # Over-registering meter: flows 105.00 / 105.00 / 105.00 -> weighted 105.00 FAIL
    bt = get_success_data(api_client.create_bench_test({
        "meter_id": ctx["old_meter"]["id"],
        "work_order_id": ctx["work_order"]["id"],
        "complaint_id": cmp["id"],
        "measured_low_ccf": 2.10,
        "measured_mid_ccf": 21.00,
        "measured_high_ccf": 31.50,
    }, AUDITOR))
    assert bt["weighted_accuracy_pct"] == pytest.approx(105.00, abs=0.005)
    assert bt["result"] == "FAIL"
    resp = api.adjudicate_complaint(cmp["id"], {"decision": "ADJUSTED"}, CS)
    data = validate_success(resp)
    # 16800 - round(16800 x 100 / 105.00) = 16800 - 16000 = 800
    assert data["adjustment_cents"] == 800, (
        f"Expected REGISTRATION_ERROR adjustment 800, got {data['adjustment_cents']}")
    assert data["adjudication_variant"] == "REGISTRATION_ERROR"
    assert data["status"] == "ADJUSTED"
    assert data["bench_test_id"] == bt["id"]
    wo = get_success_data(api_client.get_work_order(ctx["work_order"]["id"], SCHED))
    assert wo["hold_status"] == "CLEAR"
