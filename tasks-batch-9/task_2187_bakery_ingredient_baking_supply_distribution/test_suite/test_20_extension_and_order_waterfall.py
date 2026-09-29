"""Steps two and three of the pricing waterfall: extension, surcharge and rebate (PRD §3.4)."""

from test_helpers import (
    add_order_line,
    create_customer,
    create_product,
    open_order,
    read_customer,
    read_order_line,
    set_clock,
    submit_order,
)

FLOUR_33 = {
    "sku": "FLR-P33",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 33,
    "min_rotation_days": 0,
}
DAIRY_33 = {
    "sku": "DRY-Q33",
    "category": "INCLUSION",
    "allergen_class": "DAIRY",
    "shelf_life_days": 120,
    "index_code": "NONE",
    "list_price_cents_per_lb": 33,
    "min_rotation_days": 0,
}
FLOUR_30 = {
    "sku": "FLR-SURGE-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


def _bakery():
    set_clock("2026-08-01T00:00:00Z")
    return create_customer(credit_limit_cents=10000000, min_drop_cents=1000)


class TestQuantityDiscountTierFloor:
    """A single whole-line rate, and the 2000 lb floor belongs to the discounted tier."""

    def test_two_thousand_pounds_costs_less_than_nineteen_hundred_ninety_nine(self):
        """PRD §3.4: "Each line earns a quantity discount, and the discount is a
        single rate applied to the whole line rather than a marginal rate applied to
        bands. A line of fewer than 2000 pounds earns no discount. A line of 2000
        pounds or more but fewer than 10000 pounds earns one and a half percent."

        Design: Corner/calculations/corner_calc_quantity_discount_tier_boundary_2000_lb_inclusive
        """
        customer = _bakery()
        flour = create_product(FLOUR_33)
        dairy = create_product(DAIRY_33)
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-05T00:00:00Z",
        )
        undiscounted = add_order_line(customer, order["id"], flour["id"], 1999)
        discounted = add_order_line(customer, order["id"], dairy["id"], 2000)

        submitted = submit_order(customer, order["id"])

        assert read_order_line(undiscounted["id"])["extended_cents"] == 65967, (
            "1999 lb at 33 cents earns no discount at all, got "
            f"{read_order_line(undiscounted['id'])['extended_cents']}"
        )
        cheaper = read_order_line(discounted["id"])
        assert cheaper["extended_cents"] == 65010, (
            f"Expected 1.5% off the whole 2000 lb line, got {cheaper['extended_cents']}"
        )
        assert cheaper["extended_cents"] < 65967, (
            "The extra pound must make the line cheaper, not dearer"
        )
        assert submitted["subtotal_cents"] == 130977, (
            f"Expected 65967 + 65010, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 3274, (
            f"Expected 2.5% of 130977 rounded half-up, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["volume_rebate_cents"] == 0, (
            f"A 134251 rebate base earns nothing, got {submitted['volume_rebate_cents']}"
        )
        assert submitted["total_cents"] == 134251, (
            f"Expected total 134251, got {submitted['total_cents']}"
        )


class TestLineLevelRoundingOrder:
    """Round each line, then sum — never the other way round."""

    def test_two_identical_half_cent_lines_round_up_independently(self):
        """PRD §3.4: "The rounding order is pinned: each line's net value is rounded
        half-up to whole cents **first** and written to `extended_cents`, and only
        then are the rounded line values summed, in `created_at` ascending order, to
        produce the order's `subtotal_cents`. Summing exact unrounded line values and
        rounding once at the end is forbidden and yields a different subtotal for the
        same inputs."

        Each 2001 lb line nets 65042.505 cents, so rounding per line gives 130086
        while a single end rounding of 130085.01 would give 130085.

        Design: Corner/calculations/corner_calc_per_line_rounding_before_summation
        """
        customer = _bakery()
        flour = create_product(FLOUR_33)
        dairy = create_product(DAIRY_33)
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-05T00:00:00Z",
        )
        first = add_order_line(customer, order["id"], flour["id"], 2001)
        second = add_order_line(customer, order["id"], dairy["id"], 2001)

        submitted = submit_order(customer, order["id"])

        assert read_order_line(first["id"])["extended_cents"] == 65043, (
            f"Expected 65042.505 rounded half-up, got {read_order_line(first['id'])['extended_cents']}"
        )
        assert read_order_line(second["id"])["extended_cents"] == 65043, (
            f"Expected the same on the sibling line, got {read_order_line(second['id'])['extended_cents']}"
        )
        assert submitted["subtotal_cents"] == 130086, (
            f"Expected 130086 rather than the forbidden 130085, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 3252, (
            f"Expected 2.5% of 130086 rounded half-up, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["total_cents"] == 133338, (
            f"Expected total 133338, got {submitted['total_cents']}"
        )


class TestSurgeWindowLowerEdge:
    """15 November is inside the window, which both raises fuel and kills the rebate."""

    def test_a_delivery_on_the_first_day_of_the_peak_pays_more_and_rebates_nothing(self):
        """PRD §3.4: "First, `surge_window` is determined: it is true when the
        order's `requested_delivery_on` falls inside a declared holiday surge window,
        with both endpoints of the window inclusive. Two surge windows are declared —
        the spring baking build-up running from 15 March 2026 through 15 April 2026,
        and the winter holiday peak running from 15 November 2026 through 31 December
        2026. Second, the fuel surcharge rate is chosen from that flag: four percent
        of subtotal inside a surge window, and two and a half percent outside one."

        PRD §3.4: "If the order sits inside a surge window the rebate rate is zero,
        because rebates are suppressed during holiday peaks no matter how large the
        order."

        Design: Corner/calculations/corner_calc_surge_window_lower_boundary_raises_fuel_and_kills_rebate
        """
        customer = _bakery()
        flour = create_product(FLOUR_30)
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-11-15T00:00:00Z",
        )
        line = add_order_line(customer, order["id"], flour["id"], 20000)

        submitted = submit_order(customer, order["id"])

        assert submitted["surge_window"] is True, (
            f"15 November is the inclusive lower edge, got {submitted['surge_window']}"
        )
        assert read_order_line(line["id"])["extended_cents"] == 582000, (
            f"Expected the 3% tier at 20000 lb, got {read_order_line(line['id'])['extended_cents']}"
        )
        assert submitted["subtotal_cents"] == 582000, (
            f"Expected subtotal 582000, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 23280, (
            f"Expected 4% of 582000, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["volume_rebate_cents"] == 0, (
            f"Expected the rebate suppressed inside the peak, got {submitted['volume_rebate_cents']}"
        )
        assert submitted["total_cents"] == 605280, (
            f"Expected total 605280, got {submitted['total_cents']}"
        )
        assert read_customer(customer["id"])["open_exposure_cents"] == 605280, (
            "The exposure ledger takes the surge-inflated total"
        )


class TestRebateBaseIncludesTheSurcharge:
    """The tier is keyed on subtotal plus fuel; the rate lands on the subtotal alone."""

    def test_the_surcharge_unlocks_a_tier_the_subtotal_alone_would_miss(self):
        """PRD §3.4: "Third — and this is where the arithmetic looks circular but is
        not — the volume rebate tier is keyed on a base that already contains the fuel
        surcharge, while the rebate percentage itself is applied to the subtotal alone
        and never to the surcharge. The rebate base is `subtotal_cents` plus
        `fuel_surcharge_cents`."

        PRD §3.4: "Otherwise, a rebate base below five thousand dollars — that is,
        below 500000 cents — earns no rebate; a base of 500000 cents or more but below
        1500000 cents earns one percent".

        Design: Corner/calculations/corner_calc_rebate_tier_keyed_on_base_including_fuel_applied_to_subtotal
        """
        customer = _bakery()
        flour = create_product({**FLOUR_30, "sku": "FLR-REB-30"})
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-05T00:00:00Z",
        )
        add_order_line(customer, order["id"], flour["id"], 17000)

        submitted = submit_order(customer, order["id"])

        assert submitted["surge_window"] is False, (
            f"A September delivery is outside both windows, got {submitted['surge_window']}"
        )
        assert submitted["subtotal_cents"] == 494700, (
            f"Expected 17000 lb at 30 cents less 3%, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 12368, (
            f"Expected 12367.5 rounded half-up, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["volume_rebate_cents"] == 4947, (
            f"Expected 1% of the 494700 subtotal, not of the 507068 base, got "
            f"{submitted['volume_rebate_cents']}"
        )
        assert submitted["total_cents"] == 502121, (
            f"Expected 494700 + 12368 - 4947, got {submitted['total_cents']}"
        )
