"""Delivery verification and financial reconciliation: cumulative vs strict
window variants, payment reversion across the parallel order dimensions, the
money conservation invariant, exact-amount payments, append-only payment
reads, and the two-check cap (PRD §2.4, §3.6, §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_money_eq,
    assert_order_books_balance,
    deliver,
    get_order,
    get_success_data,
    make_customer_headers,
    mini_chain,
    pay,
    record_check,
    w1500_chain,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / delivery_window_cumulative_vs_strict
# Deliveries 500 then 400 against a 855.00 window: check 1 (P=500) fails and
# flags; check 2 (P=900) passes cumulatively while the strict per-delivery
# variant fails on the 400 chunk.
# ---------------------------------------------------------------------------

def test_cumulative_window_passes_when_chunks_sum_over_threshold(api):
    """PRD §3.7: "From these, `baseline_sqft` is ninety-five percent of `promised_sqft` rounded half-up to two decimals, and the authoritative `window_size` is sixty percent of the sum of `baseline_sqft` and `prior_payments`, rounded half-up to two decimals. The check's `in_window` verdict compares delivered against that window: the order passes when `delivered_cumulative` is at least `window_size`."
    PRD §3.7: "Recording the check writes `chargeable_after` into the order's `chargeable_amount`, sets the order's `delivery_flagged` to true when the check is out of window, and clears `delivery_flagged` when a later check lands in window."

    Design: Difficulty/dual_variant_calc/delivery_window_cumulative_vs_strict
    """
    bundle = w1500_chain(api)
    o_id = bundle["o"]["id"]

    deliver(api, o_id, 500)
    chk1 = record_check(api, o_id)
    assert chk1["in_window"] is False, "check 1: 500 < 855.00"
    assert_money_eq(chk1["window_size"], 855.00, "check 1 window_size")
    assert get_order(api, o_id)["delivery_flagged"] is True, (
        "an out-of-window check flags the order"
    )

    deliver(api, o_id, 400)
    chk2 = record_check(api, o_id)
    assert chk2["check_index"] == 2
    assert_money_eq(chk2["baseline_sqft"], 1425.00, "baseline = 95% of 1500")
    assert_money_eq(chk2["window_size"], 855.00, "window_size")
    assert_money_eq(chk2["delivered_cumulative"], 900, "delivered_cumulative")
    assert chk2["in_window"] is True, "cumulative variant: 900 >= 855.00"
    assert get_order(api, o_id)["delivery_flagged"] is False, (
        "a later in-window check clears the flag"
    )


def test_strict_variant_fails_on_undersized_latest_chunk(api):
    """PRD §3.7: "An informational dual variant, `strict_in_window`, instead requires each delivery chunk to stand on its own — the chunk delivered since the previous check (the full `delivered_cumulative` for the first check) must reach sixty percent of `baseline_sqft`, rounded half-up to two decimals. Consider an order promising 1500 square feet with nothing yet paid: the baseline is 1425.00 and both windows start at 855.00; deliveries of 500 and then 400 leave `delivered_cumulative` at 900, so the cumulative `in_window` passes, while `strict_in_window` fails because the latest chunk of 400 never reached 855.00 on its own."
    PRD §3.7: "Shortfalls are priced, not just flagged. The check's `shortfall_sqft` is the promised amount minus the delivered amount, floored at zero; the `blended_rate` is the order's `total_price` divided by its `turf_sqft`, rounded half-up to four decimal places; the `shortfall_credit` is the shortfall multiplied by that rate, rounded half-up to two decimals; and `chargeable_after` is `total_price` minus the credit."

    Design: Difficulty/dual_variant_calc/delivery_window_cumulative_vs_strict
    """
    bundle = w1500_chain(api)
    o_id = bundle["o"]["id"]

    deliver(api, o_id, 500)
    record_check(api, o_id)
    deliver(api, o_id, 400)
    chk2 = record_check(api, o_id)

    assert chk2["strict_in_window"] is False, (
        "strict variant: latest chunk 400 < 855.00"
    )
    assert chk2["in_window"] is True
    assert_money_eq(chk2["shortfall_sqft"], 600, "shortfall = 1500 - 900")
    assert_money_eq(chk2["chargeable_after"], 1013.83,
                    "1689.73 - round2(600 * round4(1689.73/1500))")
    assert_money_eq(get_order(api, o_id)["chargeable_amount"], 1013.83,
                    "the check rewrites chargeable_amount")


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine /
#   order_parallel_dimensions_with_payment_reversion
# payment_status cycles PAID -> PENDING when a check raises chargeable above
# total_paid; fulfillment status is untouched; the dimensions join at CLOSED.
# ---------------------------------------------------------------------------

def _paid_then_underdelivered_order(api):
    """W1500 order DELIVERED with 900 sqft; check 1 -> chargeable 1013.83;
    payment 1013.83 -> PAID; top-up 300; check 2 -> chargeable 1351.78."""
    bundle = w1500_chain(api)
    o_id = bundle["o"]["id"]
    deliver(api, o_id, 900)
    record_check(api, o_id)
    pay(api, o_id, 1013.83)
    assert get_order(api, o_id)["payment_status"] == "PAID"
    deliver(api, o_id, 300)
    chk2 = record_check(api, o_id)
    return bundle, chk2


def test_check_raising_chargeable_reverts_paid_to_pending(api):
    """PRD §3.7: "`payment_status` is `PAID` exactly when `amount_due` is zero, `PENDING` otherwise — so a delivery check that raises the chargeable amount above what has been paid flips a `PAID` order back to `PENDING`."
    PRD §3.7: "`chargeable_amount` starts at `total_price` when the order is created and is overwritten by each delivery check; `total_paid` is the sum of the order's payment amounts; `amount_due` is `chargeable_amount` minus `total_paid`, floored at zero; `credit_balance` is the overpayment, `total_paid` minus `chargeable_amount`, floored at zero; and `payment_status` is `PAID` exactly when `amount_due` is zero, `PENDING` otherwise"

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_with_payment_reversion
    """
    bundle, chk2 = _paid_then_underdelivered_order(api)
    o_id = bundle["o"]["id"]

    assert_money_eq(chk2["window_size"], 1463.30,
                    "round2((1425.00 + 1013.83) * 0.60)")
    assert chk2["in_window"] is False, "1200 < 1463.30"
    assert_money_eq(chk2["chargeable_after"], 1351.78, "1689.73 - 337.95")

    order = get_order(api, o_id)
    assert order["payment_status"] == "PENDING", "PAID -> PENDING reversion"
    assert_money_eq(order["amount_due"], 337.95, "1351.78 - 1013.83")
    assert_money_eq(order["total_paid"], 1013.83, "total_paid")
    assert_money_eq(order["chargeable_amount"], 1351.78, "chargeable_amount")


def test_payment_reversion_leaves_fulfillment_and_joins_at_close(api):
    """PRD §3.6: "If the order is already `PAID` at that moment, the two parallel dimensions join and the order drops straight to `CLOSED`."
    PRD §3.6: "The symmetric join also holds: when a payment flips an `INSTALLED` order to `PAID`, the order auto-transitions to `CLOSED`."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_with_payment_reversion
    """
    bundle, _chk2 = _paid_then_underdelivered_order(api)
    o_id = bundle["o"]["id"]
    cust = bundle["customer_headers"]

    # The fulfillment dimension is unaffected by the payment reversion.
    assert get_order(api, o_id)["status"] == "DELIVERED"

    get_success_data(api.install_start(o_id, cust))
    installed = get_success_data(api.install_complete(o_id, cust))
    assert installed["status"] == "INSTALLED", (
        "no auto-join while payment_status is PENDING"
    )

    pay(api, o_id, 337.95)
    closed = get_order(api, o_id)
    assert closed["payment_status"] == "PAID"
    assert closed["status"] == "CLOSED", (
        "a payment flipping an INSTALLED order to PAID auto-transitions to CLOSED"
    )


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant /
#   order_money_conservation_across_checks_and_payments
# ---------------------------------------------------------------------------

def test_money_conserved_through_check_and_payment(api):
    """PRD §3.7: "The books always balance: `total_paid` plus `amount_due` minus `credit_balance` equals `chargeable_amount` at every moment."
    PRD §3.7: "Payments themselves are exact-amount instruments. A `SalesRep` records a payment with an `amount` equal to the order's current `amount_due` — no partials, no overpayments — and a `method` of `CHECK` or `CARD`; any other amount, or any payment while `amount_due` is zero, is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Difficulty/compensating_invariant/order_money_conservation_across_checks_and_payments
    """
    bundle = w1500_chain(api)
    o_id = bundle["o"]["id"]
    deliver(api, o_id, 900)

    chk1 = record_check(api, o_id)
    assert_money_eq(chk1["chargeable_after"], 1013.83, "check 1 chargeable_after")
    order = get_order(api, o_id)
    assert_money_eq(order["chargeable_amount"], 1013.83, "chargeable_amount")
    assert_money_eq(order["total_paid"], 0.00, "total_paid")
    assert_money_eq(order["amount_due"], 1013.83, "amount_due")
    assert_money_eq(order["credit_balance"], 0.00, "credit_balance")
    assert order["payment_status"] == "PENDING"
    assert_order_books_balance(order)

    pay(api, o_id, 1013.83)
    order = get_order(api, o_id)
    assert order["payment_status"] == "PAID"
    assert_money_eq(order["amount_due"], 0.00, "amount_due after payment")
    assert_order_books_balance(order)


def test_money_conserved_through_reversion_and_second_payment(api):
    """PRD §3.7: "The books always balance: `total_paid` plus `amount_due` minus `credit_balance` equals `chargeable_amount` at every moment."
    PRD §3.7: "The order's money fields then reconcile, as they do after every payment as well."

    Design: Difficulty/compensating_invariant/order_money_conservation_across_checks_and_payments
    """
    bundle, chk2 = _paid_then_underdelivered_order(api)
    o_id = bundle["o"]["id"]

    assert_money_eq(chk2["chargeable_after"], 1351.78, "check 2 chargeable_after")
    order = get_order(api, o_id)
    assert_money_eq(order["chargeable_amount"], 1351.78, "chargeable_amount")
    assert_money_eq(order["total_paid"], 1013.83, "total_paid")
    assert_money_eq(order["amount_due"], 337.95, "amount_due")
    assert order["payment_status"] == "PENDING", "reversion PAID -> PENDING"
    assert_order_books_balance(order)

    pay(api, o_id, 337.95)
    order = get_order(api, o_id)
    assert order["payment_status"] == "PAID"
    assert_money_eq(order["total_paid"], 1351.78, "total_paid")
    assert_money_eq(order["amount_due"], 0.00, "amount_due")
    assert_money_eq(order["credit_balance"], 0.00, "credit_balance")
    assert_order_books_balance(order)


# ---------------------------------------------------------------------------
# Corner: errors / payment_wrong_amount_returns_mismatch
# ---------------------------------------------------------------------------

def test_payment_wrong_amount_returns_mismatch(api):
    """PRD §3.7: "Payments themselves are exact-amount instruments. A `SalesRep` records a payment with an `amount` equal to the order's current `amount_due` — no partials, no overpayments — and a `method` of `CHECK` or `CARD`; any other amount, or any payment while `amount_due` is zero, is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.7: "When the payment brings `amount_due` to zero, `payment_status` becomes `PAID` — and if the order is `INSTALLED` at that moment, it auto-transitions to `CLOSED` per §3.6."

    Design: Corner/errors/payment_wrong_amount_returns_mismatch
    """
    bundle = mini_chain(api, stage="placed")
    o_id = bundle["o"]["id"]

    resp = api.create_payment(o_id, {"amount": 100.00, "method": "CARD"}, SALES)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH, 422)

    payment = validate_success(
        api.create_payment(o_id, {"amount": 175.47, "method": "CARD"}, SALES), 201
    )
    assert_money_eq(payment["amount"], 175.47, "payment amount")
    order = get_order(api, o_id)
    assert order["payment_status"] == "PAID"
    assert_money_eq(order["total_paid"], 175.47, "total_paid")


# ---------------------------------------------------------------------------
# Corner: entities / payment_entity_is_append_only
# ---------------------------------------------------------------------------

def test_payment_entity_is_append_only(api):
    """PRD §2.4: "Three append-only sub-resources break this pattern: a `Payment`, a `DeliveryCheck`, and a `WateringLog` each carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on them."
    PRD §3.7: "Each payment belongs to its order (`order_id`) and stamps `received_at` from the server clock. When the payment brings `amount_due` to zero, `payment_status` becomes `PAID` — and if the order is `INSTALLED` at that moment, it auto-transitions to `CLOSED` per §3.6. An order's checks and payments can each be listed under the order."

    Design: Corner/entities/payment_entity_is_append_only
    """
    bundle = mini_chain(api, stage="placed")
    o_id = bundle["o"]["id"]
    payment = validate_success(
        api.create_payment(o_id, {"amount": 175.47, "method": "CARD"}, SALES), 201
    )
    assert_money_eq(payment["amount"], 175.47, "payment amount")
    assert "version" not in payment, "append-only: no version"
    assert "updated_at" not in payment, "append-only: no updated_at"
    assert payment.get("id") and payment.get("created_at")

    data, meta = validate_paginated(api.list_payments(o_id, SALES))
    assert meta["total_count"] == 1
    assert data[0]["id"] == payment["id"]
    assert "version" not in data[0] and "updated_at" not in data[0]


# ---------------------------------------------------------------------------
# Corner: errors / third_delivery_check_returns_invalid_state
# ---------------------------------------------------------------------------

def test_third_delivery_check_returns_invalid_state(api):
    """PRD §3.7: "A `SalesRep` records a delivery check against an order to verify that deliveries are keeping pace with the promise — at most two checks per order, `check_index` 1 and then 2, with a third rejected as `ERR_INVALID_STATE`."

    Design: Corner/errors/third_delivery_check_returns_invalid_state
    """
    bundle = mini_chain(api, stage="delivered", accepted_sqft=100)
    o_id = bundle["o"]["id"]
    chk1 = record_check(api, o_id)
    assert chk1["check_index"] == 1
    deliver(api, o_id, 100)  # DELIVERED -> DELIVERED top-up
    chk2 = record_check(api, o_id)
    assert chk2["check_index"] == 2

    resp = api.create_delivery_check(o_id, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
