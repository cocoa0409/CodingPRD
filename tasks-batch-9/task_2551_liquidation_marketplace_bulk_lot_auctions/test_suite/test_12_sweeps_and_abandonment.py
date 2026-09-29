"""The two sweeps: pickup abandonment with its cascade, and the once-only late fee."""

from test_helpers import (
    CANONICAL_LOT_LINES,
    api_client,
    assert_instant,
    bootstrap_marketplace,
    get_success_data,
    payment_payload,
    read_buyer,
    read_listing,
    read_lot,
    read_order,
    read_seller,
    set_clock,
    setup_auction_sale_order,
    setup_fixed_price_order,
    validate_error,
    validate_success,
)

# 200 x 10000: 2,000,000 cents of declared retail on one pallet.
LOT_A_LINES = [
    {
        "sku": "APP-SWP-0200A",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

LOT_B_LINES = [
    {
        "sku": "APP-SWP-0200B",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

ONE_SECOND_PAST_DEADLINE = "2026-08-22T00:00:01Z"


def _sweep_pickup_deadlines(env):
    """Run the pickup-deadline sweep and return the rows it changed."""
    return validate_success(
        api_client.run_pickup_deadline_sweep({}, env["sweeper_headers"])
    )


def _sweep_late_fees(env):
    """Run the late-fee sweep and return the rows it changed."""
    return validate_success(
        api_client.run_payment_late_fee_sweep({}, env["sweeper_headers"])
    )


def test_the_deadline_sweep_writes_off_the_order_and_frees_the_lot_to_be_relisted():
    """One second past the deadline the sweep claims the order, stamps it and returns the lot
    to the relist queue while the closed listing stands.

    PRD 3.7: "It selects every order whose `logistics_status` is `AWAITING_APPOINTMENT` or
    `APPOINTMENT_SCHEDULED` and whose `pickup_deadline_at` is strictly before the current
    logical clock — an order sitting exactly on its deadline is not yet abandoned — and it does
    so regardless of `payment_status`."
    PRD 3.7: "Each selected order advances `AWAITING_APPOINTMENT → ABANDONED` or
    `APPOINTMENT_SCHEDULED → ABANDONED` and has `abandoned_at` stamped."
    PRD 3.7: "The lot returns `SOLD → RELIST_PENDING` so the seller can offer it again, and the
    seller aggregates are recomputed: an abandoned order leaves the gross hammer numerator
    entirely, so `gross_hammer_cents` and `sold_retail_value_cents` fall, which recomputes
    `gross_recovery_rate`, which reassigns `commission_tier` and `commission_rate_bps`."
    PRD 3.6: "Finally, two deadlines are fixed from the order's `created_at`: `payment_due_at`
    is three days after creation and `pickup_deadline_at` is ten days after creation."

    Design: Difficulty/transitive_cascade/pickup_deadline_sweep_cascades_through_lot_relist_to_commission_tier
    """
    built = setup_auction_sale_order()
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    assert order["payment_status"] == "UNPAID"
    assert order["logistics_status"] == "AWAITING_APPOINTMENT"
    assert_instant(order["payment_due_at"], "2026-08-15T00:00:00Z")
    assert_instant(order["pickup_deadline_at"], "2026-08-22T00:00:00Z")

    set_clock(ONE_SECOND_PAST_DEADLINE)
    swept = _sweep_pickup_deadlines(env)
    assert len(swept) == 1
    assert swept[0]["id"] == order["id"]
    assert swept[0]["logistics_status"] == "ABANDONED"
    assert_instant(swept[0]["abandoned_at"], ONE_SECOND_PAST_DEADLINE)

    assert read_lot(env, built["lot"]["id"])["lot_status"] == "RELIST_PENDING"
    assert read_listing(env, built["listing"]["id"])["listing_status"] == "CLOSED_SOLD"


def test_the_write_off_retiers_the_seller_and_shuts_the_payment_window():
    """The abandoned order leaves the numerator and the exposure base, the tier follows the
    collapsed rate, and the buyer can no longer pay.

    PRD 3.7: "The affected buyers' `outstanding_exposure_cents` are recomputed too, since an
    abandoned order leaves the exposure base."
    PRD 3.9: "Otherwise, if `gross_recovery_rate` is greater than or equal to 0.2500 the tier is
    `TIER_PREFERRED` at 1,500 basis points — the comparison is inclusive, so a rate of exactly
    0.2500 earns the preferred tier while 0.2499 does not — and in every remaining case the tier
    is `TIER_STANDARD` at 2,000 basis points."
    PRD 3.6: "Payment is also refused when `logistics_status` is `ABANDONED`, with
    `ERR_PAYMENT_WINDOW_CLOSED` — once the pickup-deadline sweep has written off an order it can
    no longer be paid."

    Design: Difficulty/transitive_cascade/pickup_deadline_sweep_cascades_through_lot_relist_to_commission_tier
    """
    built = setup_auction_sale_order()
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    before = read_seller(env)
    assert before["gross_hammer_cents"] == 2_700_000
    assert before["listed_retail_value_cents"] == 10_000_000
    assert before["gross_recovery_rate"] == 0.2700
    assert before["commission_tier"] == "TIER_PREFERRED"
    assert read_buyer(env)["outstanding_exposure_cents"] == 2_987_000

    set_clock(ONE_SECOND_PAST_DEADLINE)
    _sweep_pickup_deadlines(env)

    after = read_seller(env)
    assert after["gross_hammer_cents"] == 0
    assert after["listed_retail_value_cents"] == 10_000_000
    assert after["gross_recovery_rate"] == 0.0000
    assert after["commission_tier"] == "TIER_STANDARD"
    assert after["commission_rate_bps"] == 2_000
    assert after["account_status"] == "ACTIVE"
    assert after["manifest_accuracy_avg"] == 1.000
    assert read_buyer(env)["outstanding_exposure_cents"] == 0

    too_late = api_client.pay_sale_order(
        order["id"], payment_payload(2_987_000), env["buyer_headers"]
    )
    validate_error(too_late, "ERR_PAYMENT_WINDOW_CLOSED", 409)

    unpaid = read_order(env, order["id"])
    assert unpaid["payment_status"] == "UNPAID"
    assert unpaid["amount_paid_cents"] == 0
    assert unpaid["late_fee_cents"] == 0


def test_the_sweep_takes_the_overdue_order_and_skips_the_one_still_in_time():
    """Two orders one day apart: only the one whose deadline has passed is claimed, and a second
    identical sweep changes nothing.

    PRD 3.7: "It selects every order whose `logistics_status` is `AWAITING_APPOINTMENT` or
    `APPOINTMENT_SCHEDULED` and whose `pickup_deadline_at` is strictly before the current
    logical clock — an order sitting exactly on its deadline is not yet abandoned — and it does
    so regardless of `payment_status`."
    PRD 3.7: "Orders already `PICKED_UP` or `ABANDONED` are skipped, which makes the sweep
    idempotent across repeated runs at the same clock."
    PRD 4: "Sweep endpoints return the array of rows they changed, which may be empty."

    Design: Corner/endpoints/pickup_deadline_sweep_abandons_only_the_overdue_order
    """
    env = bootstrap_marketplace()
    first = setup_fixed_price_order(
        env, ask_price_cents=1_000_000, lines=LOT_A_LINES,
        lot_overrides={"title": "Sweep lot A"},
    )
    second = setup_fixed_price_order(
        env, ask_price_cents=1_000_000, lines=LOT_B_LINES,
        lot_overrides={"title": "Sweep lot B"}, clock="2026-08-06T01:00:00Z",
    )
    order_a = read_order(env, first["order"]["id"])
    order_b = read_order(env, second["order"]["id"])
    assert_instant(order_a["pickup_deadline_at"], "2026-08-15T01:00:00Z")
    assert_instant(order_b["pickup_deadline_at"], "2026-08-16T01:00:00Z")
    assert order_a["total_due_cents"] == 1_148_500
    assert order_b["total_due_cents"] == 1_148_500

    set_clock("2026-08-15T01:00:01Z")
    swept = _sweep_pickup_deadlines(env)
    assert len(swept) == 1
    assert swept[0]["id"] == order_a["id"]

    abandoned = read_order(env, order_a["id"])
    assert abandoned["logistics_status"] == "ABANDONED"
    assert_instant(abandoned["abandoned_at"], "2026-08-15T01:00:01Z")
    untouched = read_order(env, order_b["id"])
    assert untouched["logistics_status"] == "AWAITING_APPOINTMENT"
    assert untouched["abandoned_at"] is None

    assert read_lot(env, first["lot"]["id"])["lot_status"] == "RELIST_PENDING"
    assert read_lot(env, second["lot"]["id"])["lot_status"] == "SOLD"

    again = _sweep_pickup_deadlines(env)
    assert again == []
    assert_instant(read_order(env, order_a["id"])["abandoned_at"], "2026-08-15T01:00:01Z")


def test_the_abandoned_lot_leaves_both_numerators_while_the_sold_lot_stays():
    """After the selective sweep the seller's gross and net populations are each missing exactly
    the abandoned sale, and the buyer's exposure holds only the surviving order.

    PRD 3.7: "The lot returns `SOLD → RELIST_PENDING` so the seller can offer it again, and the
    seller aggregates are recomputed: an abandoned order leaves the gross hammer numerator
    entirely, so `gross_hammer_cents` and `sold_retail_value_cents` fall, which recomputes
    `gross_recovery_rate`, which reassigns `commission_tier` and `commission_rate_bps`."
    PRD 3.9: "The **gross** basis measures what the seller recovered against everything it put on
    the market: `gross_hammer_cents` is the sum of `hammer_price_cents` over that seller's orders
    whose `logistics_status` is not `ABANDONED`, `listed_retail_value_cents` is the sum of
    `declared_retail_value_cents` over that seller's lots whose `lot_status` is `LISTED`, `SOLD`
    or `RELIST_PENDING`, and `gross_recovery_rate` is the first divided by the second, rounded
    half up once to four decimal places, or exactly 0.0000 when the denominator is zero."
    PRD 3.7: "The affected buyers' `outstanding_exposure_cents` are recomputed too, since an
    abandoned order leaves the exposure base."

    Design: Corner/endpoints/pickup_deadline_sweep_abandons_only_the_overdue_order
    """
    env = bootstrap_marketplace()
    setup_fixed_price_order(
        env, ask_price_cents=1_000_000, lines=LOT_A_LINES,
        lot_overrides={"title": "Sweep lot A"},
    )
    setup_fixed_price_order(
        env, ask_price_cents=1_000_000, lines=LOT_B_LINES,
        lot_overrides={"title": "Sweep lot B"}, clock="2026-08-06T01:00:00Z",
    )

    set_clock("2026-08-15T01:00:01Z")
    assert len(_sweep_pickup_deadlines(env)) == 1

    seller = read_seller(env)
    assert seller["gross_hammer_cents"] == 1_000_000
    assert seller["listed_retail_value_cents"] == 4_000_000
    assert seller["gross_recovery_rate"] == 0.2500
    assert seller["sold_retail_value_cents"] == 2_000_000
    assert seller["net_proceeds_cents"] == 0
    assert seller["net_recovery_rate"] == 0.0000
    assert seller["commission_tier"] == "TIER_PREFERRED"
    assert seller["commission_rate_bps"] == 1_500

    assert read_buyer(env)["outstanding_exposure_cents"] == 1_148_500


def test_the_late_fee_waits_for_the_due_instant_to_pass_and_is_charged_only_once():
    """A sweep standing exactly on the due instant changes nothing, the next second charges 1.5
    percent of the pre-fee total, and further sweeps must not compound it.

    PRD 3.6: "It is zero for an order paid in full at or before `payment_due_at`, and once the
    late-fee sweep observes a clock strictly past `payment_due_at` with a balance still
    outstanding it becomes `pre_fee_total_cents` multiplied by 150 basis points, that is 1.5
    percent, divided by 10,000 and rounded half up to a whole cent."
    PRD 3.6: "The late fee is assessed **at most once per order** and is frozen once assessed."
    PRD 3.6: "It selects every order whose `balance_due_cents` is greater than zero, whose
    `late_fee_cents` is still zero, and whose `payment_due_at` is strictly before the current
    logical clock; for each, it computes the fee from `pre_fee_total_cents` as described above,
    then recomputes `total_due_cents` and `balance_due_cents`, and finally recomputes the affected
    buyers' `outstanding_exposure_cents`."
    PRD 3.6: "Orders already carrying a non-zero late fee are skipped, which is what makes the
    sweep safe to run repeatedly."
    PRD 3.6: "When a payment lands after `payment_due_at`, any late fee already recorded in
    `late_fee_cents` remains part of `total_due_cents` and must be covered — settling late does not
    retire the fee."

    Design: Corner/cross_cutting_complexity_layers/the_late_fee_sweep_fires_only_past_the_due_instant_and_freezes_the_amount
    """
    built = setup_fixed_price_order(
        ask_price_cents=2_700_000, lines=CANONICAL_LOT_LINES,
        lot_overrides={"title": "Late fee lot", "condition_grade": "CUSTOMER_RETURNS"},
        clock="2026-08-12T01:00:00Z",
    )
    env = built["env"]
    order = read_order(env, built["order"]["id"])
    assert order["pre_fee_total_cents"] == 2_987_000
    assert_instant(order["payment_due_at"], "2026-08-15T01:00:00Z")

    set_clock("2026-08-15T01:00:00Z")
    assert _sweep_late_fees(env) == []
    on_the_instant = read_order(env, order["id"])
    assert on_the_instant["late_fee_cents"] == 0
    assert on_the_instant["total_due_cents"] == 2_987_000
    assert on_the_instant["payment_status"] == "UNPAID"

    set_clock("2026-08-15T01:00:01Z")
    swept = _sweep_late_fees(env)
    assert len(swept) == 1
    assert swept[0]["id"] == order["id"]

    assessed = read_order(env, order["id"])
    assert assessed["late_fee_cents"] == 44_805
    assert assessed["total_due_cents"] == 3_031_805
    assert assessed["balance_due_cents"] == 3_031_805
    assert assessed["payment_status"] == "UNPAID"

    assert _sweep_late_fees(env) == []
    frozen = read_order(env, order["id"])
    assert frozen["late_fee_cents"] == 44_805
    assert frozen["late_fee_cents"] != 45_477

    get_success_data(
        api_client.pay_sale_order(
            order["id"], payment_payload(3_031_805), env["buyer_headers"]
        )
    )
    settled = read_order(env, order["id"])
    assert settled["payment_status"] == "PAID"
    assert settled["balance_due_cents"] == 0
    assert settled["late_fee_cents"] == 44_805
    assert read_buyer(env)["outstanding_exposure_cents"] == 0
