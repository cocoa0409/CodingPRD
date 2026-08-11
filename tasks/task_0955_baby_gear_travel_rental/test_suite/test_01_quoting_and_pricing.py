"""Quoting and pricing: provisional quote composition, tiered rental pricing,
delivery-fee tier keying, and the two insurance premium variants."""
import pytest

from test_helpers import (
    create_catalog_item,
    create_customer,
    create_insurance_plan,
    create_quoted_reservation,
    make_customer_headers,
    validate_success,
)


class TestInsurancePremiumVariants:
    def test_per_day_plan_premium_scales_with_trip_length(self, api):
        """PRD 3.3: "Finally the insurance premium is computed: for a `PER_DAY`
        plan it is the plan's `rate_value` rounded half-up, multiplied by the
        billable days; for a `PERCENT_OF_RENTAL` plan it is the gear subtotal
        times `rate_value`, rounded half-up; with no plan the premium is zero."
        PRD 3.3: "The `quoted_total_cents` is the gear subtotal plus the
        delivery fee plus the setup fee plus the premium."

        3 billable days at rate 3000/day -> gear 9000; delivery fee 2500
        (subtotal under 10000); setup fee 1500; PER_DAY premium 200 x 3 = 600;
        quoted total 9000 + 2500 + 1500 + 600 = 13600.

        Design: Difficulty/dual_variant_calc/insurance_premium_per_day_vs_percent_of_rental
        """
        customer = create_customer()
        catalog = create_catalog_item(daily_rate_cents=3000)
        plan_pd = create_insurance_plan(
            code="PD-QUOTE", pricing_model="PER_DAY", rate_value=200
        )
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            start_date="2026-06-10",
            end_date="2026-06-13",
            insurance_plan_id=plan_pd["id"],
        )
        assert reservation["gear_subtotal_cents"] == 9000
        assert reservation["quoted_total_cents"] == 13600, (
            f"PER_DAY plan: expected quoted 13600, got "
            f"{reservation['quoted_total_cents']}"
        )

    def test_percent_of_rental_plan_premium_scales_with_gear_value(self, api):
        """PRD 3.1: "The two models are genuinely different algorithms: for
        identical trip data a per-day plan scales with trip length only, while
        a percentage plan scales with gear value only, and they produce
        different premiums."
        PRD 3.3: "for a `PERCENT_OF_RENTAL` plan it is the gear subtotal times
        `rate_value`, rounded half-up; with no plan the premium is zero."

        Same trip data (3 days, gear subtotal 9000): PERCENT_OF_RENTAL 0.08 ->
        premium round_half_up(9000 x 0.08) = 720; quoted total
        9000 + 2500 + 1500 + 720 = 13720, different from the PER_DAY variant.

        Design: Difficulty/dual_variant_calc/insurance_premium_per_day_vs_percent_of_rental
        """
        customer = create_customer()
        catalog = create_catalog_item(daily_rate_cents=3000)
        plan_pc = create_insurance_plan(
            code="PC-QUOTE", pricing_model="PERCENT_OF_RENTAL", rate_value=0.08
        )
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            start_date="2026-06-10",
            end_date="2026-06-13",
            insurance_plan_id=plan_pc["id"],
        )
        assert reservation["gear_subtotal_cents"] == 9000
        assert reservation["quoted_total_cents"] == 13720, (
            f"PERCENT_OF_RENTAL plan: expected quoted 13720, got "
            f"{reservation['quoted_total_cents']}"
        )


class TestDeliveryFeeTierKeying:
    def test_delivery_fee_tiered_on_gear_subtotal_not_running_total(self, api):
        """PRD 3.3: "Only after the subtotal exists is the delivery fee tiered
        on that subtotal alone — never on the running total: a subtotal under
        10000 cents attracts a 2500-cent delivery fee, a subtotal from 10000 up
        to and including 29999 cents attracts 1500 cents, and a subtotal of
        30000 cents or more ships free."
        PRD 3.3: "A flat 1500-cent setup fee is then added."

        Gear subtotal 9000 (< 10000) -> delivery fee 2500 even though the
        resulting total 13000 lies inside the 1500-cent tier; keying the tier
        on the total would wrongly yield 12000.

        Design: Difficulty/combinatorial_formula/quote_delivery_fee_tier_keyed_on_gear_subtotal
        """
        customer = create_customer()
        catalog = create_catalog_item(daily_rate_cents=3000)
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            start_date="2026-06-10",
            end_date="2026-06-13",
        )
        assert reservation["gear_subtotal_cents"] == 9000
        assert reservation["quoted_total_cents"] == 13000, (
            "9000 gear + 2500 delivery (tier keyed on subtotal) + 1500 setup"
        )

    def test_subtotal_at_tier2_boundary_attracts_1500_fee(self, api):
        """PRD 3.3: "a subtotal from 10000 up to and including 29999 cents
        attracts 1500 cents, and a subtotal of 30000 cents or more ships free."
        PRD 3.3: "The billable length of the rental is the number of days from
        `start_date` to the exclusive `end_date`, with a minimum of one
        billable day."

        A 2-day rental at 5000/day lands the gear subtotal exactly on the
        tier-2 boundary: 10000 -> delivery fee 1500 -> quoted
        10000 + 1500 + 1500 = 13000, the same total as the tier-1 scenario but
        with a different composition.

        Design: Difficulty/combinatorial_formula/quote_delivery_fee_tier_keyed_on_gear_subtotal
        """
        customer = create_customer()
        catalog = create_catalog_item(daily_rate_cents=5000)
        reservation = create_quoted_reservation(
            customer["id"],
            lines=[{"catalog_item_id": catalog["id"]}],
            start_date="2026-06-10",
            end_date="2026-06-12",
        )
        assert reservation["gear_subtotal_cents"] == 10000
        assert reservation["quoted_total_cents"] == 13000, (
            "10000 gear (tier 2 boundary) + 1500 delivery + 1500 setup"
        )


def test_tiered_long_rental_quote(api):
    """PRD 3.3: "the first six billable days are charged at the full daily
    rate; days seven through thirteen are charged per day at the daily rate
    times 0.85, rounded half-up to the cent; days fourteen and beyond are
    charged per day at the daily rate times 0.70, also rounded half-up."

    8-day rental at 3000/day: 6 x 3000 + 2 x round_half_up(3000 x 0.85) =
    18000 + 2 x 2550 = 23100 gear subtotal; 23100 is in the tier-2 band so the
    delivery fee is 1500; setup fee 1500; quoted total 26100.

    Design: Corner/calculations/tiered_long_rental_quote
    """
    customer = create_customer()
    catalog = create_catalog_item(daily_rate_cents=3000)
    reservation = create_quoted_reservation(
        customer["id"],
        lines=[{"catalog_item_id": catalog["id"]}],
        start_date="2026-06-01",
        end_date="2026-06-09",
    )
    assert reservation["gear_subtotal_cents"] == 23100, (
        f"expected tiered gear subtotal 23100, got "
        f"{reservation['gear_subtotal_cents']}"
    )
    assert reservation["quoted_total_cents"] == 26100, (
        f"expected quoted total 26100, got {reservation['quoted_total_cents']}"
    )
