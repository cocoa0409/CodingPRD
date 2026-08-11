"""Bench test weighted accuracy: pinned rounding order (PRD 3.8)."""
import pytest

from test_helpers import (
    TEST_USERS, api_client, get_success_data, setup_program_wave_contractor,
    setup_work_order_swapped, validate_success,
)

AUDITOR = TEST_USERS["quality_auditor_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def _removed_meter_ctx():
    prog, wave, contr = setup_program_wave_contractor()
    ctx = setup_work_order_swapped(contr["id"])
    return contr, ctx


def test_per_flow_rounding_before_weighting(api):
    """PRD §3.8: "Computation is synchronous at creation, stamped with
    `tested_at` from the logical clock, and follows a pinned rounding order —
    each per-flow accuracy is rounded first, and only then are the rounded
    figures weighted. The known test volumes are 2 CCF at low flow, 20 CCF at
    mid flow, and 30 CCF at high flow: `accuracy_low_pct` is the measured low
    volume divided by 2, times one hundred, rounded half up to two decimal
    places; `accuracy_mid_pct` the same against 20; `accuracy_high_pct` the
    same against 30. The `weighted_accuracy_pct` is then twenty percent of
    `accuracy_low_pct` plus thirty percent of `accuracy_mid_pct` plus fifty
    percent of `accuracy_high_pct`, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/bench_weighted_accuracy_rounding_order
    """
    contr, ctx = _removed_meter_ctx()
    resp = api.create_bench_test({
        "meter_id": ctx["old_meter"]["id"],
        "work_order_id": ctx["work_order"]["id"],
        "measured_low_ccf": 1.8885,   # /2 x 100 = 94.425 -> 94.43 half-up
        "measured_mid_ccf": 20.0,     # 100.00
        "measured_high_ccf": 29.9865, # /30 x 100 = 99.955 -> 99.96 half-up
    }, AUDITOR)
    bt = validate_success(resp, expected_status=201)
    assert bt["accuracy_low_pct"] == pytest.approx(94.43, abs=0.005)
    assert bt["accuracy_mid_pct"] == pytest.approx(100.00, abs=0.005)
    assert bt["accuracy_high_pct"] == pytest.approx(99.96, abs=0.005)
    # Round-first: 0.2*94.43 + 0.3*100.00 + 0.5*99.96 = 98.866 -> 98.87
    # (round-last on raw flows would publish 98.86)
    assert bt["weighted_accuracy_pct"] == pytest.approx(98.87, abs=0.005)


def test_rounding_order_drives_result_and_meter_status(api):
    """PRD §3.8: "The `result` is a two-sided band verdict: `PASS` only when
    `weighted_accuracy_pct` is at least 98.5 and at most 101.5 and
    `accuracy_low_pct` is at least 95.0 and at most 105.0; anything outside
    either bound is a `FAIL`, so over-registration fails just as
    under-registration does. The verdict moves the meter to `BENCH_PASSED` or
    `BENCH_FAILED`"

    Design: Difficulty/combinatorial_formula/bench_weighted_accuracy_rounding_order
    """
    contr, ctx = _removed_meter_ctx()
    bt = validate_success(api.create_bench_test({
        "meter_id": ctx["old_meter"]["id"],
        "work_order_id": ctx["work_order"]["id"],
        "measured_low_ccf": 1.8885,
        "measured_mid_ccf": 20.0,
        "measured_high_ccf": 29.9865,
    }, AUDITOR), expected_status=201)
    # weighted 98.87 is inside [98.5, 101.5] but low 94.43 < 95.0 floor
    assert bt["result"] == "FAIL"
    meter = get_success_data(api_client.get_meter(ctx["old_meter"]["id"], SCHED))
    assert meter["status"] == "BENCH_FAILED"
