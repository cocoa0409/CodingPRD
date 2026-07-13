"""Buyer invoice: the two independent payment/fulfillment axes, overpayment and
unpaid-release guards, shipping, and provisional-vs-final storage accrual.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_single_hammer,
    set_clock,
    assert_invoice_totals_consistent,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ─── Corner: payment / fulfillment guards and shipping ───────────────────

def test_overpayment_rejected(api):
    """PRD §3.6: "The payment must not exceed the remaining balance: if
    `amount_paid_cents` plus the new `amount_cents` would exceed `total_due_cents`,
    the payment is rejected with `ERR_OVERPAYMENT` (HTTP 409)."

    Design: Corner/validations/corner_payment_overpayment_returns_conflict
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000)
    assert bag["invoice"]["total_due_cents"] == 312_500
    res = api.pay_invoice(bag["invoice"]["id"], {"amount_cents": 400_000}, STAFF)
    validate_error(res, "ERR_OVERPAYMENT")


def test_fulfill_before_paid_rejected(api):
    """PRD §3.6: "Operations staff fulfill an invoice only when its
    `fulfillment_status` is `READY` (otherwise `ERR_INVALID_STATE`) and its
    `payment_status` is `PAID`; an unpaid or partially paid invoice cannot be
    released, and the attempt is rejected with `ERR_INVOICE_NOT_PAID` (HTTP 409)."

    Design: Corner/validations/corner_fulfill_before_paid_returns_conflict
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000,
                              clock="2026-06-10T00:00:00Z")
    validate_success(
        api.ready_invoice(bag["invoice"]["id"], {"fulfillment_method": "PICKUP"}, STAFF), 200
    )
    res = api.fulfill_invoice(bag["invoice"]["id"], STAFF)
    validate_error(res, "ERR_INVOICE_NOT_PAID")


def test_ready_ship_sets_shipping_fee_and_total(api):
    """PRD §3.6: "It sets `fulfillment_method` to the supplied method; sets
    `shipping_fee_cents` to the supplied amount when the method is `SHIP` and to 0
    when the method is `PICKUP`; finalizes `storage_fee_cents` using the current
    clock; recomputes `total_due_cents`".

    Design: Corner/endpoints/corner_ready_ship_sets_shipping_fee
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000,
                              clock="2026-06-10T00:00:00Z", bid_type="ONLINE")
    res = api.ready_invoice(
        bag["invoice"]["id"],
        {"fulfillment_method": "SHIP", "shipping_fee_cents": 2500},
        STAFF,
    )
    data = validate_success(res, 200)
    assert data["shipping_fee_cents"] == 2500
    assert data["total_due_cents"] == 315_000
    assert data["fulfillment_status"] == "READY"
    assert_invoice_totals_consistent(data)


# ─── Difficulty: parallel payment/fulfillment axes on one invoice ────────

def test_payment_axis_advances_independently(api):
    """PRD §3.6: "The `payment_status` axis — `UNPAID`, `PARTIALLY_PAID`, or
    `PAID`, beginning at `UNPAID` — is entirely separate from the
    `fulfillment_status` axis — `PENDING`, `READY`, `PICKED_UP`, or `SHIPPED`,
    beginning at `PENDING`."
    PRD §3.6: "`payment_status` is set to `PAID` when `amount_paid_cents` equals
    `total_due_cents`".

    Design: Difficulty/non_linear_state_machine/nl_invoice_parallel_payment_and_fulfillment
    """
    bag = setup_single_hammer(300_000, starting_bid_cents=200_000,
                              clock="2026-06-10T00:00:00Z")
    assert bag["invoice"]["total_due_cents"] == 375_000
    assert bag["invoice"]["payment_status"] == "UNPAID"
    assert bag["invoice"]["fulfillment_status"] == "PENDING"
    data = validate_success(
        api.pay_invoice(bag["invoice"]["id"], {"amount_cents": 375_000}, STAFF), 200
    )
    assert data["payment_status"] == "PAID"
    assert data["fulfillment_status"] == "PENDING"


def test_fulfillment_axis_advances_independently(api):
    """PRD §3.6: "Readying an invoice moves the fulfillment axis and finalizes the
    storage charge."
    PRD §3.6: "advances `fulfillment_status` `PENDING → READY`; and increments the
    invoice's `version` by one."

    Design: Difficulty/non_linear_state_machine/nl_invoice_parallel_payment_and_fulfillment
    """
    bag = setup_single_hammer(300_000, starting_bid_cents=200_000,
                              clock="2026-06-10T00:00:00Z")
    validate_success(
        api.pay_invoice(bag["invoice"]["id"], {"amount_cents": 375_000}, STAFF), 200
    )
    data = validate_success(
        api.ready_invoice(bag["invoice"]["id"], {"fulfillment_method": "PICKUP"}, STAFF), 200
    )
    assert data["fulfillment_status"] == "READY"
    assert data["payment_status"] == "PAID"


# ─── Difficulty: provisional (hammer) vs final (ready) storage fee ───────

def test_storage_fee_provisional_zero_at_hammer(api):
    """PRD §3.5: "when the invoice is created (the first hammer for that buyer in
    that auction), its `storage_start_at` is set to the current logical clock and
    its `storage_fee_cents` is fixed at 0."

    Design: Difficulty/dual_variant_calc/dv_invoice_storage_provisional_vs_final
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000,
                              clock="2026-06-10T00:00:00Z")
    assert bag["invoice"]["storage_fee_cents"] == 0
    assert bag["invoice"]["total_due_cents"] == 312_500


def test_storage_fee_final_accrues_at_ready(api):
    """PRD §3.6: "The first seven days (`FREE_STORAGE_DAYS`) are free: chargeable
    days are the elapsed whole days minus seven, never less than zero. The final
    `storage_fee_cents` is the chargeable days multiplied by 500 cents per day
    (`DAILY_STORAGE_CENTS`)."

    Design: Difficulty/dual_variant_calc/dv_invoice_storage_provisional_vs_final
    """
    bag = setup_single_hammer(250_000, starting_bid_cents=200_000,
                              clock="2026-06-10T00:00:00Z")
    set_clock("2026-06-20T00:00:00Z")  # 10 elapsed days -> 3 chargeable -> 1500
    data = validate_success(
        api.ready_invoice(bag["invoice"]["id"], {"fulfillment_method": "PICKUP"}, STAFF), 200
    )
    assert data["storage_fee_cents"] == 1500
    assert data["total_due_cents"] == 314_000
    assert_invoice_totals_consistent(data)


# ─── Difficulty: storage free-days boundary (7 -> 0, 8 -> 500) ───────────

def test_storage_zero_at_exactly_seven_days(api):
    """PRD §3.6: "Thus exactly seven days elapsed yields no charge, while the
    eighth day yields one day's charge of 500 cents."

    Design: Difficulty/boundary_precision_check/bp_storage_free_days_boundary
    """
    bag = setup_single_hammer(100_000, starting_bid_cents=100_000,
                              clock="2026-06-10T00:00:00Z")
    set_clock("2026-06-17T00:00:00Z")  # exactly 7 elapsed days
    data = validate_success(
        api.ready_invoice(bag["invoice"]["id"], {"fulfillment_method": "PICKUP"}, STAFF), 200
    )
    assert data["storage_fee_cents"] == 0


def test_storage_one_day_at_eighth_day(api):
    """PRD §3.6: "Thus exactly seven days elapsed yields no charge, while the
    eighth day yields one day's charge of 500 cents."

    Design: Difficulty/boundary_precision_check/bp_storage_free_days_boundary
    """
    bag = setup_single_hammer(100_000, starting_bid_cents=100_000,
                              clock="2026-06-10T00:00:00Z")
    set_clock("2026-06-18T00:00:00Z")  # 8 elapsed days -> 1 chargeable
    data = validate_success(
        api.ready_invoice(bag["invoice"]["id"], {"fulfillment_method": "PICKUP"}, STAFF), 200
    )
    assert data["storage_fee_cents"] == 500
