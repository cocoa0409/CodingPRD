"""Rent schedule generation: NONE / ANNUAL / BIENNIAL / STEPPED, rent-free,
proration.

PRD §3.4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    assert_rent_schedule_item,
    get_rent_schedule,
    make_stepped_entry,
    setup_signed_lease,
    validate_success,
    LA,
)


# ===========================================================================
# NONE escalation — flat monthly rent
# ===========================================================================
class TestRentScheduleNone:
    """PRD §3.4: 'When escalation_mode is NONE, the monthly rent is
    base_monthly_rent_cents unchanged for every month.'
    """

    def test_none_escalation_flat_rent_full_year(self, api):
        """PRD §3.4: 'When escalation_mode is NONE, the monthly rent is
        base_monthly_rent_cents unchanged for every month.'"""
        ctx = setup_signed_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2027-01-01T00:00:00.000Z",  # 12 full months
            base_monthly_rent_cents=100000,
            escalation_mode="NONE",
        )
        rows = get_rent_schedule(ctx["lease"]["id"])
        assert len(rows) == 12, (
            f"expected 12 RentScheduleItem rows for 12-month lease, got "
            f"{len(rows)}"
        )
        for r in rows:
            assert_rent_schedule_item(r)
            assert r["gross_rent_cents"] == 100000, (
                f"NONE-escalation row should be 100000 cents, got "
                f"{r['gross_rent_cents']}"
            )
            assert r["rent_free_offset_cents"] == 0
            assert r["net_rent_cents"] == 100000
            assert r["status"] == "PENDING"


# ===========================================================================
# Partial-month proration
# ===========================================================================
class TestRentScheduleProration:
    """PRD §3.4 Step 2: 'Let days_in_month be the calendar count of
    days in M, and let active_days be the count of days inside the
    intersection of M with [start_date, end_date). Then
    gross_rent_cents for the row is the round-half-up of monthly ×
    active_days / days_in_month, computed exactly in that order.'
    """

    def test_partial_last_month_prorated(self, api):
        """PRD §3.4: 'gross_rent_cents for the row is the round-half-up
        of monthly × active_days / days_in_month, computed exactly in
        that order.'"""
        # Lease from 2026-01-01 to 2026-02-15 → Jan full (31 days), Feb
        # partial (14 of 28 active days).
        ctx = setup_signed_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-02-15T00:00:00.000Z",
            base_monthly_rent_cents=100000,
            escalation_mode="NONE",
        )
        rows = sorted(get_rent_schedule(ctx["lease"]["id"]),
                      key=lambda r: r["period_start"])
        assert len(rows) == 2
        jan, feb = rows
        # January is a full month — 100000 cents.
        assert jan["gross_rent_cents"] == 100000
        # February: 14 active days of 28 = round_half_up(100000 * 14 / 28)
        #         = 50000 cents
        assert feb["gross_rent_cents"] == 50000


# ===========================================================================
# Rent-free deduction
# ===========================================================================
class TestRentFreeDeduction:
    """PRD §3.4 Step 3: 'The rent_free_days count applies to the
    earliest days of the lease, not spread across the lease. ... The
    net_rent_cents of the row is the maximum of zero and
    gross_rent_cents − rent_free_offset_cents.'
    """

    def test_rent_free_concentrated_in_first_month(self, api):
        """PRD §3.4: 'The rent_free_days count applies to the earliest
        days of the lease, not spread across the lease.'"""
        # 31 days of January, rent_free_days = 10 → all 10 free in Jan.
        ctx = setup_signed_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-03-01T00:00:00.000Z",
            base_monthly_rent_cents=100000,
            escalation_mode="NONE",
            rent_free_days=10,
        )
        rows = sorted(get_rent_schedule(ctx["lease"]["id"]),
                      key=lambda r: r["period_start"])
        jan, feb = rows[0], rows[1]
        # Jan free offset = round_half_up(100000 * 10 / 31)
        # = round_half_up(32258.0645…) = 32258
        assert jan["rent_free_offset_cents"] == 32258
        # Net = max(0, 100000 − 32258) = 67742
        assert jan["net_rent_cents"] == 67742
        # Feb gets no free days.
        assert feb["rent_free_offset_cents"] == 0
        assert feb["net_rent_cents"] == 100000


# ===========================================================================
# STEPPED schedule
# ===========================================================================
class TestRentScheduleStepped:
    """PRD §3.4: 'When escalation_mode is STEPPED, the algorithm
    performs a table lookup against the stepped_schedule array: the
    monthly rent in effect on M is the monthly_rent_cents of the entry
    with the largest index whose effective_from is on or before M's
    start.'
    """

    def test_stepped_two_step_table_lookup(self, api):
        """PRD §3.4: 'the monthly rent in effect on M is the
        monthly_rent_cents of the entry with the largest index whose
        effective_from is on or before M's start.'"""
        ctx = setup_signed_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",
            base_monthly_rent_cents=100000,
            escalation_mode="STEPPED",
            stepped_schedule=[
                make_stepped_entry(
                    effective_from="2026-01-01T00:00:00.000Z",
                    monthly_rent_cents=100000,
                ),
                make_stepped_entry(
                    effective_from="2026-07-01T00:00:00.000Z",
                    monthly_rent_cents=110000,
                ),
            ],
        )
        rows = sorted(get_rent_schedule(ctx["lease"]["id"]),
                      key=lambda r: r["period_start"])
        # 11 months Jan..Nov inclusive
        assert len(rows) == 11
        # Jan..Jun → 100000
        for r in rows[:6]:
            assert r["gross_rent_cents"] == 100000, (
                f"pre-step row at {r['period_start']} should be 100000, "
                f"got {r['gross_rent_cents']}"
            )
        # Jul..Nov → 110000
        for r in rows[6:]:
            assert r["gross_rent_cents"] == 110000, (
                f"post-step row at {r['period_start']} should be 110000, "
                f"got {r['gross_rent_cents']}"
            )


# ===========================================================================
# ANNUAL escalation — anniversary-based
# ===========================================================================
class TestRentScheduleAnnual:
    """PRD §3.4: 'When escalation_mode is ANNUAL, the algorithm
    computes the number of full years elapsed from the lease's
    start_date to the start of M as the floor of the elapsed days
    divided by 365.25 ... then multiplies base_monthly_rent_cents by
    (10000 + escalation_pct_bps) / 10000 raised to that integer
    power.'
    """

    def test_annual_first_year_no_escalation(self, api):
        """PRD §3.4: 'the number of full years elapsed ... as the floor
        of the elapsed days divided by 365.25.' In year 1 (years_elapsed
        = 0), rent stays at base."""
        ctx = setup_signed_lease(
            start_date="2026-01-01T00:00:00.000Z",
            end_date="2026-12-01T00:00:00.000Z",  # 11 months in year 1
            base_monthly_rent_cents=100000,
            escalation_mode="ANNUAL",
            escalation_pct_bps=500,
        )
        rows = sorted(get_rent_schedule(ctx["lease"]["id"]),
                      key=lambda r: r["period_start"])
        # 11 months, all within year 1 (≤ 365.25 days from start)
        assert len(rows) == 11
        for r in rows:
            assert r["gross_rent_cents"] == 100000, (
                f"year-1 ANNUAL row should be 100000, got "
                f"{r['gross_rent_cents']}"
            )
