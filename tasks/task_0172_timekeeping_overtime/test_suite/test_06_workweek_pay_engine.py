"""Workweek pay engine — FED vs CA, federal weekly OT, CA daily OT/DT.

Covers PRD §3.6 (Finalization, the Workweek, and the Pay Engine).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_workweek,
    clock_set,
    create_employee,
    create_shift,
    finalize_all_shifts,
    finalize_shift,
    get_workweek,
    make_employee_headers,
    post_punch,
    setup_finalized_week,
    TEST_DEFAULTS,
    validate_success,
)


def setup_module(module):
    clock_set(TEST_DEFAULTS["WORKWEEK_ANCHOR"])


# ===========================================================================
# Federal-only: weekly OT above 40 hours — PRD §3.6
# ===========================================================================
class TestFederalWeeklyOvertime:

    def test_fed_jurisdiction_45_hours_yields_5_ot(self, api):
        """PRD §3.6: "When the employee's `jurisdiction` is `FED`, no
        daily carve happens: the day's full total goes into the
        daily-regular bucket ... `overtime_hours` for the workweek is
        the sum of federal weekly overtime accumulated".

        Claim: 13+8+8+8+8 = 45h FED → regular 40, overtime 5, DT 0.
        """
        state = setup_finalized_week(
            daily_hours=[13.0, 8.0, 8.0, 8.0, 8.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        assert_workweek(ww)
        assert ww["total_hours"] == pytest.approx(45.0, abs=1e-9), (
            f"total_hours expected 45.0, got {ww['total_hours']}"
        )
        assert ww["regular_hours"] == pytest.approx(40.0, abs=1e-9)
        assert ww["overtime_hours"] == pytest.approx(5.0, abs=1e-9)
        assert ww["double_time_hours"] == pytest.approx(0.0, abs=1e-9)
        # gross = 40*2000 + 5*2000*1.5 = 80000 + 15000 = 95000.
        assert ww["gross_pay_cents"] == 95000

    def test_fed_exactly_40_hours_no_overtime(self, api):
        """PRD §3.6: "the amount that fits under the remaining capacity
        to 40 hours (40 minus cumulative_regular_so_far, floored at
        zero) is classified as regular, and the remainder of the day's
        daily-regular bucket spills into federal weekly overtime."

        Claim: 5x8.0h FED → 40 regular, 0 OT, 0 DT.
        """
        state = setup_finalized_week(
            daily_hours=[8.0, 8.0, 8.0, 8.0, 8.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        assert ww["total_hours"] == pytest.approx(40.0, abs=1e-9)
        assert ww["regular_hours"] == pytest.approx(40.0, abs=1e-9)
        assert ww["overtime_hours"] == pytest.approx(0.0, abs=1e-9)
        assert ww["double_time_hours"] == pytest.approx(0.0, abs=1e-9)
        # 40 * 2000 = 80000 cents.
        assert ww["gross_pay_cents"] == 80000


# ===========================================================================
# CA daily buckets — PRD §3.6
# ===========================================================================
class TestCaliforniaDailyBuckets:

    def test_ca_daily_ot_carves_8_to_12_hours(self, api):
        """PRD §3.6: "the daily-overtime bucket is the part of the day's
        hours above 8 but at or below 12 (so it can be at most 4 hours
        per day)".

        Claim: 13+8+8+8+8 = 45h CA → 1h daily-DT, 4h daily-OT, 40 regular.
        """
        state = setup_finalized_week(
            daily_hours=[13.0, 8.0, 8.0, 8.0, 8.0],
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        assert ww["total_hours"] == pytest.approx(45.0, abs=1e-9)
        assert ww["regular_hours"] == pytest.approx(40.0, abs=1e-9)
        assert ww["overtime_hours"] == pytest.approx(4.0, abs=1e-9)
        assert ww["double_time_hours"] == pytest.approx(1.0, abs=1e-9)
        # 40 * 2000 + 4 * 2000 * 1.5 + 1 * 2000 * 2.0
        # = 80000 + 12000 + 4000 = 96000.
        assert ww["gross_pay_cents"] == 96000

    def test_ca_daily_dt_above_12_hours(self, api):
        """PRD §3.6: "the daily-doubletime bucket is the part of the
        day's hours strictly above 12".

        Claim: a single 14h day in CA → 8 regular, 4 OT, 2 DT.
        """
        state = setup_finalized_week(
            daily_hours=[14.0],
            jurisdiction="CA",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        assert ww["total_hours"] == pytest.approx(14.0, abs=1e-9)
        assert ww["regular_hours"] == pytest.approx(8.0, abs=1e-9)
        assert ww["overtime_hours"] == pytest.approx(4.0, abs=1e-9)
        assert ww["double_time_hours"] == pytest.approx(2.0, abs=1e-9)
        # 8*2000 + 4*2000*1.5 + 2*2000*2.0 = 16000 + 12000 + 8000 = 36000.
        assert ww["gross_pay_cents"] == 36000

    def test_fed_no_daily_dt(self, api):
        """PRD §3.6: "the daily-overtime and daily-doubletime buckets
        are zero for every day" when jurisdiction is FED.

        Claim: 14h day FED → DT=0, weekly OT picks up the over-40 only.
        """
        state = setup_finalized_week(
            daily_hours=[14.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        ww = state["workweek"]
        # 14h total under FED — all 14 in daily-regular bucket, weekly
        # OT applies only after 40h cumulative; since this is the only
        # day, all 14 are classified as regular.
        assert ww["total_hours"] == pytest.approx(14.0, abs=1e-9)
        assert ww["regular_hours"] == pytest.approx(14.0, abs=1e-9)
        assert ww["overtime_hours"] == pytest.approx(0.0, abs=1e-9)
        assert ww["double_time_hours"] == pytest.approx(0.0, abs=1e-9)


# ===========================================================================
# Workweek payroll status — PRD §3.6
# ===========================================================================
class TestWorkweekPayrollStatus:

    def test_workweek_auto_posts_when_all_shifts_finalized(self, api):
        """PRD §3.6: "if every sibling shift in the workweek is now
        `FINALIZED`, the workweek transitions `OPEN → POSTED`
        automatically."
        """
        state = setup_finalized_week(
            daily_hours=[8.0, 8.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        assert state["workweek"]["payroll_status"] == "POSTED"

    def test_finalize_pre_post_status_is_open(self, api):
        """PRD §3.6: workweek starts OPEN; the auto-transition only
        fires when every sibling shift has reached FINALIZED.

        Claim: build TWO shifts, finalize ONLY one → workweek remains
        OPEN (since the second shift is still CLOSED).
        """
        from test_helpers import setup_week_with_shifts
        built = setup_week_with_shifts(
            daily_hours=[8.0, 8.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        finalize_shift(built["shifts"][0]["id"])
        ww = get_workweek(built["shifts"][0]["workweek_id"])
        assert ww["payroll_status"] == "OPEN", (
            f"expected OPEN until ALL siblings FINALIZED, got "
            f"{ww['payroll_status']}"
        )

    def test_workweek_lock_transitions_posted_to_locked(self, api):
        """PRD §3.6: "A payroll administrator locks a workweek when its
        `payroll_status` is `POSTED` ... the transition `POSTED →
        LOCKED` freezes the workweek".

        Claim: a POSTED workweek transitions to LOCKED on lock.
        """
        from test_helpers import setup_week_with_shifts, TEST_USERS
        built = setup_week_with_shifts(
            daily_hours=[8.0, 8.0],
            jurisdiction="FED",
            base_hourly_rate_cents=2000,
        )
        finalize_shift(built["shifts"][0]["id"])
        ww_after_first = get_workweek(built["shifts"][0]["workweek_id"])
        finalize_shift(built["shifts"][1]["id"])
        api.lock_workweek(
            ww_after_first["id"], TEST_USERS["payroll_admin_headers"],
        )
        ww_locked = get_workweek(ww_after_first["id"])
        assert ww_locked["payroll_status"] == "LOCKED"
