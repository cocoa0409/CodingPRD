"""Tiered line pricing and the pinned price-stack evaluation order (PRD §3.4)."""
from test_helpers import (
    TEST_USERS,
    agent,
    api_client,
    confirm,
    find_line_by_quantity,
    full_book_payload,
    make_active_book,
    make_customer,
    make_depot,
    make_order,
    make_surge_window,
    mini_cube_book_payload,
    mini_cube_pallet_book_payload,
    order_line,
    quote,
    set_logical_clock,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _lines(order_id, headers):
    """Order lines are exposed as a paginated sub-list of the order (PRD §3.4)."""
    data, _meta = validate_paginated(api_client.list_order_lines(order_id, headers))
    return data


# ---------------------------------------------------------------- corner ----

def test_order_computed_fields_from_lines(api):
    """PRD §3.4: "`pallets_required` sums, across lines, the `quantity_units`
    of each `PALLET`-packaged line plus — for `BAG`-packaged lines — the
    quantity divided by twenty and rounded up to a whole pallet space."
    PRD §3.1: "Tier rates are flat: whichever tier a quantity falls into prices
    the entire quantity at that tier's unit price, never marginally."

    Design: Corner/entities/order_computed_fields_from_lines
    """
    depot = make_depot(10, "Depot E6")
    set_logical_clock()
    make_active_book(mini_cube_book_payload())
    cust = make_customer(
        account_name="E6", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    order = make_order(
        cust["id"], depot["id"], [order_line("CUBE", "BAG", 21)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    assert order["pallets_required"] == 2, "ceil(21/20) pallet spaces"
    quoted = quote(order["id"], cust["id"])
    assert quoted["total_cents"] == 6300

    lines = _lines(order["id"], agent(cust["id"]))
    line = find_line_by_quantity(lines, 21)
    assert line["unit_weight_lbs"] == 7
    assert line["unit_price_cents"] == 300, "tier 20-99 flat rate"
    assert line["line_total_cents"] == 6300


def test_delivery_fee_threshold_applied(api):
    """PRD §3.4: "Fourth, `delivery_fee_cents` is zero for `WILL_CALL` orders,
    zero when the post-discount subtotal reaches the book's
    `free_delivery_threshold_cents`, and otherwise the book's
    `delivery_fee_cents`."

    Design: Corner/calculations/delivery_fee_threshold_applied
    """
    depot = make_depot(10, "Depot C25")
    set_logical_clock()
    make_active_book(mini_cube_book_payload())
    cust = make_customer(
        account_name="C25", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    o1 = make_order(
        cust["id"], depot["id"], [order_line("CUBE", "BAG", 25)],
        channel="DELIVERY", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    o2 = make_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="DELIVERY", event_date="2026-05-11",
        window_start="10:00", window_end="12:00",
    )
    q1 = quote(o1["id"], cust["id"])
    q2 = quote(o2["id"], cust["id"])
    assert q1["delivery_fee_cents"] == 4900 and q1["total_cents"] == 12400, (
        "post-discount 7500 < 20000: fee applies"
    )
    assert q2["delivery_fee_cents"] == 0 and q2["total_cents"] == 22500, (
        "post-discount 21000 >= 20000: fee waived, deposit 1500 added"
    )


def test_deposit_exempt_from_discount(api):
    """PRD §3.4: "Sixth, `deposit_cents` sums, over `PALLET` lines, the
    quantity times the book's `pallet_deposit_cents` — the deposit is exempt
    from both the discount base and the surcharge base."

    Design: Corner/calculations/deposit_exempt_from_discount
    """
    depot = make_depot(10, "Depot C26")
    set_logical_clock()
    make_active_book(mini_cube_pallet_book_payload())
    cust = make_customer(
        account_name="C26", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    order = make_order(
        cust["id"], depot["id"], [order_line("CUBE", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    quoted = quote(order["id"], cust["id"])
    assert quoted["merchandise_subtotal_cents"] == 56000
    assert quoted["discount_cents"] == 2800, "5% of merchandise only"
    assert quoted["deposit_cents"] == 3000
    assert quoted["total_cents"] == 56200, "56000 - 2800 + 0 + 0 + 3000"


# ------------------------------------------------- difficulty: tiered lines ----

def test_dry_ice_handling_folded_before_rounding(api):
    """PRD §3.4: "Dry-ice lines additionally absorb a handling premium of seven
    percent — 700 basis points — folded into the line total before rounding".
    PRD §3.1: "Tier rates are flat: whichever tier a quantity falls into prices
    the entire quantity at that tier's unit price, never marginally."

    Design: Difficulty/combinatorial_formula/tiered_line_pricing_multi_input
    """
    depot = make_depot(10, "Depot CF-a")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="CF Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    order = make_order(
        cust["id"], depot["id"],
        [order_line("DRY_ICE", "BAG", 13), order_line("DRY_ICE", "BAG", 9)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    quoted = quote(order["id"], cust["id"])
    assert quoted["merchandise_subtotal_cents"] == 33224
    assert quoted["total_cents"] == 33224, (
        "WILL_CALL: no fee; no discount tier below 50000; no deposit for BAG"
    )

    lines = _lines(order["id"], agent(cust["id"]))
    line13 = find_line_by_quantity(lines, 13)
    assert line13["unit_price_cents"] == 1350, "tier 10-49 flat rate"
    assert line13["line_total_cents"] == 18779, "round_half_up(13*1350*1.07)"
    line9 = find_line_by_quantity(lines, 9)
    assert line9["unit_price_cents"] == 1500, "tier 1-9 flat rate"
    assert line9["line_total_cents"] == 14445, "round_half_up(9*1500*1.07)"


def test_dry_ice_tier_edges_and_exact_non_dry_lines(api):
    """PRD §3.1: "Tier rates are flat: whichever tier a quantity falls into
    prices the entire quantity at that tier's unit price, never marginally."
    PRD §3.4: "Every line's `line_total_cents` is rounded half up to a whole
    cent individually, before any summation; non-dry-ice lines, being exact
    integer products, are unaffected by that rounding."

    Design: Difficulty/combinatorial_formula/tiered_line_pricing_multi_input
    """
    depot = make_depot(10, "Depot CF-a2")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="CF Edges", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    order = make_order(
        cust["id"], depot["id"],
        [
            order_line("DRY_ICE", "BAG", 10),
            order_line("DRY_ICE", "BAG", 50),
            order_line("BLOCK", "PALLET", 1),
        ],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    quote(order["id"], cust["id"])

    lines = _lines(order["id"], agent(cust["id"]))
    line10 = find_line_by_quantity(lines, 10)
    assert line10["unit_price_cents"] == 1350, "10 units enters tier 10-49"
    assert line10["line_total_cents"] == 14445, "round_half_up(10*1350*1.07)"
    line50 = find_line_by_quantity(lines, 50)
    assert line50["unit_price_cents"] == 1200, "50 units enters tier 50+"
    assert line50["line_total_cents"] == 64200, "round_half_up(50*1200*1.07)"
    line_block = find_line_by_quantity(lines, 1)
    assert line_block["unit_price_cents"] == 21000
    assert line_block["line_total_cents"] == 21000, "exact integer product"
    assert line_block["unit_weight_lbs"] == 300


# ------------------------------------- difficulty: discount/surcharge order ----

def test_discount_pre_discount_base_surcharge_post_discount(api):
    """PRD §3.4: "Second, `discount_cents` comes from the
    `volume_discount_tiers`: the highest row whose `threshold_cents` the
    pre-discount subtotal reaches supplies its `discount_bps`, and the discount
    is the subtotal times those basis points divided by ten thousand, rounded
    half up — no satisfied tier means no discount."
    PRD §3.4: "Fifth, when a surge window covering the event date is `ACTIVE`
    at evaluation time, `surcharge_cents` is the post-discount subtotal times
    the book's `surge_surcharge_bps` divided by ten thousand, rounded half up;
    otherwise the surcharge is zero."

    Design: Difficulty/combinatorial_formula/discount_then_surcharge_evaluation_order
    """
    depot = make_depot(10, "Depot CF-c")
    set_logical_clock()
    make_active_book(full_book_payload())
    make_surge_window(depot["id"], "2026-05-01", "2026-06-15", "OPEN")
    cust = make_customer(
        account_name="CF-c Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    order = make_order(
        cust["id"], depot["id"],
        [order_line("CUBE", "BAG", 30), order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    quote(order["id"], cust["id"])
    confirmed = confirm(order["id"], cust["id"])
    assert confirmed["merchandise_subtotal_cents"] == 51000
    assert confirmed["discount_cents"] == 2550, (
        "round_half_up(51000 * 500bps), keyed on PRE-discount merchandise"
    )
    assert confirmed["surcharge_cents"] == 7268, (
        "round_half_up((51000-2550) * 1500bps) on the POST-discount base"
    )
    assert confirmed["delivery_fee_cents"] == 0, "WILL_CALL"
    assert confirmed["deposit_cents"] == 3000, "2 pallets x 1500, exempt"
    assert confirmed["total_cents"] == 58718, "51000 - 2550 + 0 + 7268 + 3000"


def test_highest_satisfied_discount_tier_wins_with_surcharge(api):
    """PRD §3.4: "the highest row whose `threshold_cents` the pre-discount
    subtotal reaches supplies its `discount_bps`".
    PRD §3.4: "Fifth, when a surge window covering the event date is `ACTIVE`
    at evaluation time, `surcharge_cents` is the post-discount subtotal times
    the book's `surge_surcharge_bps` divided by ten thousand, rounded half up;
    otherwise the surcharge is zero."

    Design: Difficulty/combinatorial_formula/discount_then_surcharge_evaluation_order
    """
    depot = make_depot(10, "Depot CF-c2")
    set_logical_clock()
    make_active_book(full_book_payload())
    make_surge_window(depot["id"], "2026-05-01", "2026-06-15", "OPEN")
    cust = make_customer(
        account_name="CF-c2 Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    order = make_order(
        cust["id"], depot["id"],
        [order_line("BLOCK", "PALLET", 4), order_line("CUBE", "BAG", 100)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    quote(order["id"], cust["id"])
    confirmed = confirm(order["id"], cust["id"])
    assert confirmed["merchandise_subtotal_cents"] == 111500
    assert confirmed["discount_cents"] == 11150, (
        "111500 >= 100000: the 1000bps tier wins over the 500bps tier"
    )
    assert confirmed["surcharge_cents"] == 15053, (
        "round_half_up((111500-11150) * 1500bps) = round_half_up(15052.5)"
    )
    assert confirmed["deposit_cents"] == 6000
    assert confirmed["total_cents"] == 121403, "111500 - 11150 + 0 + 15053 + 6000"


# ------------------------------------- difficulty: provisional vs final ----

def test_provisional_vs_final_totals_diverge_with_surge_adoption(api):
    """PRD §3.4: "The `PROVISIONAL` variant, produced by quoting and repricing,
    reads the book `ACTIVE` at evaluation time and treats the surcharge as
    applicable when a covering window is `ACTIVE` at that same moment; the
    result is stored on the order and returned in the quote response."
    PRD §3.4: "The `FINAL` variant, produced by confirmation and waitlist
    promotion, keeps the order's pinned book for lines, discount, fee, and
    deposit even if that book has since been superseded, and re-evaluates surge
    coverage at the confirmation or promotion moment."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_surge_adoption
    """
    depot = make_depot(10, "Depot DV")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="DV Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    order = make_order(
        cust["id"], depot["id"],
        [order_line("CUBE", "BAG", 30), order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    quoted = quote(order["id"], cust["id"])
    assert quoted["pricing_mode"] == "PROVISIONAL"
    assert quoted["total_cents"] == 51450 and quoted["surcharge_cents"] == 0, (
        "no ACTIVE surge window at quote time"
    )

    make_surge_window(depot["id"], "2026-05-15", "2026-06-15", "OPEN")
    set_logical_clock("2026-05-16T09:00:00Z")

    confirmed = confirm(order["id"], cust["id"])
    assert confirmed["pricing_mode"] == "FINAL"
    assert confirmed["total_cents"] == 58718
    assert confirmed["surcharge_cents"] == 7268, (
        "round_half_up(48450 * 0.15): window ACTIVE at confirm time"
    )
    assert confirmed["discount_cents"] == 2550
    assert confirmed["deposit_cents"] == 3000
    assert confirmed["delivery_fee_cents"] == 0
    assert quoted["total_cents"] != confirmed["total_cents"], (
        "identical lines legitimately price differently across variants"
    )


def test_final_variant_without_active_surge_keeps_zero_surcharge(api):
    """PRD §3.4: "The `FINAL` variant, produced by confirmation and waitlist
    promotion, keeps the order's pinned book for lines, discount, fee, and
    deposit even if that book has since been superseded, and re-evaluates surge
    coverage at the confirmation or promotion moment."
    PRD §3.4: "otherwise the surcharge is zero."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_surge_adoption
    """
    depot = make_depot(10, "Depot DV2")
    set_logical_clock()
    make_active_book(full_book_payload())
    cust = make_customer(
        account_name="DV2 Events", kind="EVENT_ORGANIZER", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=500000,
    )
    order = make_order(
        cust["id"], depot["id"],
        [order_line("CUBE", "BAG", 30), order_line("BLOCK", "PALLET", 2)],
        channel="WILL_CALL", event_date="2026-05-20",
        window_start="10:00", window_end="12:00",
    )
    quoted = quote(order["id"], cust["id"])
    # Surge window starts 2026-05-15: still SCHEDULED at confirm (clock stays
    # 2026-05-01), so the FINAL evaluation finds no ACTIVE covering window.
    make_surge_window(depot["id"], "2026-05-15", "2026-06-15", "OPEN")

    confirmed = confirm(order["id"], cust["id"])
    assert confirmed["pricing_mode"] == "FINAL"
    assert confirmed["surcharge_cents"] == 0, (
        "window SCHEDULED at confirm time: surcharge not applicable"
    )
    assert confirmed["total_cents"] == 51450
    assert confirmed["discount_cents"] == 2550
    assert confirmed["deposit_cents"] == 3000
