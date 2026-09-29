"""Seller standing: the two recovery bases, the per-line payout and the tier threshold."""

from test_helpers import (
    assert_analytics_envelope,
    auction_listing_payload,
    book_appointment,
    bootstrap_marketplace,
    complete_appointment,
    create_listing,
    create_lot_with_lines,
    fixed_price_listing_payload,
    publish_listing,
    read_analytics,
    read_lot,
    read_order,
    read_seller,
    setup_approved_lot,
    setup_fixed_price_order,
    setup_paid_fixed_price_order,
    setup_picked_up_order,
)

# Lot X: one line of 100 x 100000 - 100 units, 10,000,000 cents of declared retail.
BIG_TICKET_LINES = [
    {
        "sku": "OVR-BIG-0100",
        "unit_count": 100,
        "unit_retail_cents": 100_000,
        "declared_condition": "NEW",
    },
]

# Lot Y: one line of 40 x 100000 - 4,000,000 cents of declared retail, never sold.
UNSOLD_LOT_LINES = [
    {
        "sku": "OVR-BIG-0040",
        "unit_count": 40,
        "unit_retail_cents": 100_000,
        "declared_condition": "NEW",
    },
]

# Lot D: three lines whose hammer shares do not terminate - 445 units, 5,750,240 cents.
LOT_D_LINES = [
    {
        "sku": "OVR-D-0075",
        "unit_count": 75,
        "unit_retail_cents": 19_999,
        "declared_condition": "NEW",
    },
    {
        "sku": "OVR-D-0325",
        "unit_count": 325,
        "unit_retail_cents": 10_001,
        "declared_condition": "NEW",
    },
    {
        "sku": "OVR-D-0045",
        "unit_count": 45,
        "unit_retail_cents": 22_222,
        "declared_condition": "NEW",
    },
]

PICKUP_START = "2026-08-10T14:00:00Z"
PICKUP_END = "2026-08-10T15:00:00Z"


def _sold_lot_plus_unpublished_lot():
    """One lot carried through pickup, plus a second approved lot whose AUCTION listing
    is still DRAFT."""
    sold = setup_picked_up_order(
        sale="fixed_price", ask_price_cents=2_700_000, lines=BIG_TICKET_LINES,
        actual_freight_cents=9_000,
        window_start_at=PICKUP_START, window_end_at=PICKUP_END,
        lot_overrides={"title": "Lot X single-SKU overstock"},
    )
    env = sold["env"]
    unsold = setup_approved_lot(
        env, UNSOLD_LOT_LINES, title="Lot Y single-SKU overstock",
        condition_grade="NEW_OVERSTOCK",
    )
    draft = create_listing(env, unsold["lot"]["id"], auction_listing_payload())
    return {"env": env, "sold": sold, "unsold": unsold, "draft_listing": draft}


def test_publishing_an_unsold_lot_moves_the_gross_rate_and_leaves_the_net_rate():
    """The same single sale is measured twice: against everything offered, and against what
    actually sold and settled.

    PRD 3.9: "The **gross** basis measures what the seller recovered against everything it
    put on the market: `gross_hammer_cents` is the sum of `hammer_price_cents` over that
    seller's orders whose `logistics_status` is not `ABANDONED`, `listed_retail_value_cents`
    is the sum of `declared_retail_value_cents` over that seller's lots whose `lot_status` is
    `LISTED`, `SOLD` or `RELIST_PENDING`, and `gross_recovery_rate` is the first divided by
    the second, rounded half up once to four decimal places, or exactly 0.0000 when the
    denominator is zero."
    PRD 3.9: "The **net** basis measures post-commission payouts against what actually sold:
    `net_proceeds_cents` is the sum of `seller_net_proceeds_cents` over that seller's orders
    whose `settlement_basis` is `FINAL`, `sold_retail_value_cents` is the sum of
    `declared_retail_value_cents` over that seller's lots whose `lot_status` is `SOLD`, and
    `net_recovery_rate` is the first divided by the second, rounded half up once to four
    decimal places, or exactly 0.0000 when the denominator is zero."
    PRD 3.3: "Publication also enters the lot into the seller's gross recovery denominator —
    the seller's `listed_retail_value_cents` is recomputed as the sum of
    `declared_retail_value_cents` over that seller's lots whose `lot_status` is `LISTED`,
    `SOLD` or `RELIST_PENDING`, which recomputes `gross_recovery_rate`, which reassigns
    `commission_tier` and `commission_rate_bps` as §3.9 specifies."

    Design: Difficulty/dual_variant_calc/recovery_rate_gross_and_net_diverge_on_seller_account
    """
    staged = _sold_lot_plus_unpublished_lot()
    env = staged["env"]
    before = read_analytics(env)
    assert_analytics_envelope(before)
    assert before["gross_hammer_cents"] == 2_700_000
    assert before["listed_retail_value_cents"] == 10_000_000
    assert before["gross_recovery_rate"] == 0.2700
    assert before["net_recovery_rate"] == 0.2295

    publish_listing(env, staged["draft_listing"]["id"])

    after = read_analytics(env)
    assert after["gross_hammer_cents"] == 2_700_000
    assert after["listed_retail_value_cents"] == 14_000_000
    assert after["gross_recovery_rate"] == 0.1929
    assert after["net_proceeds_cents"] == 2_295_000
    assert after["sold_retail_value_cents"] == 10_000_000
    assert after["net_recovery_rate"] == 0.2295
    assert after["gross_recovery_rate"] != after["net_recovery_rate"]


def test_the_gross_fall_retiers_the_seller_but_never_reprices_the_settled_order():
    """Publishing the second lot drops the gross rate below the threshold and demotes the
    seller, while the order that already settled keeps the rate it froze at pickup.

    PRD 3.9: "Otherwise, if `gross_recovery_rate` is greater than or equal to 0.2500 the tier
    is `TIER_PREFERRED` at 1,500 basis points — the comparison is inclusive, so a rate of
    exactly 0.2500 earns the preferred tier while 0.2499 does not — and in every remaining
    case the tier is `TIER_STANDARD` at 2,000 basis points."
    PRD 3.9: "First, the rate in force is read from the seller's `commission_rate_bps` at that
    instant — after the same request's recovery recomputation, and then frozen into the order's
    `seller_commission_rate_bps`, so a later tier change never reprices an already settled
    order."

    Design: Difficulty/dual_variant_calc/recovery_rate_gross_and_net_diverge_on_seller_account
    """
    staged = _sold_lot_plus_unpublished_lot()
    env = staged["env"]
    preferred = read_seller(env)
    assert preferred["gross_recovery_rate"] == 0.2700
    assert preferred["commission_tier"] == "TIER_PREFERRED"
    assert preferred["commission_rate_bps"] == 1_500

    publish_listing(env, staged["draft_listing"]["id"])

    demoted = read_seller(env)
    assert demoted["gross_recovery_rate"] == 0.1929
    assert demoted["commission_tier"] == "TIER_STANDARD"
    assert demoted["commission_rate_bps"] == 2_000
    assert demoted["net_recovery_rate"] == 0.2295

    order = read_order(env, staged["sold"]["order"]["id"])
    assert order["settlement_basis"] == "FINAL"
    assert order["seller_commission_rate_bps"] == 1_500
    assert order["seller_commission_cents"] == 405_000
    assert order["seller_net_proceeds_cents"] == 2_295_000


def test_the_seller_payout_rounds_every_line_before_summing_the_commission():
    """Three non-terminating line shares expose the nesting: the per-line commissions sum to
    one cent less than the rate applied to the hammer price in one step.

    PRD 3.9: "Then, walking the lot's manifest lines whose `line_status` is `ACTIVE` in
    `created_at` ascending order — the ordering is fixed so that the summation is
    reproducible, and the row identifier is never used for ordering — each line yields its
    extended value as `unit_count` multiplied by `unit_retail_cents`; its share of the sale as
    the order's `hammer_price_cents` multiplied by that extended value, divided by the lot's
    `declared_retail_value_cents`, rounded half up to a whole cent; and its commission as that
    rounded share multiplied by the frozen rate, divided by 10,000, rounded half up to a whole
    cent."
    PRD 3.9: "This order is normative and must not be shortcut: on a lot whose three line
    shares are 704,283, 1,526,176 and 469,541 cents at a rate of 1,500 basis points, the
    per-line commissions of 105,642, 228,926 and 70,431 cents sum to 404,999 cents, whereas
    applying the rate directly to the 2,700,000-cent hammer price would yield 405,000 cents —
    a one-cent divergence that the per-line order resolves in the seller's favour."
    PRD 3.9: "`seller_net_proceeds_cents` is then the order's `hammer_price_cents` less
    `seller_commission_cents` less `seller_debranding_fee_cents`."

    Design: Difficulty/combinatorial_formula/seller_net_proceeds_round_per_line_then_sum
    """
    built = setup_paid_fixed_price_order(
        ask_price_cents=2_700_000, lines=LOT_D_LINES,
        lot_overrides={"title": "Lot D mixed overstock"},
    )
    env = built["env"]
    lot = read_lot(env, built["lot"]["id"])
    assert lot["declared_unit_count"] == 445
    assert lot["declared_retail_value_cents"] == 5_750_240

    unsettled = read_order(env, built["order"]["id"])
    assert unsettled["seller_commission_cents"] is None
    assert unsettled["seller_net_proceeds_cents"] is None

    appointment = book_appointment(
        env, unsettled, window_start_at=PICKUP_START, window_end_at=PICKUP_END,
        bol_number="BOL-LOTD",
    )
    complete_appointment(
        env, appointment, actual_freight_cents=25_500, picked_up_unit_count=445
    )

    settled = read_order(env, built["order"]["id"])
    assert settled["seller_commission_rate_bps"] == 1_500
    assert settled["seller_commission_cents"] == 404_999
    assert settled["seller_commission_cents"] != 405_000
    assert settled["seller_debranding_fee_cents"] == 0
    assert settled["seller_net_proceeds_cents"] == 2_295_001


def test_the_settled_lot_d_order_carries_its_payout_into_the_net_recovery_basis():
    """The one-cent divergence is not swallowed downstream: it reaches the seller's net
    proceeds and the net rate computed from them.

    PRD 3.9: "`seller_commission_cents` is the sum of those per-line commissions — **rounded
    per line and only then summed**."
    PRD 3.9: "All four of these fields stay null until the order's `settlement_basis` becomes
    `FINAL`."
    PRD 3.9: "The **net** basis measures post-commission payouts against what actually sold:
    `net_proceeds_cents` is the sum of `seller_net_proceeds_cents` over that seller's orders
    whose `settlement_basis` is `FINAL`, `sold_retail_value_cents` is the sum of
    `declared_retail_value_cents` over that seller's lots whose `lot_status` is `SOLD`, and
    `net_recovery_rate` is the first divided by the second, rounded half up once to four
    decimal places, or exactly 0.0000 when the denominator is zero."

    Design: Difficulty/combinatorial_formula/seller_net_proceeds_round_per_line_then_sum
    """
    built = setup_paid_fixed_price_order(
        ask_price_cents=2_700_000, lines=LOT_D_LINES,
        lot_overrides={"title": "Lot D mixed overstock"},
    )
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    assert order["total_due_cents"] == 2_995_500
    assert order["balance_due_cents"] == 0
    assert order["estimated_freight_cents"] == 25_500

    appointment = book_appointment(
        env, order, window_start_at=PICKUP_START, window_end_at=PICKUP_END,
        bol_number="BOL-LOTD",
    )
    complete_appointment(
        env, appointment, actual_freight_cents=25_500, picked_up_unit_count=445
    )

    settled = read_order(env, built["order"]["id"])
    assert settled["settlement_basis"] == "FINAL"
    assert settled["actual_freight_cents"] == 25_500
    assert settled["total_due_cents"] == 2_995_500
    assert settled["balance_due_cents"] == 0

    seller = read_seller(env)
    assert seller["net_proceeds_cents"] == 2_295_001
    assert seller["net_recovery_rate"] == 0.3991
    assert seller["gross_recovery_rate"] == 0.4695
    assert seller["commission_tier"] == "TIER_PREFERRED"


# Two same-seller lots that differ only in category and by 10,000 cents of retail.
APPAREL_LOT_LINES = [
    {
        "sku": "APP-CAT-0200",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

HOME_GOODS_LOT_LINES = [
    {
        "sku": "HG-CAT-0201",
        "unit_count": 201,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

# 200 x 20000 puts exactly 4,000,000 cents of retail behind a 1,000,000-cent sale.
THRESHOLD_LOT_LINES = [
    {
        "sku": "APP-THR-0200",
        "unit_count": 200,
        "unit_retail_cents": 20_000,
        "declared_condition": "USED_GOOD",
    },
]

# A single 2,000-cent unit: just enough retail to push the ratio under the threshold.
TINY_LOT_LINES = [
    {
        "sku": "APP-THR-0001",
        "unit_count": 1,
        "unit_retail_cents": 2_000,
        "declared_condition": "USED_GOOD",
    },
]


def test_grouping_by_category_reports_each_slice_and_the_whole_population():
    """One seller, two sold lots in different categories: the envelope aggregates both while
    each group aggregates only its own lot.

    PRD 3.9: "The response reports `seller_id`, the effective `group_by`, and both variants at
    the top level as `gross_hammer_cents`, `listed_retail_value_cents`, `gross_recovery_rate`,
    `net_proceeds_cents`, `sold_retail_value_cents` and `net_recovery_rate`, plus a `groups`
    array."
    PRD 3.9: "With `CATEGORY` the lot population is grouped by each lot's `category_code`, and
    with `CHANNEL` it is grouped by the `resale_channel` of the listing that produced each
    order; in either case each entry carries a `key` naming the group and the same six
    aggregate figures recomputed within that group, and a group whose denominator is zero
    reports 0.0000 rather than being omitted."
    PRD 3.9: "The **net** basis measures post-commission payouts against what actually sold:
    `net_proceeds_cents` is the sum of `seller_net_proceeds_cents` over that seller's orders
    whose `settlement_basis` is `FINAL`, `sold_retail_value_cents` is the sum of
    `declared_retail_value_cents` over that seller's lots whose `lot_status` is `SOLD`, and
    `net_recovery_rate` is the first divided by the second, rounded half up once to four
    decimal places, or exactly 0.0000 when the denominator is zero."

    Design: Corner/calculations/recovery_analytics_group_by_category_splits_the_seller_population
    """
    env = bootstrap_marketplace()
    setup_fixed_price_order(
        env, ask_price_cents=1_000_000, lines=APPAREL_LOT_LINES,
        lot_overrides={"title": "Apparel returns lot A", "category_code": "APPAREL"},
    )
    setup_fixed_price_order(
        env, ask_price_cents=1_000_000, lines=HOME_GOODS_LOT_LINES,
        lot_overrides={"title": "Home goods returns lot B", "category_code": "HOME_GOODS"},
        clock=None,
    )

    report = read_analytics(env, group_by="CATEGORY")
    assert_analytics_envelope(report)
    assert report["seller_id"] == env["seller"]["id"]
    assert report["group_by"] == "CATEGORY"
    assert report["gross_hammer_cents"] == 2_000_000
    assert report["listed_retail_value_cents"] == 4_010_000
    assert report["gross_recovery_rate"] == 0.4988
    assert report["net_proceeds_cents"] == 0
    assert report["sold_retail_value_cents"] == 4_010_000
    assert report["net_recovery_rate"] == 0.0000

    groups = {group["key"]: group for group in report["groups"]}
    assert sorted(groups) == ["APPAREL", "HOME_GOODS"]
    assert groups["APPAREL"]["gross_hammer_cents"] == 1_000_000
    assert groups["APPAREL"]["listed_retail_value_cents"] == 2_000_000
    assert groups["APPAREL"]["gross_recovery_rate"] == 0.5000
    assert groups["HOME_GOODS"]["gross_hammer_cents"] == 1_000_000
    assert groups["HOME_GOODS"]["listed_retail_value_cents"] == 2_010_000
    assert groups["HOME_GOODS"]["gross_recovery_rate"] == 0.4975
    for group in groups.values():
        assert group["net_proceeds_cents"] == 0
        assert group["net_recovery_rate"] == 0.0000

    seller = read_seller(env)
    assert seller["gross_recovery_rate"] == 0.4988
    assert seller["commission_tier"] == "TIER_PREFERRED"
    assert seller["commission_rate_bps"] == 1_500


def test_a_seller_whose_only_lot_is_a_draft_reads_zeros_rather_than_a_division():
    """Both denominators are empty, so both rates read exactly 0.0000 and the default grouping
    returns no groups at all.

    PRD 3.9: "A computed analytics read serves these figures for one seller without persisting
    anything."
    PRD 3.9: "With `group_by` of `NONE` the `groups` array is empty."
    PRD 3.9: "The **gross** basis measures what the seller recovered against everything it put
    on the market: `gross_hammer_cents` is the sum of `hammer_price_cents` over that seller's
    orders whose `logistics_status` is not `ABANDONED`, `listed_retail_value_cents` is the sum
    of `declared_retail_value_cents` over that seller's lots whose `lot_status` is `LISTED`,
    `SOLD` or `RELIST_PENDING`, and `gross_recovery_rate` is the first divided by the second,
    rounded half up once to four decimal places, or exactly 0.0000 when the denominator is
    zero."
    PRD 3.9: "A freshly registered seller starts `ACTIVE` on `TIER_STANDARD` at 2,000 basis
    points with every recovery aggregate at zero and `manifest_accuracy_avg` at 1.000."

    Design: Corner/endpoints/recovery_analytics_returns_zeros_for_a_seller_with_no_listed_lots
    """
    env = bootstrap_marketplace()
    built = create_lot_with_lines(
        env, BIG_TICKET_LINES, title="Draft overstock lot", condition_grade="NEW_OVERSTOCK"
    )

    report = read_analytics(env)
    assert_analytics_envelope(report)
    assert report["seller_id"] == env["seller"]["id"]
    assert report["group_by"] == "NONE"
    assert report["groups"] == []
    assert report["gross_hammer_cents"] == 0
    assert report["listed_retail_value_cents"] == 0
    assert report["gross_recovery_rate"] == 0.0000
    assert report["net_proceeds_cents"] == 0
    assert report["sold_retail_value_cents"] == 0
    assert report["net_recovery_rate"] == 0.0000

    lot = read_lot(env, built["lot"]["id"])
    assert lot["lot_status"] == "DRAFT"
    assert lot["declared_retail_value_cents"] == 10_000_000

    seller = read_seller(env)
    assert seller["gross_recovery_rate"] == 0.0000
    assert seller["commission_tier"] == "TIER_STANDARD"
    assert seller["commission_rate_bps"] == 2_000


def test_the_tier_threshold_is_inclusive_going_up_and_strict_coming_down():
    """A rate of exactly 0.2500 promotes the seller; adding 2,000 cents of unsold retail takes
    the rate to 0.2499 and demotes it again, with no sale in between.

    PRD 3.9: "Otherwise, if `gross_recovery_rate` is greater than or equal to 0.2500 the tier
    is `TIER_PREFERRED` at 1,500 basis points — the comparison is inclusive, so a rate of
    exactly 0.2500 earns the preferred tier while 0.2499 does not — and in every remaining case
    the tier is `TIER_STANDARD` at 2,000 basis points."
    PRD 3.9: "Reassignment is triggered by listing publication, auction close, fixed-price
    purchase, negotiated acceptance, the pickup-deadline sweep, claim decisions and claim
    reversals — that is, by every event that can move either the recovery rate or the accuracy
    average."
    PRD 3.3: "Publication also enters the lot into the seller's gross recovery denominator —
    the seller's `listed_retail_value_cents` is recomputed as the sum of
    `declared_retail_value_cents` over that seller's lots whose `lot_status` is `LISTED`,
    `SOLD` or `RELIST_PENDING`, which recomputes `gross_recovery_rate`, which reassigns
    `commission_tier` and `commission_rate_bps` as §3.9 specifies."
    PRD 3.9: "All four of these fields stay null until the order's `settlement_basis` becomes
    `FINAL`."

    Design: Corner/cross_cutting_complexity_layers/commission_tier_crosses_the_recovery_threshold_in_both_directions
    """
    env = bootstrap_marketplace()
    sold = setup_fixed_price_order(
        env, ask_price_cents=1_000_000, lines=THRESHOLD_LOT_LINES,
        lot_overrides={"title": "Threshold lot one", "category_code": "APPAREL"},
    )

    at_threshold = read_analytics(env)
    assert at_threshold["gross_hammer_cents"] == 1_000_000
    assert at_threshold["listed_retail_value_cents"] == 4_000_000
    assert at_threshold["gross_recovery_rate"] == 0.2500
    assert at_threshold["net_recovery_rate"] == 0.0000

    promoted = read_seller(env)
    assert promoted["commission_tier"] == "TIER_PREFERRED"
    assert promoted["commission_rate_bps"] == 1_500

    second = setup_approved_lot(
        env, TINY_LOT_LINES, title="Threshold lot two", category_code="APPAREL"
    )
    listing = create_listing(
        env, second["lot"]["id"], fixed_price_listing_payload(2_000)
    )
    publish_listing(env, listing["id"])

    below_threshold = read_analytics(env)
    assert below_threshold["gross_hammer_cents"] == 1_000_000
    assert below_threshold["listed_retail_value_cents"] == 4_002_000
    assert below_threshold["gross_recovery_rate"] == 0.2499
    assert below_threshold["net_recovery_rate"] == 0.0000

    demoted = read_seller(env)
    assert demoted["commission_tier"] == "TIER_STANDARD"
    assert demoted["commission_rate_bps"] == 2_000

    order = read_order(env, sold["order"]["id"])
    assert order["buyer_premium_bps"] == 1_400
    assert order["total_due_cents"] == 1_148_500
    assert order["seller_commission_rate_bps"] is None
