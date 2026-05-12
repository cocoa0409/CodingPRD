"""Storage fee accrual: tiered hourly pricing.

PRD §3.8 (Storage-Fee Accrual: Tiered Hourly Pricing).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    advance_clock_hours,
    pickup_with_code,
    register_shelved_parcel,
    run_sweep,
    setup_station_with_staff,
    setup_picked_up_parcel,
    TEST_USERS,
    validate_success,
)


class TestStorageFeeBoundary:
    def test_pickup_within_free_window_yields_zero_fee(self, api):
        """PRD §3.8: "A parcel's storage fee begins to accrue only
        after its free_storage_deadline. Until that moment,
        storage_fee_total is zero."

        Claim: pickup at exactly the deadline (t == deadline) yields
        storage_fee_total == 0.00 and storage_fee_locked == true.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="M")
        # Advance clock to exactly deadline (72h * 3600s).
        advance_clock(72 * 3600)
        picked = pickup_with_code(ctx, parcel)
        assert picked["storage_fee_total"] == 0.0
        assert picked["storage_fee_locked"] is True

    def test_pickup_one_second_past_deadline_yields_one_hour_fee(self, api):
        """PRD §3.8: "the overdue duration is the difference (t -
        free_storage_deadline) expressed in hours and rounded up to
        the next whole hour. ... the first tier covers the first 24 of
        those overdue hours and is priced at 0.50 CNY per hour. ... the
        final number is rounded to two decimal places, half-up.
        Rounding happens exactly once, after the size multiplier has
        been applied."

        Claim: 1 second past deadline on a size-M parcel ceils to 1
        hour, tier1 = 1*0.50, multiplier 1.0 -> storage_fee_total ==
        0.50.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="M")
        advance_clock(72 * 3600 + 1)  # 1 second past deadline
        picked = pickup_with_code(ctx, parcel)
        assert picked["storage_fee_total"] == 0.50

    def test_xl_parcel_size_multiplier_two(self, api):
        """PRD §3.8: "the size multiplier — 1.0 for S, 1.0 for M, 1.5
        for L, and 2.0 for XL — and the final number is rounded to
        two decimal places, half-up. Rounding happens exactly once,
        after the size multiplier has been applied."

        Claim: an XL parcel 100 hours overdue yields raw =
        (24*0.50 + 72*1.00 + 4*2.00) = 92.00, * 2.0 (XL) = 184.00.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="XL")
        # Advance to deadline + 100h.
        advance_clock(72 * 3600 + 100 * 3600)
        # Run sweep first so SHELVED -> OVERTIME and fee accrual logic
        # is exercised on the active row (not required but realistic).
        run_sweep()
        picked = pickup_with_code(ctx, parcel)
        assert picked["storage_fee_total"] == 184.00

    def test_l_parcel_in_first_tier(self, api):
        """PRD §3.8: "the first tier covers the first 24 of those
        overdue hours and is priced at 0.50 CNY per hour."

        Claim: an L parcel exactly 1 hour overdue: tier1=1*0.50=0.50,
        size_multiplier=1.5 -> 0.75.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="L")
        advance_clock(72 * 3600 + 1)  # 1 second past -> ceil to 1h
        picked = pickup_with_code(ctx, parcel)
        assert picked["storage_fee_total"] == 0.75


class TestStorageFeeFinalization:
    def test_storage_fee_locked_true_on_picked_up(self, api):
        """PRD §3.8: "The final variant is invoked when the parcel
        transitions into PICKED_UP, RETURNED, or DISPOSED: it uses t
        equal to that terminal-state timestamp ... writes the
        resulting figure to storage_fee_total, and sets
        storage_fee_locked to true."

        Claim: a picked-up parcel carries storage_fee_locked=true.
        """
        _ctx, parcel = setup_picked_up_parcel(overdue_hours=0)
        assert parcel["status"] == "PICKED_UP"
        assert parcel["storage_fee_locked"] is True

    def test_sweep_after_pickup_does_not_change_locked_fee(self, api):
        """PRD §3.8: "Once locked, subsequent recomputes must not alter
        the recorded storage_fee_total."

        Claim: after pickup, a subsequent sweep does NOT change the
        parcel's storage_fee_total.
        """
        ctx = setup_station_with_staff(free_storage_hours=72)
        parcel = register_shelved_parcel(ctx, size_class="M")
        advance_clock(72 * 3600 + 50 * 3600)  # 50h overdue
        picked = pickup_with_code(ctx, parcel)
        fee_at_pickup = picked["storage_fee_total"]
        # Advance further and run another sweep.
        advance_clock(24 * 3600)
        run_sweep()
        reread = validate_success(
            api.get_parcel(parcel["id"], ctx["clerk_headers"])
        )
        assert reread["storage_fee_total"] == fee_at_pickup
        assert reread["storage_fee_locked"] is True
