"""The two places where one operation carries two genuinely different formulas.

An invoice is struck either on the metal price pinned when the order was booked
or on the mean of the settlement window ending at the ship date, and a deposit
comes back either on a stepped band keyed on days out or on a linear decay curve
keyed on the same days out. In both pairs the inputs are identical and only the
variant selector differs, so the money has to differ by an amount that can be
computed to the cent from the contract alone.
"""

import pytest

from test_helpers import (
    BILLING,
    CLERK,
    advance_lot_to_tested,
    assert_deposit_ledger_identity,
    assert_four_decimal_price,
    assert_money,
    create_lot,
    create_metal_quote,
    create_order,
    create_reel,
    create_reel_return_payload,
    create_shipment_payload,
    current_order_version,
    get_success_data,
    load_reel_payload,
    read_customer,
    read_order,
    read_reel,
    release_lot,
    set_clock,
    setup_baseline,
    validate_success,
)

SECOND_LINE_WINDOW = {
    "line_code": "EXT-2",
    "scheduled_start_at": "2026-08-02T08:00:00Z",
    "scheduled_end_at": "2026-08-02T10:00:00Z",
}

# The five settlements that fall inside a window ending on 2026-08-05: their
# arithmetic mean is 21.65 / 5 = 4.3300.
FLOAT_WINDOW_QUOTES = (
    ("2026-08-01", 4.00),
    ("2026-08-02", 4.05),
    ("2026-08-03", 4.10),
    ("2026-08-04", 4.60),
    ("2026-08-05", 4.90),
)
SHIP_DATE = "2026-08-05"


def _post_float_window_quotes(api):
    for effective_date, price in FLOAT_WINDOW_QUOTES:
        create_metal_quote(
            api, effective_date=effective_date, settlement_price_usd_per_lb=price
        )


def _packaged_lot_on_its_own_reel(api, world, order, lot_code, reel_overrides=None,
                                  **lot_overrides):
    """Walk one 5000 ft lot to CONFORMING and put it on its own reel."""
    lot = create_lot(
        api, dict(world, order=order), lot_code=lot_code, planned_length_ft=5000,
        **lot_overrides,
    )
    advance_lot_to_tested(api, lot["id"])
    lot = release_lot(api, lot["id"], 5000)
    reel = create_reel(api, **(reel_overrides or {}))
    get_success_data(
        api.load_reel(reel["id"], load_reel_payload(lot["id"], 5000), CLERK)
    )
    return lot, reel


def _stage_and_invoice(api, order_id, lot_id, reel_id, ship_date=SHIP_DATE, length=5000):
    shipment = validate_success(
        api.create_shipment(
            create_shipment_payload(
                order_id, lot_id, reel_id, length,
                current_order_version(api, order_id), ship_date=ship_date,
            ),
            CLERK,
        ),
        201,
    )
    return get_success_data(api.invoice_shipment(shipment["id"], BILLING))


def test_the_two_price_bases_bill_identical_shipments_at_different_amounts(api):
    """Two orders differing in nothing but `price_basis`, each shipping 5000 ft of the
    same SKU on the same date, invoice 544.58 against 567.80.

    PRD 3.9: "Under `ORDER_DATE_LOCK`, `metal_price_used_usd_per_lb` is simply the
    order's `quoted_metal_price_usd_per_lb`, the price pinned when the order was
    booked; no quote lookup happens at invoice time at all, so later settlements
    can never move the invoice, and `price_variant_applied` is recorded as
    `ORDER_DATE_LOCK`."

    PRD 3.9: "Under `SHIP_DATE_FLOAT`, `metal_price_used_usd_per_lb` is the
    arithmetic mean of `settlement_price_usd_per_lb` across every quote whose
    `metal` equals the SKU's `conductor_metal` and whose `effective_date` falls
    inside an inclusive five-calendar-day window running from four days before the
    shipment's `ship_date` through `ship_date` itself, rounded half up to four
    decimal places."

    PRD 3.5: "This price is recorded for `SHIP_DATE_FLOAT` orders as well as
    `ORDER_DATE_LOCK` ones, so that the quote remains comparable against whatever
    the float window later produces."

    Design: Difficulty/dual_variant_calc/metal_pass_through_lock_versus_float_invoice
    """
    world = setup_baseline(api, order_overrides={"order_number": "SO-LOCK"})
    lock_order = world["order"]
    float_order = create_order(
        api, world["customer"]["id"], world["product"]["id"],
        order_number="SO-FLOAT", price_basis="SHIP_DATE_FLOAT",
    )
    _post_float_window_quotes(api)

    lock_lot, lock_reel = _packaged_lot_on_its_own_reel(
        api, world, lock_order, "LOT-A1"
    )
    float_lot, float_reel = _packaged_lot_on_its_own_reel(
        api, world, float_order, "LOT-B1", {"reel_serial": "R-002"}, **SECOND_LINE_WINDOW
    )

    locked = _stage_and_invoice(
        api, lock_order["id"], lock_lot["id"], lock_reel["id"]
    )
    floated = _stage_and_invoice(
        api, float_order["id"], float_lot["id"], float_reel["id"]
    )

    assert locked["price_variant_applied"] == "ORDER_DATE_LOCK"
    assert_four_decimal_price(
        locked["metal_price_used_usd_per_lb"], 4.1000, "the pinned metal price"
    )
    assert_four_decimal_price(
        locked["unit_price_usd_per_kft"], 106.7800, "85.00 plus 19.8 x 1.10"
    )
    assert_money(locked["extended_amount_usd"], 533.90, "106.78 over 5.000 kft")
    assert_money(locked["volatility_surcharge_usd"], 10.68, "two percent of 533.90")
    assert_money(locked["invoice_amount_usd"], 544.58, "the locked invoice")

    assert floated["price_variant_applied"] == "SHIP_DATE_FLOAT"
    assert_four_decimal_price(
        floated["metal_price_used_usd_per_lb"], 4.3300,
        "the mean of the five in-window settlements",
    )
    assert_four_decimal_price(
        floated["unit_price_usd_per_kft"], 111.3340, "85.00 plus 19.8 x 1.33"
    )
    assert_money(floated["extended_amount_usd"], 556.67, "111.334 over 5.000 kft")
    assert_money(floated["volatility_surcharge_usd"], 11.13, "two percent of 556.67")
    assert_money(floated["invoice_amount_usd"], 567.80, "the floated invoice")

    assert floated["invoice_amount_usd"] - locked["invoice_amount_usd"] == pytest.approx(
        23.22, abs=0.01
    ), "the variant selector is worth 23.22 on an otherwise identical delivery"

    assert_four_decimal_price(
        read_order(api, lock_order["id"])["quoted_metal_price_usd_per_lb"], 4.1000,
        "the locked order's reference price",
    )
    assert_four_decimal_price(
        read_order(api, float_order["id"])["quoted_metal_price_usd_per_lb"], 4.1000,
        "the floated order records the same reference price at booking",
    )


def test_the_locked_variant_ignores_every_settlement_posted_after_booking(api):
    """A rising market between the order date and the ship date moves nothing: the
    locked invoice is struck on the price pinned at booking.

    PRD 3.9: "Under `ORDER_DATE_LOCK`, `metal_price_used_usd_per_lb` is simply the
    order's `quoted_metal_price_usd_per_lb`, the price pinned when the order was
    booked; no quote lookup happens at invoice time at all, so later settlements
    can never move the invoice, and `price_variant_applied` is recorded as
    `ORDER_DATE_LOCK`."

    PRD 3.9: "`invoice_amount_usd` is then the extension plus the cut fee plus the
    surcharge, rounded half up to two decimals, and `invoice_date` is the logical
    clock's current date."

    Design: Difficulty/dual_variant_calc/metal_pass_through_lock_versus_float_invoice
    """
    world = setup_baseline(api, order_overrides={"order_number": "SO-LOCK"})
    order = world["order"]
    lot, reel = _packaged_lot_on_its_own_reel(api, world, order, "LOT-A1")
    _post_float_window_quotes(api)

    invoice = _stage_and_invoice(api, order["id"], lot["id"], reel["id"])

    assert invoice["price_variant_applied"] == "ORDER_DATE_LOCK"
    assert_four_decimal_price(
        invoice["metal_price_used_usd_per_lb"], 4.1000,
        "the 2026-07-30 settlement the order pinned, not the 4.90 of the ship date",
    )
    assert_four_decimal_price(
        invoice["unit_price_usd_per_kft"], 106.7800, "unit price"
    )
    assert_money(invoice["extended_amount_usd"], 533.90, "extension")
    assert_money(invoice["cut_fee_usd"], 0.00, "this order is not cut to length")
    assert_money(invoice["volatility_surcharge_usd"], 10.68, "two percent of 533.90")
    assert_money(invoice["invoice_amount_usd"], 544.58, "the locked invoice")
    assert invoice["invoice_date"] == "2026-08-01", (
        "the invoice is dated by the logical clock, not by the ship date"
    )
    assert_four_decimal_price(
        read_order(api, order["id"])["quoted_metal_price_usd_per_lb"], 4.1000,
        "the pinned price is untouched by the later settlements",
    )


def test_the_floated_variant_averages_an_inclusive_five_day_window(api):
    """The window takes both of its ends and nothing outside them: settlements a day
    before it opens and a day after the ship date are excluded.

    PRD 3.9: "Under `SHIP_DATE_FLOAT`, `metal_price_used_usd_per_lb` is the
    arithmetic mean of `settlement_price_usd_per_lb` across every quote whose
    `metal` equals the SKU's `conductor_metal` and whose `effective_date` falls
    inside an inclusive five-calendar-day window running from four days before the
    shipment's `ship_date` through `ship_date` itself, rounded half up to four
    decimal places."

    PRD 3.9: "`unit_price_usd_per_kft` is the order's `conversion_price_usd_per_kft`
    plus that component, rounded half up to four decimal places."

    Design: Difficulty/dual_variant_calc/metal_pass_through_lock_versus_float_invoice
    """
    world = setup_baseline(
        api,
        order_overrides={"order_number": "SO-FLOAT", "price_basis": "SHIP_DATE_FLOAT"},
    )
    order = world["order"]
    create_metal_quote(
        api, effective_date="2026-07-31", settlement_price_usd_per_lb=9.99
    )
    _post_float_window_quotes(api)
    create_metal_quote(
        api, effective_date="2026-08-06", settlement_price_usd_per_lb=9.99
    )

    lot, reel = _packaged_lot_on_its_own_reel(api, world, order, "LOT-B1")
    invoice = _stage_and_invoice(api, order["id"], lot["id"], reel["id"])

    assert invoice["price_variant_applied"] == "SHIP_DATE_FLOAT"
    assert_four_decimal_price(
        invoice["metal_price_used_usd_per_lb"], 4.3300,
        "4.00, 4.05, 4.10, 4.60 and 4.90 average to 4.3300; the 9.99 settlements "
        "on 2026-07-31 and 2026-08-06 both fall outside the window",
    )
    assert_four_decimal_price(
        invoice["unit_price_usd_per_kft"], 111.3340, "85.00 plus 19.8 x 1.33"
    )
    assert_money(invoice["extended_amount_usd"], 556.67, "extension")
    assert_money(invoice["volatility_surcharge_usd"], 11.13, "two percent of 556.67")
    assert_money(invoice["invoice_amount_usd"], 567.80, "the floated invoice")


def test_a_wood_reel_at_a_hundred_and_twenty_days_settles_on_the_stepped_band(api):
    """The flat-step schedule pays half the deposit anywhere between 91 and 180 days
    out, so the exact number of days out beyond 90 changes nothing.

    PRD 3.9: "A `WOOD_RETURNABLE` reel returned in `GOOD` condition follows a flat
    step schedule recorded as `FLAT_STEP`: the whole `deposit_usd` is refunded when
    `days_out` is at most 90; half the deposit, rounded half up to two decimals, is
    refunded when `days_out` is greater than 90 and at most 180; and nothing is
    refunded once `days_out` exceeds 180."

    PRD 3.9: "In every case `forfeited_usd` is `deposit_usd` minus `refund_usd`,
    rounded half up to two decimals, and `refund_variant_applied` records which of
    `FLAT_STEP`, `DAILY_DECAY` or `NONE` produced the figure."

    Design: Difficulty/dual_variant_calc/reel_deposit_flat_step_versus_daily_decay_refund
    """
    world = setup_baseline(api, order_overrides={"order_number": "SO-W"})
    order = world["order"]
    lot, reel = _packaged_lot_on_its_own_reel(
        api, world, order, "LOT-W",
        {"reel_serial": "R-W", "reel_type": "WOOD_RETURNABLE", "deposit_usd": 450.00},
    )
    set_clock(api, "2026-08-05T00:00:00Z")
    invoice = _stage_and_invoice(api, order["id"], lot["id"], reel["id"])
    assert read_reel(api, reel["id"])["status"] == "RETURN_PENDING", (
        "invoicing is what puts a returnable reel on the expected-back list"
    )

    set_clock(api, "2026-12-03T00:00:00Z")
    settled = validate_success(
        api.create_reel_return(
            reel["id"],
            create_reel_return_payload(invoice["id"], "2026-12-03", "GOOD"),
            CLERK,
        ),
        201,
    )

    assert settled["days_out"] == 120, (
        "whole calendar days from the 2026-08-05 shipping instant to the return"
    )
    assert settled["refund_variant_applied"] == "FLAT_STEP"
    assert_money(settled["refund_usd"], 225.00, "half of a 450.00 deposit")
    assert_money(settled["forfeited_usd"], 225.00, "the deposit less the refund")

    customer = read_customer(api, world["customer"]["id"])
    assert_money(customer["credit_memo_balance_usd"], 225.00, "credited back")
    assert_money(customer["forfeited_deposit_total_usd"], 225.00, "forfeited")
    assert_money(customer["reel_deposit_balance_usd"], 0.00, "nothing outstanding")
    assert_deposit_ledger_identity(customer)


def test_a_steel_reel_at_the_same_days_out_settles_on_the_decay_curve(api):
    """The daily-decay schedule reads the same 120 days out and the same 450.00
    deposit and answers 234.00, because the percentage is a linear function of
    days out that is floored at thirty percent.

    PRD 3.9: "A `STEEL_RETURNABLE` reel returned in `GOOD` condition follows a daily
    decay schedule recorded as `DAILY_DECAY`: the refund percentage is the greater
    of thirty percent and one minus four thousandths multiplied by `days_out`, and
    `refund_usd` is `deposit_usd` multiplied by that percentage, rounded half up to
    two decimals; the percentage itself is never rounded before it multiplies the
    deposit."

    PRD 3.9: "To make the difference concrete, at 120 days out a deposit of 450.00
    refunds 234.00 under the steel schedule against 225.00 under the wood schedule."

    Design: Difficulty/dual_variant_calc/reel_deposit_flat_step_versus_daily_decay_refund
    """
    world = setup_baseline(api, order_overrides={"order_number": "SO-S"})
    order = world["order"]
    lot, reel = _packaged_lot_on_its_own_reel(
        api, world, order, "LOT-S",
        {"reel_serial": "R-S", "reel_type": "STEEL_RETURNABLE", "deposit_usd": 450.00},
    )
    set_clock(api, "2026-08-05T00:00:00Z")
    invoice = _stage_and_invoice(api, order["id"], lot["id"], reel["id"])

    set_clock(api, "2026-12-03T00:00:00Z")
    settled = validate_success(
        api.create_reel_return(
            reel["id"],
            create_reel_return_payload(invoice["id"], "2026-12-03", "GOOD"),
            CLERK,
        ),
        201,
    )

    assert settled["days_out"] == 120
    assert settled["refund_variant_applied"] == "DAILY_DECAY"
    assert_money(
        settled["refund_usd"], 234.00,
        "one minus 0.004 x 120 is 0.52, which beats the thirty percent floor",
    )
    assert_money(settled["forfeited_usd"], 216.00, "the deposit less the refund")
    assert read_reel(api, reel["id"])["status"] == "AVAILABLE", (
        "a GOOD return puts the reel back into the fleet"
    )


def test_the_two_refund_schedules_close_one_account_ledger_together(api):
    """One account holding one reel of each returnable type gets both schedules on the
    same day, and the two settlements together account for every dollar charged.

    PRD 2.9: "The deposit ledger obeys a strict invariant: after every reel return,
    the lifetime total of deposits charged to an account must equal the sum of
    deposits still outstanding, deposit value credited back to the account, and
    deposit value forfeited."

    PRD 3.9: "In the first hop the holding account's `reel_deposit_balance_usd` is
    decreased by the reel's `deposit_usd`, then its `credit_memo_balance_usd` is
    increased by `refund_usd`, then its `forfeited_deposit_total_usd` is increased
    by `forfeited_usd`."

    Design: Difficulty/dual_variant_calc/reel_deposit_flat_step_versus_daily_decay_refund
    """
    world = setup_baseline(
        api, order_overrides={"order_number": "SO-DEP", "ordered_kft": 10.000}
    )
    order = world["order"]
    wood_lot, wood_reel = _packaged_lot_on_its_own_reel(
        api, world, order, "LOT-W",
        {"reel_serial": "R-W", "reel_type": "WOOD_RETURNABLE", "deposit_usd": 450.00},
    )
    steel_lot, steel_reel = _packaged_lot_on_its_own_reel(
        api, world, order, "LOT-S",
        {"reel_serial": "R-S", "reel_type": "STEEL_RETURNABLE", "deposit_usd": 450.00},
        **SECOND_LINE_WINDOW,
    )

    set_clock(api, "2026-08-05T00:00:00Z")
    wood_invoice = _stage_and_invoice(
        api, order["id"], wood_lot["id"], wood_reel["id"]
    )
    steel_invoice = _stage_and_invoice(
        api, order["id"], steel_lot["id"], steel_reel["id"]
    )
    charged = read_customer(api, world["customer"]["id"])
    assert_money(charged["deposit_charged_total_usd"], 900.00, "two deposits charged")
    assert_money(charged["reel_deposit_balance_usd"], 900.00, "both still outstanding")

    set_clock(api, "2026-12-03T00:00:00Z")
    wood_return = validate_success(
        api.create_reel_return(
            wood_reel["id"],
            create_reel_return_payload(wood_invoice["id"], "2026-12-03", "GOOD"),
            CLERK,
        ),
        201,
    )
    steel_return = validate_success(
        api.create_reel_return(
            steel_reel["id"],
            create_reel_return_payload(steel_invoice["id"], "2026-12-03", "GOOD"),
            CLERK,
        ),
        201,
    )

    assert wood_return["days_out"] == steel_return["days_out"] == 120, (
        "the two schedules are being fed identical days out"
    )
    assert steel_return["refund_usd"] - wood_return["refund_usd"] == pytest.approx(
        9.00, abs=0.01
    ), "the variant selector is worth 9.00 on an identical 450.00 deposit"

    ledger = read_customer(api, world["customer"]["id"])
    assert_money(ledger["credit_memo_balance_usd"], 459.00, "225.00 plus 234.00")
    assert_money(ledger["forfeited_deposit_total_usd"], 441.00, "225.00 plus 216.00")
    assert_money(ledger["reel_deposit_balance_usd"], 0.00, "nothing outstanding")
    assert_deposit_ledger_identity(ledger)
    assert read_reel(api, wood_reel["id"])["status"] == "AVAILABLE"
    assert read_reel(api, steel_reel["id"])["status"] == "AVAILABLE"
