"""Order pricing and the freight program: order-level free-freight threshold
(not per-line), tier x seasonal x qty multiplicative pricing, pinned per-line
rounding order, and the hazmat surcharge + shortfall cap assembly."""
from test_helpers import (
    create_confirmed_order,
    get_order_lines,
    make_account,
    make_branch,
    make_lot,
    make_open_program_with_commitment,
    make_product,
    order_line,
    seed_account_tier,
    set_clock,
    setup_branch_account_product_lot,
)


class TestFreightOrderLevelThreshold:
    def test_freight_free_when_two_lines_each_below_minimum_but_subtotal_above(self, api):
        """PRD §3.5: "Freight is an order-level threshold calculation — evaluating the threshold per line instead is a declared trap variant and produces wrong freight on multi-line orders."
        PRD §3.5: "For `ROUTE_DELIVERY`, the freightable amount is the whole `order_subtotal_cents`, and hazmat lines do count toward the minimum."
        PRD §3.5: "When that amount reaches the free-freight minimum of 50,000 cents ($500), freight is zero."

        Design: Difficulty/dual_variant_calc/freight_order_level_vs_per_line_trap
        """
        set_clock("2026-06-01T00:00:00Z", api)
        branch, account, p1, _l1 = setup_branch_account_product_lot(
            api,
            branch_over={"branch_code": "PHX-12", "hazmat_storage_certified": True},
            account_over={"account_number": "DLR-100"},
            product_over={
                "sku": "PUMP-1HP",
                "product_family": "EQUIPMENT",
                "base_price_cents": 30000,
            },
            lot_over={"qty_on_hand": 10},
        )
        p2 = make_product(api, sku="SEAL-KIT", product_family="PARTS", base_price_cents=30000)
        make_lot(api, branch_id=branch["id"], product_id=p2["id"], qty_on_hand=10)

        # Each line is 30,000c (< 50,000c) but the order subtotal is 60,000c.
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="ROUTE_DELIVERY", route_date="2026-06-10",
            lines=[order_line(p1["id"], 1), order_line(p2["id"], 1)],
        )
        assert order["order_subtotal_cents"] == 60000, (
            f"subtotal is the sum of the per-line rounded amounts: {order}"
        )
        assert order["freight_charge_cents"] == 0, (
            f"order-level threshold: 60,000 >= 50,000 pays no freight "
            f"(per-line evaluation is the declared trap): {order}"
        )
        assert order["invoiced_cents"] == 60000

    def test_freight_free_when_subtotal_reaches_minimum_exactly(self, api):
        """PRD §3.5: "Freight is an order-level threshold calculation — evaluating the threshold per line instead is a declared trap variant and produces wrong freight on multi-line orders."
        PRD §3.5: "When that amount reaches the free-freight minimum of 50,000 cents ($500), freight is zero."

        Design: Difficulty/dual_variant_calc/freight_order_level_vs_per_line_trap
        """
        set_clock("2026-06-01T00:00:00Z", api)
        # Two lines of 25,000c each reach exactly 50,000c at order level.
        branch = make_branch(api, hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-101")
        p1 = make_product(api, sku="PUMP-2HP", product_family="EQUIPMENT", base_price_cents=25000)
        p2 = make_product(api, sku="FILTER-25", product_family="EQUIPMENT", base_price_cents=25000)
        make_lot(api, branch_id=branch["id"], product_id=p1["id"], qty_on_hand=5)
        make_lot(api, branch_id=branch["id"], product_id=p2["id"], qty_on_hand=5)

        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="ROUTE_DELIVERY", route_date="2026-06-10",
            lines=[order_line(p1["id"], 1), order_line(p2["id"], 1)],
        )
        assert order["order_subtotal_cents"] == 50000
        assert order["freight_charge_cents"] == 0, (
            f"reaching the 50,000-cent minimum exactly makes freight zero: {order}"
        )
        assert order["invoiced_cents"] == 50000


class TestFreightChargeAssembly:
    def test_freight_hazmat_surcharge_and_shortfall_cap(self, api):
        """PRD §3.5: "Below it, the charge assembles three parts: a base fee of 2,500 cents; a hazmat surcharge of 1,800 cents when any line's product carries a non-`NONE` `hazmat_class`; and a shortfall fee equal to the gap between the 50,000-cent minimum and the freightable amount, capped at 7,500 cents so that a near-miss order never pays more than the cap on that component."
        PRD §3.5: "The order's `invoiced_cents` is subtotal plus freight, and it freezes the moment the order is invoiced."

        Design: Corner/calculations/freight_hazmat_surcharge_and_shortfall_cap
        """
        set_clock("2026-06-01T00:00:00Z", api)
        branch = make_branch(api, branch_code="PHX-12", hazmat_storage_certified=True)
        account = make_account(
            api, account_number="DLR-8", hazmat_delivery_license_expiry="2027-01-01"
        )
        product = make_product(
            api, sku="ACID-M", product_family="CHEMICAL",
            hazmat_class="CORROSIVE_8", base_price_cents=30000,
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=5)
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="ROUTE_DELIVERY", route_date="2026-06-10",
            lines=[order_line(product["id"], 1)],
        )
        assert order["order_subtotal_cents"] == 30000
        # 2,500 base + 1,800 hazmat + min(50,000-30,000, 7,500) shortfall = 11,800
        assert order["freight_charge_cents"] == 11800, (
            f"freight = 2500 + 1800 + min(20000, 7500) = 11800: {order}"
        )
        assert order["invoiced_cents"] == 41800


class TestTierSeasonalPricing:
    def test_pricing_premier_tier_x_early_buy_x_qty(self, api):
        """PRD §3.5: "Apply the tier factor implied by `tier_at_confirm`: no discount for `PRO`, 5% for `ELITE`, 10% for `PREMIER`."
        PRD §3.5: "If the order draws on a commitment, additionally apply the seasonal factor — the program's `early_buy_discount_pct` expressed as a fraction of a hundred; without a commitment that factor is zero."
        PRD §3.4: "The account's current tier is pinned onto the order as `tier_at_confirm`, and prices are computed against that snapshot even if the live tier later moves."
        PRD §3.5: "Counter orders pay no freight: `freight_charge_cents` is zero for `WILL_CALL`."

        Design: Difficulty/combinatorial_formula/pricing_tier_x_seasonal_x_qty_mode_a
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, branch_code="PHX-12", hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-300")
        product = make_product(
            api, sku="TAB-3IN", product_family="CHEMICAL", base_price_cents=10000
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=50000)
        seed_account_tier(
            account["id"], branch["id"], "PREMIER", api,
            pickup_slot="2026-01-10T14:00:00Z",
        )
        program, commitment = make_open_program_with_commitment(
            branch["id"], account["id"], 500, api,
            program_name="2026 Early-Buy", early_buy_discount_pct=20,
            pool_cap_units=10000,
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="WILL_CALL", requested_pickup_slot="2026-01-10T15:00:00Z",
            commitment_id=commitment["id"],
            lines=[order_line(product["id"], 3)],
        )
        lines = get_order_lines(order["id"], api)
        assert len(lines) == 1
        # 10,000 x 0.90 (PREMIER) x 0.80 (early-buy 20%) = 7,200 per unit
        assert lines[0]["unit_price_cents"] == 7200, (
            f"unit price is base x tier factor x seasonal factor: {lines[0]}"
        )
        assert lines[0]["extended_price_cents"] == 21600
        assert order["order_subtotal_cents"] == 21600
        assert order["freight_charge_cents"] == 0, "counter orders pay no freight"
        assert order["tier_at_confirm"] == "PREMIER", (
            f"PREMIER snapshot pinned at confirm: {order}"
        )

    def test_pricing_elite_tier_x_early_buy_x_qty(self, api):
        """PRD §3.5: "Apply the tier factor implied by `tier_at_confirm`: no discount for `PRO`, 5% for `ELITE`, 10% for `PREMIER`."
        PRD §3.5: "If the order draws on a commitment, additionally apply the seasonal factor — the program's `early_buy_discount_pct` expressed as a fraction of a hundred; without a commitment that factor is zero."
        PRD §3.5: "The unrounded unit price is the base price reduced by both factors multiplicatively."

        Design: Difficulty/combinatorial_formula/pricing_tier_x_seasonal_x_qty_mode_a
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-310")
        product = make_product(
            api, sku="TAB-1IN", product_family="CHEMICAL", base_price_cents=10000
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=500)
        seed_account_tier(
            account["id"], branch["id"], "ELITE", api,
            pickup_slot="2026-01-10T14:00:00Z",
        )
        _program, commitment = make_open_program_with_commitment(
            branch["id"], account["id"], 100, api,
            program_name="Early-Buy 10", early_buy_discount_pct=10,
            pool_cap_units=10000,
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="WILL_CALL", requested_pickup_slot="2026-01-10T16:00:00Z",
            commitment_id=commitment["id"],
            lines=[order_line(product["id"], 2)],
        )
        lines = get_order_lines(order["id"], api)
        # 10,000 x 0.95 (ELITE) x 0.90 (early-buy 10%) = 8,550 per unit
        assert lines[0]["unit_price_cents"] == 8550
        assert lines[0]["extended_price_cents"] == 17100
        assert order["order_subtotal_cents"] == 17100
        assert order["tier_at_confirm"] == "ELITE"


class TestPerLineRoundingOrder:
    def test_round_per_line_then_sum_qty_2(self, api):
        """PRD §3.5: "The line's `extended_price_cents` is the unrounded unit price times `qty`, rounded half up to whole cents — per line, before any summation."
        PRD §3.5: "The line's `unit_price_cents` is then derived from that rounded extended amount: the extended amount divided by `qty`, rounded half up."
        PRD §3.5: "The order's `order_subtotal_cents` is the sum of the per-line rounded extended amounts; summing unrounded amounts and rounding once would be a specification violation."

        Design: Difficulty/combinatorial_formula/pricing_per_line_round_then_sum_mode_b
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, branch_code="TUC-03", hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-301")
        product = make_product(
            api, sku="CL-SHOCK", product_family="CHEMICAL", base_price_cents=1051
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=1000)
        seed_account_tier(
            account["id"], branch["id"], "PREMIER", api,
            pickup_slot="2026-01-10T14:00:00Z",
        )
        _program, commitment = make_open_program_with_commitment(
            branch["id"], account["id"], 100, api,
            program_name="Chem Early-Buy 5", early_buy_discount_pct=5,
            pool_cap_units=10000,
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="WILL_CALL", requested_pickup_slot="2026-01-10T16:00:00Z",
            commitment_id=commitment["id"],
            lines=[order_line(product["id"], 2)],
        )
        lines = get_order_lines(order["id"], api)
        # unit_unrounded = 1051 x 0.90 x 0.95 = 898.605
        # extended = round_half_up(898.605 x 2) = round_half_up(1797.21) = 1797
        assert lines[0]["extended_price_cents"] == 1797, (
            f"round per line first: {lines[0]}"
        )
        # unit derived FROM the rounded line: round_half_up(1797 / 2) = 899
        assert lines[0]["unit_price_cents"] == 899, (
            f"unit derives from the rounded line, not the pre-rounded 898.605: {lines[0]}"
        )
        # The round-unit-first trap would give 899 x 2 = 1798.
        assert order["order_subtotal_cents"] == 1797, (
            f"subtotal sums rounded lines (not 1798): {order}"
        )

    def test_round_per_line_then_sum_qty_3(self, api):
        """PRD §3.5: "The line's `extended_price_cents` is the unrounded unit price times `qty`, rounded half up to whole cents — per line, before any summation."
        PRD §3.5: "The order's `order_subtotal_cents` is the sum of the per-line rounded extended amounts; summing unrounded amounts and rounding once would be a specification violation."

        Design: Difficulty/combinatorial_formula/pricing_per_line_round_then_sum_mode_b
        """
        set_clock("2026-01-10T00:00:00Z", api)
        branch = make_branch(api, hazmat_storage_certified=True)
        account = make_account(api, account_number="DLR-302")
        product = make_product(
            api, sku="CL-SHOCK", product_family="CHEMICAL", base_price_cents=1051
        )
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=1000)
        seed_account_tier(
            account["id"], branch["id"], "PREMIER", api,
            pickup_slot="2026-01-10T14:00:00Z",
        )
        _program, commitment = make_open_program_with_commitment(
            branch["id"], account["id"], 100, api,
            program_name="Chem Early-Buy 5", early_buy_discount_pct=5,
            pool_cap_units=10000,
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="WILL_CALL", requested_pickup_slot="2026-01-10T17:00:00Z",
            commitment_id=commitment["id"],
            lines=[order_line(product["id"], 3)],
        )
        lines = get_order_lines(order["id"], api)
        # extended = round_half_up(898.605 x 3) = round_half_up(2695.815) = 2696
        assert lines[0]["extended_price_cents"] == 2696
        # unit = round_half_up(2696 / 3) = round_half_up(898.666...) = 899
        assert lines[0]["unit_price_cents"] == 899
        # The round-unit-first trap would give 899 x 3 = 2697.
        assert order["order_subtotal_cents"] == 2696, (
            f"subtotal is 2696, not the trap value 2697: {order}"
        )
