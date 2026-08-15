"""Rental billing: provisional vs final variants, tiers, discounts, overage,
and fleet utilization."""
import pytest

from test_helpers import (
    get_customer,
    get_unit,
    make_customer,
    make_rental_contract,
    make_returned_contract,
    make_unit,
    set_clock,
)


class TestProvisionalVsFinalBilling:
    def test_provisional_estimate_uses_ceil_weeks(self, api):
        """PRD §3.3: "On the `WEEKLY` tier it is the scheduled days divided by 7
        and rounded up to whole weeks, times `weekly_rate_cents`" — and
        "identical schedule data yields different numbers: a 10-day reservation
        on a unit at 15000 cents per day and 70000 cents per week holds 140000
        cents provisionally".

        Design: Difficulty/dual_variant_calc/rental_billing_provisional_vs_final
        """
        customer = make_customer(name="Acme Materials")
        unit = make_unit(serial_number="SN-DV1")
        contract = make_rental_contract(customer["id"], unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-08-11")
        assert contract["scheduled_days"] == 10
        assert contract["rate_tier"] == "WEEKLY"
        assert contract["provisional_estimate_cents"] == 140000, \
            "ceil(10/7)=2 weeks * 70000"

    def test_final_charge_uses_floor_weeks_capped_remainder(self, api):
        """PRD §3.3: the final variant bills "`WEEKLY` is the whole weeks in
        the scheduled window (days divided by 7, rounded down) times the
        weekly rate, plus the leftover days at the daily rate with that
        leftover charge capped at one weekly rate" — so the same 10-day
        reservation "bills 115000 cents at return when the unit comes back on
        schedule", and the customer balance moves by the final charge while
        the hold is released ("the provisional hold is released from
        `credit_holds_cents` and `final_charge_cents` is posted to
        `outstanding_balance_cents`").

        Design: Difficulty/dual_variant_calc/rental_billing_provisional_vs_final
        """
        customer, unit, contract = make_returned_contract(
            return_date="2026-08-11", return_hours=40,
            start_date="2026-08-01", end_date="2026-08-11",
            unit_overrides={"serial_number": "SN-DV2"})
        assert contract["final_charge_cents"] == 115000, \
            "floor(10/7)=1 week 70000 + min(3*15000, 70000)=45000"
        assert contract["final_charge_cents"] != contract[
            "provisional_estimate_cents"]
        assert customer["outstanding_balance_cents"] == 115000
        assert customer["credit_holds_cents"] == 0
        unit_after = get_unit(unit["id"])
        assert unit_after["availability_status"] == "AVAILABLE"
        assert unit_after["maintenance_posture"] == "PM_OK"  # 40 < 500


class TestMonthlyTierWithDiscount:
    def test_monthly_tier_selected_at_40_days(self, api):
        """PRD §3.3: "`scheduled_days` is the whole number of days between
        them. That length determines the `rate_tier`: `DAILY` when the window
        is shorter than 7 days, `WEEKLY` when it is at least 7 but fewer than
        28 days, and `MONTHLY` when it runs 28 days or longer."

        Design: Difficulty/combinatorial_formula/rental_tiered_monthly_discount
        """
        customer = make_customer(name="Discounter Co", discount_pct=0.10)
        unit = make_unit(serial_number="SN-CF1")
        contract = make_rental_contract(customer["id"], unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-09-10")
        assert contract["scheduled_days"] == 40
        assert contract["rate_tier"] == "MONTHLY"

    def test_monthly_provisional_with_discount_and_hold(self, api):
        """PRD §3.3: "On the `MONTHLY` tier it is the scheduled days divided by
        28 and rounded up to whole months, times `monthly_rate_cents`. The
        customer's `discount_pct` is then applied to that tier amount with
        round-half-up to whole cents" — ceil(40/28)=2 * 210000 * 0.9 = 378000 —
        "The resulting `provisional_estimate_cents` is placed on the customer
        as a credit hold: `credit_holds_cents` increases by exactly that
        amount."

        Design: Difficulty/combinatorial_formula/rental_tiered_monthly_discount
        """
        customer = make_customer(name="Discounter Co", discount_pct=0.10)
        unit = make_unit(serial_number="SN-CF2")
        contract = make_rental_contract(customer["id"], unit["id"],
                                        start_date="2026-08-01",
                                        end_date="2026-09-10")
        assert contract["provisional_estimate_cents"] == 378000
        assert get_customer(customer["id"])["credit_holds_cents"] == 378000


class TestOverageUndiscounted:
    def test_late_return_overage_at_150pct_no_discount(self, api):
        """PRD §3.3: "The discount applies only to this tier portion, rounded
        half up to whole cents. Overage days are never discounted: each costs
        one and a half times the daily rate, with that single-day overage
        figure rounded half up to whole cents once and then multiplied by the
        number of overage days." A 4-day DAILY contract at 15000/day with a 10%
        customer discount, returned 2 days late: provisional 54000, final
        54000 + 2*22500 = 99000.

        Design: Corner/calculations/rental_overage_undiscounted
        """
        customer, _unit, contract = make_returned_contract(
            return_date="2026-08-07", return_hours=40,
            start_date="2026-08-01", end_date="2026-08-05",
            customer_overrides={"name": "Late Co", "discount_pct": 0.10},
            unit_overrides={"serial_number": "SN-OV1"})
        assert contract["provisional_estimate_cents"] == 54000, \
            "4*15000*0.9"
        assert contract["final_charge_cents"] == 99000, \
            "54000 discounted tier + 2 * 22500 undiscounted overage"


class TestFleetUtilization:
    def test_utilization_pct_90d_after_return(self, api):
        """PRD §3.3: "Dividing the summed rented days by 90 and multiplying by
        100, then rounding half up to one decimal place, yields
        `utilization_pct_90d`; a unit with no qualifying contracts reports
        0.0." A returned 10-day contract inside the trailing 90-day window
        contributes 10 rented days -> 11.1.

        Design: Corner/calculations/utilization_pct_90d_after_return
        """
        _customer, unit, contract = make_returned_contract(
            return_date="2026-08-11", return_hours=40,
            start_date="2026-08-01", end_date="2026-08-11",
            unit_overrides={"serial_number": "SN-UT1"})
        assert contract["status"] == "RETURNED"
        set_clock("2026-08-11T00:00:00Z")
        data = get_unit(unit["id"])
        assert data["utilization_pct_90d"] == pytest.approx(11.1, abs=0.001), \
            "10 rented days in the trailing 90-day window"
