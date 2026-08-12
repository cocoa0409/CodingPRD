"""Swap true-up: prorated estimate at swap vs measured at reconcile (PRD 3.5)."""
import pytest

from test_helpers import (
    TEST_DEFAULTS, TEST_USERS, api_client, create_meter, fc, get_success_data,
    post_final_initial_readings, setup_program_wave_contractor,
    setup_work_order_completed_visit, validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def _provisional_ctx():
    """Work order SWAPPED at clock 2026-05-06T09:00Z, account last billed
    1000 CCF at 2026-04-15T00:00Z, avg 2.0 CCF/day, program rate 450."""
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_completed_visit(contr["id"])
    newm = create_meter(technology="AMI")
    return prog, contr, ctx, newm


def test_provisional_trueup_prorated_estimate_at_swap(api):
    """PRD §3.5: "At swap time a provisional true-up is booked into
    `provisional_trueup_cents` using the prorated estimate variant: the whole
    days elapsed between the account's `last_billed_read_at` and the swap's
    clock timestamp are multiplied by the account's `avg_daily_usage_ccf`, the
    product is rounded half up to two decimal places to give the estimated
    usage in CCF, and that usage is multiplied by the program's
    `rate_per_ccf_cents` and rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/trueup_prorated_vs_measured_variants
    """
    prog, contr, ctx, newm = _provisional_ctx()
    resp = api.swap_work_order(ctx["work_order"]["id"], {
        "expected_work_order_version": ctx["work_order"]["version"],
        "new_meter_id": newm["id"],
        "final_read_value": 1060,
        "initial_read_value": 0,
    }, fc(contr["id"]))
    wo = validate_success(resp)
    # 2.0 CCF/day x 21 whole days x 450 cents = 18900 cents
    assert wo["provisional_trueup_cents"] == 18900, (
        f"Expected prorated provisional 18900, got {wo['provisional_trueup_cents']}")
    assert wo["lifecycle_status"] == "SWAPPED"


def test_measured_trueup_and_delta_at_reconcile(api):
    """PRD §3.5: "It books the measured-variant true-up into
    `trueup_amount_cents`: measured usage is the `final_read_value` minus the
    account's `last_billed_read_value`, and that usage multiplied by
    `rate_per_ccf_cents`, rounded half up to whole cents, is the measured
    true-up. The `trueup_delta_cents` booked alongside is the measured true-up
    minus the provisional true-up — a negative delta means the prorated
    estimate overcharged the customer and the difference comes back as a
    credit."

    Design: Difficulty/dual_variant_calc/trueup_prorated_vs_measured_variants
    """
    prog, contr, ctx, newm = _provisional_ctx()
    wo = get_success_data(api_client.swap_work_order(ctx["work_order"]["id"], {
        "expected_work_order_version": ctx["work_order"]["version"],
        "new_meter_id": newm["id"],
        "final_read_value": 1060,
        "initial_read_value": 0,
    }, fc(contr["id"])))
    post_final_initial_readings(wo["id"], ctx["old_meter"]["id"], newm["id"],
                                contr["id"], final_read_value=1060,
                                initial_read_value=0)
    resp = api.reconcile_work_order(
        wo["id"], {"expected_work_order_version": wo["version"]}, fc(contr["id"]))
    rec = validate_success(resp)
    # (1060 - 1000) x 450 = 27000; delta 27000 - 18900 = 8100
    assert rec["trueup_amount_cents"] == 27000, (
        f"Expected measured true-up 27000, got {rec['trueup_amount_cents']}")
    assert rec["trueup_delta_cents"] == 8100, (
        f"Expected delta 8100, got {rec['trueup_delta_cents']}")
    assert rec["lifecycle_status"] == "RECONCILED"
