"""Rounding order and the pinned order-level waterfall (PRD §2.5, §3.4)."""

from test_helpers import (
    EMULSIFIER,
    YEAST_INSTANT,
    add_order_line,
    create_customer,
    create_product,
    open_order,
    read_order_line,
    set_clock,
    submit_order,
)


def _order_with_yeast_lines(quantity_lb, line_count):
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer()
    product = create_product(YEAST_INSTANT)
    order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    lines = [
        add_order_line(customer, order["id"], product["id"], quantity_lb)
        for _ in range(line_count)
    ]
    return customer, order, lines


class TestPerLineRoundingThenSum:
    """Two identical lines whose exact net value ends in .500 cents."""

    def test_each_line_is_rounded_half_up_before_the_subtotal_is_summed(self):
        """PRD §2.5: "the order subtotal is produced by rounding each line to
        whole cents and then summing the rounded line values, never by summing
        exact fractional line values and rounding once at the end."

        Each 2010 lb line at 310 c/lb earns the one-and-a-half percent tier, so
        its exact net value is 613753.500 cents; rounding first gives 613754 per
        line and a subtotal of 1227508, where summing first would give 1227507.

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_round_per_line_then_sum_beats_sum_then_round_by_one_cent
        """
        customer, order, lines = _order_with_yeast_lines(2010, 2)

        submitted = submit_order(customer, order["id"])

        first = read_order_line(lines[0]["id"])
        second = read_order_line(lines[1]["id"])
        assert first["unit_price_cents"] == 310, (
            f"Expected the list price 310 c/lb, got {first['unit_price_cents']}"
        )
        assert first["extended_cents"] == 613754, (
            f"Expected line extension 613754, got {first['extended_cents']}"
        )
        assert second["extended_cents"] == 613754, (
            f"Expected line extension 613754, got {second['extended_cents']}"
        )
        assert submitted["subtotal_cents"] == 1227508, (
            f"Expected subtotal 1227508, got {submitted['subtotal_cents']}"
        )
        assert submitted["subtotal_cents"] != 1227507, (
            "Subtotal 1227507 means the exact line values were summed before rounding"
        )

    def test_order_total_follows_from_the_per_line_rounded_subtotal(self):
        """PRD §3.4: "Finally, `total_cents` is the subtotal plus the fuel
        surcharge plus the formulation-support attach fee, less the volume
        rebate."

        Requested delivery on 2026-09-15 falls outside both declared surge
        windows, so the surcharge is two and a half percent of 1227508 and the
        rebate is one percent of the same subtotal.

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_round_per_line_then_sum_beats_sum_then_round_by_one_cent
        """
        customer, order, _lines = _order_with_yeast_lines(2010, 2)

        submitted = submit_order(customer, order["id"])

        assert submitted["surge_window"] is False, (
            "2026-09-15 sits outside both declared surge windows"
        )
        assert submitted["fuel_surcharge_cents"] == 30688, (
            f"Expected fuel surcharge 30688, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["volume_rebate_cents"] == 12275, (
            f"Expected volume rebate 12275, got {submitted['volume_rebate_cents']}"
        )
        assert submitted["total_cents"] == 1245921, (
            f"Expected total 1245921, got {submitted['total_cents']}"
        )


class TestRebateBaseVersusRebateApplication:
    """A subtotal below the first rebate tier whose base crosses it."""

    def test_rebate_tier_is_keyed_on_the_subtotal_plus_fuel_surcharge(self):
        """PRD §3.4: "the volume rebate tier is keyed on a base that already
        contains the fuel surcharge, while the rebate percentage itself is
        applied to the subtotal alone and never to the surcharge."

        A subtotal of 490000 is below the five-thousand-dollar floor, but the
        base of 490000 + 12250 = 502250 crosses it, so the one percent tier
        applies.

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_rebate_tier_keyed_on_subtotal_plus_fuel_but_applied_to_subtotal
        """
        set_clock("2026-08-05T00:00:00Z")
        customer = create_customer()
        product = create_product(EMULSIFIER)
        order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
        line = add_order_line(customer, order["id"], product["id"], 1000)

        submitted = submit_order(customer, order["id"])

        assert read_order_line(line["id"])["extended_cents"] == 490000
        assert submitted["subtotal_cents"] == 490000, (
            f"Expected subtotal 490000, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 12250, (
            f"Expected fuel surcharge 12250, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["volume_rebate_cents"] == 4900, (
            "A rebate of 0 means the tier was keyed on the subtotal alone, got "
            f"{submitted['volume_rebate_cents']}"
        )

    def test_rebate_percentage_is_applied_to_the_subtotal_not_to_the_base(self):
        """PRD §3.4: "The chosen rate is applied to `subtotal_cents` and rounded
        half-up to whole cents to give `volume_rebate_cents`."

        One percent of the 490000 subtotal is 4900, not the 5023 that one percent
        of the 502250 rebate base would give, so the total settles at 497350.

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_rebate_tier_keyed_on_subtotal_plus_fuel_but_applied_to_subtotal
        """
        set_clock("2026-08-05T00:00:00Z")
        customer = create_customer()
        product = create_product(EMULSIFIER)
        order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
        add_order_line(customer, order["id"], product["id"], 1000)

        submitted = submit_order(customer, order["id"])

        assert submitted["volume_rebate_cents"] == 4900, (
            f"Expected rebate 4900 on the subtotal, got {submitted['volume_rebate_cents']}"
        )
        assert submitted["total_cents"] == 497350, (
            f"Expected total 497350, got {submitted['total_cents']}"
        )
        assert submitted["total_cents"] != 502250, (
            "Total 502250 means no rebate was applied at all"
        )
