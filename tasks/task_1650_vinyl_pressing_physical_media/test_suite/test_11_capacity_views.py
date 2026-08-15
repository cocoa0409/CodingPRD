"""Computed capacity and warehousing views: the optimistic/conservative
backlog dual variant and the storage daily-accrual/monthly-statement dual
variant."""
import pytest

from test_helpers import (
    create_inventory_lot,
    create_queued_order,
    decide_qc_report,
    file_qc_report,
    press_run,
    receive_stock,
    schedule_order,
    set_clock,
    setup_world,
    validate_success,
)
from test_helpers.fixtures import CSR


class TestBacklogDualVariant:
    def test_backlog_optimistic_vs_conservative_before_repress(self, api):
        """PRD §3.6: "Booked hours total the lengths of the line's unfreed
        `PRODUCTION` slots dated today or later, plus one changeover hour for
        every adjacent pair of different-family slots on the same date. The
        optimistic figure divides booked hours by `hours_per_day`, rounded
        half-up to two decimal places, and backs customer-facing promise
        dates. The conservative figure inflates booked hours by twenty-five
        percent, adds a repress-queue term — the sum, over each order of this
        line currently `QUEUED` after at least one repress, of that order's
        `quantity_ordered` divided by the line's hourly rate and rounded up to
        whole hours — divides the total by `hours_per_day`, and rounds half-up
        to two decimals; identical slot data therefore yields two deliberately
        different backlog answers, one for promises and one for internal risk."

        Design: Difficulty/dual_variant_calc/backlog_optimistic_vs_conservative
        """
        world = setup_world()
        staged = create_queued_order(world, quantity_ordered=1000)
        schedule_order(staged["order"], world["line"]["id"],
                       date="2026-08-10", start_hour=0, end_hour=8,
                       planned_units=1000)

        backlog = validate_success(
            api.get_line_backlog(world["line"]["id"], CSR), 200
        )
        assert backlog["booked_hours"] == 8
        # optimistic: round_half_up(8 / 16, 2)
        assert backlog["optimistic_backlog_days"] == pytest.approx(0.50, abs=1e-6)
        # conservative: round_half_up(8 * 1.25 / 16, 2) = round_half_up(0.625, 2)
        assert backlog["conservative_backlog_days"] == pytest.approx(0.63, abs=1e-6)

    def test_backlog_conservative_absorbs_repress_queue(self, api):
        """PRD §3.6: "The conservative figure inflates booked hours by
        twenty-five percent, adds a repress-queue term — the sum, over each
        order of this line currently `QUEUED` after at least one repress, of
        that order's `quantity_ordered` divided by the line's hourly rate and
        rounded up to whole hours — divides the total by `hours_per_day`, and
        rounds half-up to two decimals"

        Design: Difficulty/dual_variant_calc/backlog_optimistic_vs_conservative
        """
        world = setup_world()
        staged = create_queued_order(world, quantity_ordered=1000)
        order = schedule_order(staged["order"], world["line"]["id"],
                               date="2026-08-10", start_hour=0, end_hour=8,
                               planned_units=1000)
        before = validate_success(
            api.get_line_backlog(world["line"]["id"], CSR), 200
        )
        assert before["optimistic_backlog_days"] == pytest.approx(0.50, abs=1e-6)
        assert before["conservative_backlog_days"] == pytest.approx(0.63, abs=1e-6)

        press_run(order["id"], slot_date="2026-08-10")
        qc = file_qc_report(order["id"], 1000, 100)
        decide_qc_report(qc["id"], "REPRESS", "PLANT", decider="pm-1")

        after = validate_success(
            api.get_line_backlog(world["line"]["id"], CSR), 200
        )
        # Only the conservative variant reacts to the repress queue:
        # (8*1.25 + ceil(1000/313)) / 16 = 14/16 = 0.875 -> 0.88.
        assert after["optimistic_backlog_days"] == pytest.approx(0.50, abs=1e-6)
        assert after["conservative_backlog_days"] == pytest.approx(0.88, abs=1e-6)
        assert after["conservative_backlog_days"] != before["conservative_backlog_days"]


class TestStorageFeeDualVariant:
    def _lot_held_30_days(self):
        """Zone-A lot with 1000 LP units (10 pallets) received 2026-08-01;
        clock advanced to 2026-08-31 so the trailing 30-day window sees 10
        pallets on hand every day."""
        world = setup_world(release_over={"format": "LP", "weight_gram": 140},
                            with_line=False, with_bath=False)
        lot = create_inventory_lot(world["release"]["id"], zone="A")
        receive_stock(lot["id"], 1000, event_date="2026-08-01")
        set_clock("2026-08-31T00:00:00Z")
        return lot

    def test_storage_daily_accrual(self, api):
        """PRD §3.8: "`storage_daily_accrual_cents` sums, over each day in the
        window, that day's on-hand pallets — on-hand units divided by
        units-per-pallet, rounded up — times 55 cents"

        Design: Difficulty/dual_variant_calc/storage_accrual_vs_statement_divergence
        """
        lot = self._lot_held_30_days()
        data = validate_success(api.get_inventory_lot(lot["id"], CSR), 200)
        # 30 days x ceil(1000/100) pallets x 55 cents.
        assert data["storage_daily_accrual_cents"] == 16500

    def test_storage_monthly_statement_diverges(self, api):
        """PRD §3.8: "`storage_monthly_statement_cents` instead averages the
        daily pallet counts across the days in the month, rounds that average
        half-up to two decimals, multiplies by 1500 cents per pallet, and
        floors the result at a 5000-cent monthly minimum, taking the larger of
        the two."
        PRD §3.8: "two deliberately divergent storage-fee figures"

        Design: Difficulty/dual_variant_calc/storage_accrual_vs_statement_divergence
        """
        lot = self._lot_held_30_days()
        data = validate_success(api.get_inventory_lot(lot["id"], CSR), 200)
        # avg 10.00 pallets x 1500 = 15000, above the 5000 floor.
        assert data["storage_monthly_statement_cents"] == 15000
        assert data["storage_daily_accrual_cents"] == 16500
        assert data["storage_daily_accrual_cents"] != (
            data["storage_monthly_statement_cents"]
        ), "identical pallet-day data must price differently under the two variants"
