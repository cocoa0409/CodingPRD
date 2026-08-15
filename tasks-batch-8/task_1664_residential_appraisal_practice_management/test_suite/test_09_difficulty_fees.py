"""Difficulty queue A: fee-quote dual variants, multi-branch fee composition,
pinned per-line rounding order, and the inclusive HIGH_VALUE threshold
(PRD 2.6, 3.3, 3.5)."""
from test_helpers import (
    accept_order,
    api_client,
    create_client,
    create_fee_schedule,
    create_fee_schedule_payload,
    create_order,
    get_client,
    get_order,
    set_clock,
    setup_order_in_analysis,
    validate_success,
)
from test_helpers import ADMIN
from test_helpers import create_comparable as create_comparable_fx


def api_scope(order_id):
    return api_client.determine_scope(order_id, {}, ADMIN)


def _setup_two_window_client():
    """Client with STANDARD windows A [07-01, 08-01T12:00) base 40000 and
    B [08-01T12:00, open) base 52000; one SFR order scoped under window A."""
    set_clock("2026-08-01T00:00:00Z")
    client = create_client(name="AMC One")
    create_fee_schedule(
        client["id"],
        base_fee_cents=40000,
        rush_multiplier_bps=1000,
        revision_fee_cents=12000,
        effective_from="2026-07-01T00:00:00Z",
        effective_to="2026-08-01T12:00:00Z",
    )
    order = create_order(client["id"], property_address="123 Main St")
    scoped = validate_success(api_scope(order["id"]), 200)
    create_fee_schedule(
        client["id"],
        base_fee_cents=52000,
        rush_multiplier_bps=1000,
        revision_fee_cents=12000,
        effective_from="2026-08-01T12:00:00Z",
    )
    return client, order, scoped


def test_fee_provisional_variant_uses_scope_time_window(api):
    """PRD 3.3: "The provisional variant of this recipe runs at scope
    determination with the logical clock as its as-of timestamp, and its
    result is stored in `fee_quoted_cents`."
    PRD 3.3: "The system selects the fee schedule for the order's client and
    its just-determined tier whose window contains the as-of timestamp —
    `effective_from` at or before that instant, and `effective_to` either
    unset or strictly after it — taking the base from that row's
    `base_fee_cents`".

    Design: Difficulty/dual_variant_calc/fee_quote_provisional_vs_final_on_schedule_supersede
    """
    _, _, scoped = _setup_two_window_client()
    # scoped at 2026-08-01T00:00 while window A (base 40000) was in force
    assert scoped["fee_quoted_cents"] == 40000


def test_fee_final_variant_reprices_after_schedule_supersede(api):
    """PRD 3.3: "Acceptance — again a `FirmAdmin` action, again requiring an
    `ACTIVE` client — moves `SCOPE_DETERMINED` to `ACCEPTED` and runs the
    final variant with the acceptance timestamp as its as-of, storing the
    result in `fee_current_cents`; whenever a superseding schedule window has
    taken effect between scope determination and acceptance, the final fee
    legitimately differs from the quote."

    Design: Difficulty/dual_variant_calc/fee_quote_provisional_vs_final_on_schedule_supersede
    """
    _, order, _ = _setup_two_window_client()
    set_clock("2026-08-03T00:00:00Z")
    accept_order(order["id"])

    accepted = get_order(order["id"])
    assert accepted["fee_quoted_cents"] == 40000, "provisional variant frozen"
    assert accepted["fee_current_cents"] == 52000, "final variant re-priced under window B"


def _setup_multifactor_order():
    """Client (default turn 7) with COMPLEX schedule base 45000 rush 2000bps;
    MULTI_2_4 FHA order with requested_turn_days 3."""
    set_clock("2026-08-01T00:00:00Z")
    client = create_client(name="AMC Four")
    create_fee_schedule(
        client["id"],
        complexity_tier="COMPLEX",
        base_fee_cents=45000,
        rush_multiplier_bps=2000,
    )
    order = create_order(
        client["id"],
        property_address="44 Duplex Way",
        property_type="MULTI_2_4",
        estimated_value_cents=80000000,
        loan_type="FHA",
        requested_turn_days=3,
    )
    return order


def test_fee_multifactor_tier_mapping(api):
    """PRD 3.3: "Otherwise the tier is `COMPLEX` when `property_type` is
    `MULTI_2_4` or `MANUFACTURED`."

    Design: Difficulty/combinatorial_formula/fee_quote_multifactor_tier_rush_addons_clamp
    """
    order = _setup_multifactor_order()
    scoped = validate_success(api_scope(order["id"]), 200)
    assert scoped["complexity_tier"] == "COMPLEX"


def test_fee_multifactor_full_composition(api):
    """PRD 3.3: "If the order's `requested_turn_days` is fewer than the
    client's `default_turn_time_days`, a rush premium is added: the base
    multiplied by the rush basis points and divided by ten thousand, rounded
    half-up to whole cents. A property surcharge follows — 15000 cents for
    `MULTI_2_4`, or 7500 cents for `MANUFACTURED` — and a government-loan
    surcharge of 5000 cents applies when `loan_type` is `FHA` or `VA`. The
    quote is finally bounded: raised to a floor of 35000 cents when below it,
    and capped at 150000 cents when above."

    Design: Difficulty/combinatorial_formula/fee_quote_multifactor_tier_rush_addons_clamp
    """
    order = _setup_multifactor_order()
    scoped = validate_success(api_scope(order["id"]), 200)
    # 45000 + round_half_up(45000*2000/10000)=9000 rush + 15000 MULTI_2_4
    # + 5000 FHA = 74000, inside the [35000, 150000] clamp
    assert scoped["fee_quoted_cents"] == 74000


def _setup_in_analysis_with_order():
    return setup_order_in_analysis()


def test_comp_per_line_rounding_moves_adjusted_price(api):
    """PRD 3.5: "Each of the four signed lines is rounded individually first:
    divided by 10000, rounded half-up to a whole number, and multiplied back
    by 10000, so every line lands on a whole hundred dollars before any
    summation takes place. Rounding the sum instead of the lines is
    non-conformant — the two orders of operation produce different cents."
    PRD 3.5: "The comparable's `adjusted_price_cents` is then its
    `sale_price_cents` plus the sum of the four rounded lines."

    Design: Difficulty/combinatorial_formula/comp_adjustment_per_line_rounding_before_summation
    """
    ctx = _setup_in_analysis_with_order()
    comp = create_comparable_fx(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="9 Rounding Rd",
        sale_price_cents=45250000,
        sale_date="2026-06-01",
        distance_miles=0.30,
        site_adjustment_cents=6000,
        gla_adjustment_cents=6000,
        condition_adjustment_cents=0,
    )
    # per-line: 6000 -> 10000 each; sum 20000; sum-first would give 10000
    assert comp["adjusted_price_cents"] == 45270000


def test_comp_per_line_rounding_drives_percentages(api):
    """PRD 3.5: "The `net_adjustment_pct` is the absolute value of that net
    sum divided by `sale_price_cents`, expressed as a percentage rounded
    half-up to two decimal places. The `gross_adjustment_pct` replaces the net
    sum with the sum of the four lines' absolute rounded values, divided by
    `sale_price_cents` and again expressed as a percentage rounded half-up to
    two decimal places."

    Design: Difficulty/combinatorial_formula/comp_adjustment_per_line_rounding_before_summation
    """
    ctx = _setup_in_analysis_with_order()
    comp = create_comparable_fx(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="9 Rounding Rd",
        sale_price_cents=45250000,
        sale_date="2026-06-01",
        distance_miles=0.30,
        site_adjustment_cents=6000,
        gla_adjustment_cents=6000,
        condition_adjustment_cents=0,
    )
    # net sum 20000; round_half_up(20000 * 10000 / 45250000) = 4 -> 0.04
    assert comp["net_adjustment_pct"] == 0.04
    assert comp["gross_adjustment_pct"] == 0.04


def _setup_tier_threshold_pair():
    """Client with only a STANDARD 45000 schedule; two SFR orders at the
    estimated-value threshold and one cent below it."""
    set_clock("2026-08-01T00:00:00Z")
    client = create_client(name="AMC Fourteen")
    create_fee_schedule(client["id"], base_fee_cents=45000)
    hi = create_order(
        client["id"], property_address="Edge Case 1", estimated_value_cents=100000000
    )
    lo = create_order(
        client["id"], property_address="Edge Case 2", estimated_value_cents=99999999
    )
    return hi, lo


def test_tier_threshold_exactly_1m_is_high_value(api):
    """PRD 3.3: "The computed `complexity_tier` is `HIGH_VALUE` when
    `estimated_value_cents` is at least 100000000 cents — the threshold is
    inclusive, so an estimate of exactly that amount yields `HIGH_VALUE`."
    PRD 3.3: "When no window matches, the retail rate card supplies a base of
    45000 cents for `STANDARD`, 60000 cents for `COMPLEX`, and 85000 cents
    for `HIGH_VALUE`, with a retail rush rate of 1500 basis points."

    Design: Difficulty/boundary_precision_check/tier_threshold_estimated_value_exactly_1m_is_high_value
    """
    hi, _ = _setup_tier_threshold_pair()
    scoped = validate_success(api_scope(hi["id"]), 200)
    assert scoped["complexity_tier"] == "HIGH_VALUE"
    # no HIGH_VALUE schedule on file -> retail fallback 85000
    assert scoped["fee_quoted_cents"] == 85000


def test_tier_threshold_one_cent_below_is_standard(api):
    """PRD 3.3: "Every remaining order is `STANDARD`."
    PRD 3.3: "The system selects the fee schedule for the order's client and
    its just-determined tier whose window contains the as-of timestamp —
    `effective_from` at or before that instant, and `effective_to` either
    unset or strictly after it — taking the base from that row's
    `base_fee_cents`".

    Design: Difficulty/boundary_precision_check/tier_threshold_estimated_value_exactly_1m_is_high_value
    """
    _, lo = _setup_tier_threshold_pair()
    scoped = validate_success(api_scope(lo["id"]), 200)
    assert scoped["complexity_tier"] == "STANDARD"
    assert scoped["fee_quoted_cents"] == 45000
