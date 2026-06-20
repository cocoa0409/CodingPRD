"""Anesthesia coverage-load report: projected vs actual variants diverge.

Difficulty queue: dual_variant_calc / projected_vs_actual_anesthesia_coverage_load.
"""
from test_helpers import validate_success, get_success_data, fixtures
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

BILL = TEST_USERS["billing_analyst_headers"]
ORMGR = TEST_USERS["or_manager_headers"]


def _completed_case_actual_78():
    """One case completed with actual 78 vs scheduled 60, anesthesia assigned, on day 2026-07-15."""
    world, block, case, _ = fixtures.setup_case_in_recovery(
        actual_world_clock="2026-07-01T00:00:00.000Z",
        start_min=480, block_start=480, block_end=600)
    fixtures.complete_case(case["id"], 78)
    return world


def test_projected_coverage_load_uses_scheduled_minutes():
    """PRD §3.14: "The projected variant sums each such case's planned `scheduled_minutes`."
    PRD §3.14: "In both variants the coverage load percentage is 100 multiplied by the
    summed minutes, divided by the solo-coverage cap of 480 minutes (eight prime-time hours),
    rounded half-up to one decimal place."

    One case sched 60 -> projected 100*60/480 = 12.5.

    Design: Difficulty/dual_variant_calc/projected_vs_actual_anesthesia_coverage_load
    """
    world = _completed_case_actual_78()
    anes_id = world["anesthesiologist"]["id"]
    resp = api_client.get_coverage_load(
        anes_id, BILL, params={"service_date": "2026-07-15", "basis": "PROJECTED"})
    data = validate_success(resp, 200)
    assert data["coverage_load_pct"] == 12.5, data["coverage_load_pct"]


def test_actual_coverage_load_uses_actual_minutes_and_diverges():
    """PRD §3.14: "The actual variant instead walks the same cases in chronological order —
    `start_min` ascending, then `created_at` ascending — and, for each, uses `actual_minutes`
    if the case is `COMPLETED` and `scheduled_minutes` otherwise; a not-yet-completed case
    thus contributes its planned footprint as a placeholder."
    PRD §3.14: "The two variants diverge whenever a completed case ran over or under its
    scheduled time."

    Completed case actual 78 -> actual 100*78/480 = 16.25 -> 16.3 (half-up to 1 dp), which
    diverges from the 12.5 projected load.

    Design: Difficulty/dual_variant_calc/projected_vs_actual_anesthesia_coverage_load
    """
    world = _completed_case_actual_78()
    anes_id = world["anesthesiologist"]["id"]
    proj = validate_success(api_client.get_coverage_load(
        anes_id, BILL, params={"service_date": "2026-07-15", "basis": "PROJECTED"}), 200)
    act = validate_success(api_client.get_coverage_load(
        anes_id, BILL, params={"service_date": "2026-07-15", "basis": "ACTUAL"}), 200)
    assert act["coverage_load_pct"] == 16.3, act["coverage_load_pct"]
    assert proj["coverage_load_pct"] != act["coverage_load_pct"]
