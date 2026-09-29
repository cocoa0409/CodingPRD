"""Two order-money formulas of the Winery DTC contract whose step order is pinned.

The first pair pins the sales-tax rounding order of PRD §2.7 and §3.5: two lines
whose taxable bases are each exactly 10,008 cents at 825 basis points must be
rounded per line and then summed to 1,652 cents, not summed to 20,016 cents and
rounded once to 1,651.

The second pair pins the handling-fee waiver of PRD §3.5 step 11: the waiver
comparison reads ``pre_fee_total_cents``, so a club order at 19,119 cents pays
the 900-cent fee and totals 20,019 cents.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import DtcApiClient  # noqa: F401  (fixture type)
from test_helpers.assertions import (
    assert_cents,
    assert_charge_chain,
    assert_liters,
    assert_order_dimensions,
)
from test_helpers.constants import (
    CLOCK_STARTUP_DEFAULT,
    CLUB_SHIPPING_DISCOUNT_BPS,
    COMPLIANCE_HANDLING_FEE_CENTS,
    FEE_WAIVER_THRESHOLD_CENTS,
    LITER_TIER_1_MAX_L,
    SHIPPING_BASE_CENTS,
    SHIPPING_PER_LITER_CENTS,
    STATE_RULE_TX,
)
from test_helpers.fixtures import (
    consumer_version,
    create_consumer,
    create_state_rule,
    create_winery,
    set_clock,
)
from test_helpers.test_users import OFFICER_A, make_winery_operator_headers

# ===========================================================================
# sales_tax_round_per_line_then_sum_beats_sum_then_round
#
# Two lines of 3 x 750 ml at 2921 c, recomputed from the PRD §3.5 chain:
#   line_liters       3 * 750 / 1000                      = 2.250 L each
#   line_subtotal     3 * 2921                            = 8763 c each
#   total_liters      2.250 + 2.250                       = 4.500 L
#   subtotal          8763 + 8763                         = 17526 c
#   shipping_gross    round_half_up(1500 + 220 * 4.500)   = 2490 c
#   tier              4.500 <= 9.000                      -> x1.00
#   shipping_tiered   round_half_up(2490 * 1.00)          = 2490 c
#   discount          club_subscription_id is null        = 0 c
#   shipping          2490 - 0                            = 2490 c
#   excise base       round_half_up(4.500 * 55)           = 248 c
#   surcharge         no line strictly above 1500 ml      = 0 c
#   credit           round_half_up(248 * 1500 / 10000)    = 37 c
#   excise            min(248 - 37, 100000)               = 211 c
#   pool              shipping 2490 (tax_on_shipping),
#                     excise excluded (excise_in_tax_base false) = 2490 c
#   raw share         2490 * 2.250 / 4.500 = 1245.0 -> trunc = 1245 c each
#   remainder         2490 - (1245 + 1245)                = 0 c
#   line_taxable      8763 + 1245                         = 10008 c each
#   line_sales_tax    round_half_up(10008 * 825 / 10000)
#                     = round_half_up(825.66)             = 826 c each
#   sales_tax         826 + 826                           = 1652 c
#                     (summing the bases first would give
#                      round_half_up(20016 * 825 / 10000) = 1651 c)
#   pre_fee_total     17526 + 2490 + 211 + 1652           = 21879 c (>= 20000)
#   handling fee      pre_fee_total >= 20000              = 0 c
#   total             21879 + 0                           = 21879 c
# ===========================================================================
TWO_LINE_LITERS = 4.500
TWO_LINE_SUBTOTAL_CENTS = 17526
TWO_LINE_SHIPPING_CENTS = 2490
TWO_LINE_EXCISE_CENTS = 211
LINE_ALLOCATED_SHIPPING_CENTS = 1245
LINE_TAXABLE_CENTS = 10008
LINE_SALES_TAX_CENTS = 826
TWO_LINE_SALES_TAX_CENTS = 1652
TWO_LINE_SALES_TAX_IF_SUMMED_FIRST_CENTS = 1651
TWO_LINE_PRE_FEE_TOTAL_CENTS = 21879
TWO_LINE_TOTAL_CENTS = 21879

TWO_EQUAL_LINES = [
    f.order_line(sku="CAB-750", bottle_ml=750, bottles=3, unit_price_cents=2921),
    f.order_line(sku="MER-750", bottle_ml=750, bottles=3, unit_price_cents=2921),
]


def _build_money_only_landscape(api):
    """Clock, winery, TX rule and a consumer — everything the chain needs.

    Every money field is frozen by ``POST /dtc/orders`` (PRD §3.5), so no permit,
    carrier enrollment or screening is involved in these tests.
    """
    set_clock(api, CLOCK_STARTUP_DEFAULT)
    winery = create_winery(api)
    state_rule = create_state_rule(api)
    consumer = create_consumer(api)
    return winery, state_rule, consumer


def _create_order(api, winery_id, consumer_id, lines, **overrides):
    payload = f.order_payload(
        winery_id, consumer_id,
        consumer_version(api, consumer_id, OFFICER_A),
        lines=lines,
        **overrides,
    )
    response = api.create_order(payload, make_winery_operator_headers(winery_id))
    return validate_success(response, 201)


def test_two_equal_lines_round_sales_tax_per_line_then_sum(api):
    """Two 10,008-cent bases at 825 bps must total 1,652 cents, never 1,651.

    PRD §2.7: "These two orders give different totals and the difference is not
    negligible: two lines whose taxable bases are each 10,008 cents, taxed at
    825 basis points, produce 826 cents plus 826 cents — 1,652 cents — when each
    line is rounded and then summed, but 1,651 cents when the bases are summed
    and the result rounded once."

    PRD §2.7: "The per-line-then-sum order is the one this system uses for sales
    tax."

    PRD §3.5: "The order's `sales_tax_cents` is the sum of the per-line figures."

    Design: Difficulty/combinatorial_formula/sales_tax_round_per_line_then_sum_beats_sum_then_round
    """
    winery, state_rule, consumer = _build_money_only_landscape(api)
    assert state_rule["sales_tax_rate_bps"] == 825
    assert state_rule["tax_on_shipping"] is True
    assert state_rule["excise_in_tax_base"] is False

    order = _create_order(api, winery["id"], consumer["id"], TWO_EQUAL_LINES)

    assert_order_dimensions(order, compliance_status="DRAFT",
                            fulfillment_status="UNFULFILLED")
    assert_charge_chain(
        order,
        total_liters=TWO_LINE_LITERS,
        subtotal_cents=TWO_LINE_SUBTOTAL_CENTS,
        shipping_gross_cents=TWO_LINE_SHIPPING_CENTS,
        shipping_tiered_cents=TWO_LINE_SHIPPING_CENTS,
        shipping_discount_cents=0,
        shipping_cents=TWO_LINE_SHIPPING_CENTS,
        excise_tax_cents=TWO_LINE_EXCISE_CENTS,
        sales_tax_cents=TWO_LINE_SALES_TAX_CENTS,
        pre_fee_total_cents=TWO_LINE_PRE_FEE_TOTAL_CENTS,
        compliance_handling_fee_cents=0,
        total_cents=TWO_LINE_TOTAL_CENTS,
    )
    # The whole point of the pinning: not the sum-then-round answer.
    assert order["sales_tax_cents"] != TWO_LINE_SALES_TAX_IF_SUMMED_FIRST_CENTS
    # 21879 c is at or above the waiver threshold, so no fee is charged here.
    assert order["pre_fee_total_cents"] >= FEE_WAIVER_THRESHOLD_CENTS
    # 1500 + 220 * 4.500 = 2490 c at tier x1.00.
    assert (
        SHIPPING_BASE_CENTS + round(SHIPPING_PER_LITER_CENTS * TWO_LINE_LITERS)
        == TWO_LINE_SHIPPING_CENTS
    )
    assert TWO_LINE_LITERS <= LITER_TIER_1_MAX_L


def test_per_line_allocation_and_taxable_bases_on_the_lines_read(api):
    """The waterfall splits the 2,490-cent pool 1,245/1,245 with no remainder.

    PRD §3.5: "Each line's raw share of that pool is the pool multiplied by the
    line's `line_liters` divided by the order's `total_liters`; the line's
    `allocated_shipping_cents` is that raw share truncated downward to a whole
    cent."

    PRD §3.5: "Each line's `line_taxable_cents` is then its
    `line_subtotal_cents` plus its final `allocated_shipping_cents`, and its
    `line_sales_tax_cents` is `line_taxable_cents` multiplied by the state's
    `sales_tax_rate_bps` divided by 10,000, rounded half up to whole cents."

    PRD §3.5: "Creation records one line per element of the `lines` array and
    assigns each an `order_id` pointing back at the order plus a `line_index`
    running from 1 upward in exactly the request's array order."

    Design: Difficulty/combinatorial_formula/sales_tax_round_per_line_then_sum_beats_sum_then_round
    """
    winery, _, consumer = _build_money_only_landscape(api)

    order = _create_order(api, winery["id"], consumer["id"], TWO_EQUAL_LINES)

    lines, _meta = validate_paginated(
        api.list_order_lines(order["id"], OFFICER_A, {"limit": 100})
    )
    assert len(lines) == 2
    assert [line["line_index"] for line in lines] == [1, 2]
    assert [line["sku"] for line in lines] == ["CAB-750", "MER-750"]

    for line in lines:
        assert line["order_id"] == order["id"]
        assert_liters(line["line_liters"], 2.250, "line_liters")
        assert_cents(line["line_subtotal_cents"], 8763, "line_subtotal_cents")
        # 2490 * 2.250 / 4.500 = 1245.0 exactly, so nothing is left over.
        assert_cents(line["allocated_shipping_cents"],
                     LINE_ALLOCATED_SHIPPING_CENTS, "allocated_shipping_cents")
        assert_cents(line["line_taxable_cents"], LINE_TAXABLE_CENTS,
                     "line_taxable_cents")
        assert_cents(line["line_sales_tax_cents"], LINE_SALES_TAX_CENTS,
                     "line_sales_tax_cents")

    allocated_total = sum(line["allocated_shipping_cents"] for line in lines)
    assert allocated_total == TWO_LINE_SHIPPING_CENTS

    per_line_total = sum(line["line_sales_tax_cents"] for line in lines)
    assert per_line_total == TWO_LINE_SALES_TAX_CENTS
    frozen = get_success_data(api.get_order(order["id"], OFFICER_A))
    assert_cents(frozen["sales_tax_cents"], per_line_total, "sales_tax_cents")


# ===========================================================================
# handling_fee_waiver_uses_pre_fee_total_pinned_order
#
# One club line of 6 x 750 ml at 2600 c, recomputed from the PRD §3.5 chain:
#   total_liters      6 * 750 / 1000                      = 4.500 L
#   subtotal          6 * 2600                            = 15600 c
#   shipping_gross    round_half_up(1500 + 220 * 4.500)   = 2490 c
#   tier              4.500 <= 9.000                      -> x1.00
#   shipping_tiered   round_half_up(2490 * 1.00)          = 2490 c
#   discount          round_half_up(2490 * 2500 / 10000)
#                     = round_half_up(622.5)              = 623 c
#   shipping          2490 - 623                          = 1867 c
#   excise base       round_half_up(4.500 * 55)           = 248 c
#   surcharge         no line strictly above 1500 ml      = 0 c
#   credit            round_half_up(248 * 1500 / 10000)   = 37 c
#   excise            min(248 - 37, 100000)               = 211 c
#   pool              shipping 1867 (tax_on_shipping),
#                     excise excluded                     = 1867 c
#   allocated         1867 * 4.500 / 4.500 -> trunc       = 1867 c
#   line_taxable      15600 + 1867                        = 17467 c
#   line_sales_tax    round_half_up(17467 * 825 / 10000)
#                     = round_half_up(1441.0275)          = 1441 c
#   sales_tax         1441 c
#   pre_fee_total     15600 + 1867 + 211 + 1441           = 19119 c
#   handling fee      19119 < 20000                       = 900 c
#   total             19119 + 900                         = 20019 c
# ===========================================================================
CLUB_LITERS = 4.500
CLUB_SUBTOTAL_CENTS = 15600
CLUB_SHIPPING_GROSS_CENTS = 2490
CLUB_SHIPPING_TIERED_CENTS = 2490
CLUB_SHIPPING_DISCOUNT_CENTS = 623
CLUB_SHIPPING_CENTS = 1867
CLUB_EXCISE_CENTS = 211
CLUB_LINE_TAXABLE_CENTS = 17467
CLUB_SALES_TAX_CENTS = 1441
CLUB_PRE_FEE_TOTAL_CENTS = 19119
CLUB_TOTAL_CENTS = 20019
CLUB_TOTAL_IF_FEE_WAIVED_CENTS = 19119

CLUB_LINE = [
    f.order_line(sku="CLUB-750", bottle_ml=750, bottles=6, unit_price_cents=2600)
]


def _build_club_money_landscape(api):
    """Clock, winery, TX rule, a STANDARD-tier consumer and one subscription."""
    set_clock(api, CLOCK_STARTUP_DEFAULT)
    winery = create_winery(api)
    state_rule = create_state_rule(api)
    consumer = create_consumer(api)
    subscription = get_success_data(
        api.create_club_subscription(
            f.club_subscription_payload(
                consumer["id"], winery["id"],
                next_run_date="2026-08-15",
                cadence="MONTHLY",
                sku="CLUB-750",
                bottles_per_shipment=6,
                bottle_ml=750,
                unit_price_cents=2600,
                annual_allotment=12,
            ),
            make_winery_operator_headers(winery["id"]),
        ),
        201,
    )
    return winery, state_rule, consumer, subscription


def test_club_order_applies_the_tier_multiplier_before_the_club_discount(api):
    """The 2,500 bps concession is taken off the tiered gross, giving 623 cents.

    PRD §3.5: "`shipping_discount_cents` is the wine-club shipping concession:
    when `club_subscription_id` is not null it is 2,500 basis points — one
    quarter — of `shipping_tiered_cents`, rounded half up to whole cents; when
    `club_subscription_id` is null it is 0."

    PRD §3.5: "The liter-tier multiplier is applied to the gross shipping charge
    **before** the club discount is taken, not after."

    PRD §3.5: "`shipping_cents` is `shipping_tiered_cents` less
    `shipping_discount_cents`."

    Design: Difficulty/combinatorial_formula/handling_fee_waiver_uses_pre_fee_total_pinned_order
    """
    winery, _, consumer, subscription = _build_club_money_landscape(api)
    assert subscription["status"] == "ACTIVE"
    assert CLUB_SHIPPING_DISCOUNT_BPS == 2500

    order = _create_order(
        api, winery["id"], consumer["id"], CLUB_LINE,
        club_subscription_id=subscription["id"],
    )

    assert order["club_subscription_id"] == subscription["id"]
    assert_charge_chain(
        order,
        total_liters=CLUB_LITERS,
        subtotal_cents=CLUB_SUBTOTAL_CENTS,
        shipping_gross_cents=CLUB_SHIPPING_GROSS_CENTS,
        shipping_tiered_cents=CLUB_SHIPPING_TIERED_CENTS,
        shipping_discount_cents=CLUB_SHIPPING_DISCOUNT_CENTS,
        shipping_cents=CLUB_SHIPPING_CENTS,
        excise_tax_cents=CLUB_EXCISE_CENTS,
        sales_tax_cents=CLUB_SALES_TAX_CENTS,
    )
    # round_half_up(2490 * 0.25) = round_half_up(622.5) = 623, not 622.
    assert order["shipping_discount_cents"] == CLUB_SHIPPING_DISCOUNT_CENTS
    assert (
        order["shipping_tiered_cents"] - order["shipping_discount_cents"]
        == order["shipping_cents"]
    )


def test_handling_fee_waiver_reads_pre_fee_total_and_not_the_grown_total(api):
    """19,119 cents is short of the threshold, so the 900-cent fee applies.

    PRD §3.5: "`compliance_handling_fee_cents` is 0 when `pre_fee_total_cents`
    is at least 20,000 cents — two hundred dollars — and otherwise 900 cents."

    PRD §3.5: "The waiver comparison reads `pre_fee_total_cents`, and
    `pre_fee_total_cents` is the **only** quantity in the system ever compared
    against the two-hundred-dollar waiver threshold."

    PRD §3.5: "Adding the fee first and then testing the resulting `total_cents`
    would flip the decision for every order whose `pre_fee_total_cents` lands
    between 19,100 cents inclusive and 20,000 cents exclusive: the fee would be
    waived and `total_cents` would come out 900 cents lower than it should."

    Design: Difficulty/combinatorial_formula/handling_fee_waiver_uses_pre_fee_total_pinned_order
    """
    winery, _, consumer, subscription = _build_club_money_landscape(api)

    order = _create_order(
        api, winery["id"], consumer["id"], CLUB_LINE,
        club_subscription_id=subscription["id"],
    )

    # pre_fee_total_cents = 15600 + 1867 + 211 + 1441 = 19119 c.
    assert_cents(order["pre_fee_total_cents"], CLUB_PRE_FEE_TOTAL_CENTS,
                 "pre_fee_total_cents")
    assert (
        order["subtotal_cents"]
        + order["shipping_cents"]
        + order["excise_tax_cents"]
        + order["sales_tax_cents"]
        == order["pre_fee_total_cents"]
    )
    # Squarely inside the 19,100-to-20,000 band the PRD calls out.
    assert 19100 <= order["pre_fee_total_cents"] < FEE_WAIVER_THRESHOLD_CENTS

    assert_cents(order["compliance_handling_fee_cents"],
                 COMPLIANCE_HANDLING_FEE_CENTS,
                 "compliance_handling_fee_cents")
    assert_cents(order["total_cents"], CLUB_TOTAL_CENTS, "total_cents")
    assert (
        order["pre_fee_total_cents"] + order["compliance_handling_fee_cents"]
        == order["total_cents"]
    )
    # A post-fee comparison would have waived the fee and returned 19119 c.
    assert order["total_cents"] != CLUB_TOTAL_IF_FEE_WAIVED_CENTS
    # And the grown total is itself at or above the threshold, which is exactly
    # why the comparison must not be made against it.
    assert order["total_cents"] >= FEE_WAIVER_THRESHOLD_CENTS


def test_club_order_single_line_carries_the_whole_discounted_shipping_pool(api):
    """The one line absorbs all 1,867 cents of discounted shipping.

    PRD §3.5: "First the pool is assembled: it consists of `shipping_cents` when
    the state's `tax_on_shipping` is true and nothing otherwise, plus
    `excise_tax_cents` when the state's `excise_in_tax_base` is true and nothing
    otherwise."

    PRD §3.5: "The `compliance_handling_fee_cents` never enters the sales-tax
    base under any state's configuration."

    Design: Difficulty/combinatorial_formula/handling_fee_waiver_uses_pre_fee_total_pinned_order
    """
    winery, state_rule, consumer, subscription = _build_club_money_landscape(api)
    assert state_rule["tax_on_shipping"] is True
    assert state_rule["excise_in_tax_base"] is False
    assert STATE_RULE_TX["sales_tax_rate_bps"] == 825

    order = _create_order(
        api, winery["id"], consumer["id"], CLUB_LINE,
        club_subscription_id=subscription["id"],
    )

    lines, _meta = validate_paginated(
        api.list_order_lines(order["id"], OFFICER_A, {"limit": 100})
    )
    assert len(lines) == 1
    line = lines[0]
    assert line["line_index"] == 1
    assert_liters(line["line_liters"], CLUB_LITERS, "line_liters")
    assert_cents(line["line_subtotal_cents"], CLUB_SUBTOTAL_CENTS,
                 "line_subtotal_cents")
    # The pool is the discounted shipping figure, never the 2490 c gross.
    assert_cents(line["allocated_shipping_cents"], CLUB_SHIPPING_CENTS,
                 "allocated_shipping_cents")
    assert_cents(line["line_taxable_cents"], CLUB_LINE_TAXABLE_CENTS,
                 "line_taxable_cents")
    assert_cents(line["line_sales_tax_cents"], CLUB_SALES_TAX_CENTS,
                 "line_sales_tax_cents")
    # The 900 c handling fee is nowhere in the taxable base.
    assert (
        line["line_taxable_cents"]
        == line["line_subtotal_cents"] + line["allocated_shipping_cents"]
    )
