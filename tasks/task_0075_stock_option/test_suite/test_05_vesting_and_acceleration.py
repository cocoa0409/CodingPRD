"""Vesting algorithms, performance gating, and acceleration (PRD §3.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    SECONDS_PER_DAY,
    TEST_USERS,
    accelerate_vesting_payload,
    advance_clock_by_days,
    advance_clock_by_months,
    create_and_activate_plan,
    create_and_open_batch,
    create_change_of_control,
    create_grant_and_drive_to_live,
    register_grantee,
    setup_live_grant_with_open_window,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Cliff: before, at, after (PRD §3.5)
# ---------------------------------------------------------------------------
def test_anniversary_zero_vested_before_cliff(api, plan_admin_headers):
    """PRD §3.5: "If the elapsed-month count is strictly less than
    cliff_months, the unconditional vested figure is zero — nothing has
    cleared the cliff."
    """
    setup = setup_live_grant_with_open_window(
        cliff_months=12, vesting_total_months=48, vesting_period_months=3,
        quantity=1200,
        advance_clock_months_after_grant=6,
    )
    g = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    assert g["vested_quantity"] == 0


def test_anniversary_vests_lump_sum_at_cliff_plus_period(api,
                                                          plan_admin_headers):
    """PRD §3.5: "For ANNIVERSARY_BATCH, tranches vest in lump sums at
    each vesting_period_months boundary after the cliff."

    Inputs: quantity=1200, cliff=12, period=3, total=48, algorithm=
    ANNIVERSARY_BATCH. At cliff+3 months: completed_periods = floor(3/3)+1
    = 2 (cliff and first period). Vested = floor(1200*2*3/48) = 150.

    Note: scaffold difficulty design Rule 1 pins 150 at cliff+3mo.
    """
    setup = setup_live_grant_with_open_window(
        vesting_algorithm="ANNIVERSARY_BATCH",
        cliff_months=12, vesting_total_months=48, vesting_period_months=3,
        quantity=1200,
        advance_clock_months_after_grant=15,
    )
    g = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    assert g["vested_quantity"] == 150


def test_continuous_daily_linear_after_cliff(api, plan_admin_headers):
    """PRD §3.5: "For CONTINUOUS_DAILY, vesting accrues linearly by day
    after the cliff. The constant DAYS_PER_MONTH is fixed at 30..."

    Inputs: quantity=1200, cliff=12, total=48, algorithm=CONTINUOUS_DAILY.
    Total vesting days = (48 - 12)*30 = 1080. At cliff+3mo (= 90 days
    after cliff): vested = floor(1200*90/1080) = 100.

    Scaffold difficulty design Rule 1 pins 100 at cliff+3mo.
    """
    setup = setup_live_grant_with_open_window(
        vesting_algorithm="CONTINUOUS_DAILY",
        cliff_months=12, vesting_total_months=48, vesting_period_months=3,
        quantity=1200,
        advance_clock_months_after_grant=15,
    )
    g = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    assert g["vested_quantity"] == 100


def test_full_vesting_at_total_months(api, plan_admin_headers):
    """PRD §3.5: "The grant's vested_quantity is the smaller of quantity
    and the larger of the gated figure and the acceleration sum."

    After vesting_total_months elapsed, vested_quantity must equal quantity.
    """
    setup = setup_live_grant_with_open_window(
        cliff_months=0, vesting_total_months=12, vesting_period_months=3,
        quantity=400,
        advance_clock_months_after_grant=12,
    )
    g = validate_success(api.get_grant(
        setup["grant"]["id"], plan_admin_headers,
    ), expected_status=200)
    assert g["vested_quantity"] == 400


# ---------------------------------------------------------------------------
# Performance gating (PRD §3.5)
# ---------------------------------------------------------------------------
def test_performance_required_gates_vesting_until_attest(api,
                                                         plan_admin_headers):
    """PRD §3.5: "If the batch's performance_condition_required is true
    and Grant.performance_attested_at is null, the gated vested figure
    is forced to zero — the performance gate suppresses unconditional
    vesting until a PlanAdministrator attests..."
    """
    plan = create_and_activate_plan()
    batch = create_and_open_batch(
        plan["id"], performance_condition_required=True,
    )
    grantee = register_grantee(plan["id"])
    grant = create_grant_and_drive_to_live(plan, batch, grantee)
    advance_clock_by_months(plan["id"], 24)
    g_before = validate_success(api.get_grant(
        grant["id"], plan_admin_headers,
    ), expected_status=200)
    assert g_before["vested_quantity"] == 0
    # Attest performance.
    validate_success(api.attest_performance(
        grant["id"], plan_admin_headers,
    ), expected_status=200)
    g_after = validate_success(api.get_grant(
        grant["id"], plan_admin_headers,
    ), expected_status=200)
    assert g_after["vested_quantity"] > 0


# ---------------------------------------------------------------------------
# Acceleration (PRD §3.5)
# ---------------------------------------------------------------------------
def test_acceleration_requires_qualifying_event(api, plan_admin_headers):
    """PRD §3.5: "...takes a corporate_event_id referencing an existing
    event of type CHANGE_OF_CONTROL or IPO (failure to reference such an
    event yields ERR_INVALID_TIME_INTERVAL)..."
    """
    from test_helpers import create_blackout
    setup = setup_live_grant_with_open_window()
    plan, grant = setup["plan"], setup["grant"]
    # Create an EARNINGS_BLACKOUT to use as a non-qualifying event.
    import datetime as _dt
    base = _dt.datetime.fromisoformat(
        plan["current_clock_ts"].replace("Z", "+00:00"),
    )
    # Blackout far in the future so it doesn't overlap any existing window.
    eff = (base + _dt.timedelta(days=400)).isoformat().replace("+00:00", "Z")
    end = (base + _dt.timedelta(days=401)).isoformat().replace("+00:00", "Z")
    non_qualifying = create_blackout(plan["id"], eff, end)
    res = api.accelerate_vesting(
        grant["id"], accelerate_vesting_payload(non_qualifying["id"]),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_INTERVAL.value)


def test_acceleration_emits_vesting_record(api, plan_admin_headers):
    """PRD §3.5: "writes a VestingRecord whose tranche_quantity is
    determined by acceleration policy (typically equal to the grant's
    remaining outstanding_quantity), ... and whose cause is the
    corresponding ACCELERATION_* value."
    """
    setup = setup_live_grant_with_open_window()
    plan, grant = setup["plan"], setup["grant"]
    coc = create_change_of_control(plan["id"], plan["current_clock_ts"])
    res = api.accelerate_vesting(
        grant["id"], accelerate_vesting_payload(coc["id"]),
        plan_admin_headers,
    )
    validate_success(res, expected_status=200)
    records_res = api.list_vesting_records(
        grant["id"], plan_admin_headers,
    )
    records = records_res.json()["data"]
    accel_records = [
        r for r in records if r["cause"] == "ACCELERATION_CHANGE_OF_CONTROL"
    ]
    assert len(accel_records) == 1
