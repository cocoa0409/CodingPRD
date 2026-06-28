"""Cascading side effects and conservation invariants: fulfill stock cascade,
special-order confirm billing cascade, compensating restock on cancel, void
restoring balance, PO receive restock, and balance reconciliation after pay.

Covers Difficulty queue rules transitive_cascade and compensating_invariant,
plus the Corner queue endpoints and derived_field_reconciliation sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    create_vendor, create_product, create_account,
    setup_placed_order, setup_fulfilled_order, setup_invoiced_order,
    setup_quoted_special_order, setup_submitted_po,
    api_client, SALES, INVENTORY, ACCOUNTS,
    make_contractor_headers,
)


# ─── Difficulty: transitive_cascade ─────────────────────────────────────────

def test_fulfill_cascades_line_to_onhand_to_reorder_flag(api):
    """PRD 3.4: "A depth-three cascade then runs. Each `PENDING` line moves to
    `status` `FULFILLED`; that transition debits the line's product `on_hand` by
    the line's `qty`; and that change to `on_hand` recomputes the product's
    `reorder_needed` flag, flipping it true when stock has fallen to or below the
    reorder point."

    Design: Difficulty/transitive_cascade/fulfill_cascades_line_to_onhand_to_reorder_flag_depth3
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, reorder_point=2,
                             reorder_qty=20, on_hand=10)
    placed = setup_placed_order(product["id"], qty=8)
    fulfilled = validate_success(api.fulfill_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES), 200)

    data, _ = validate_paginated(api.list_order_lines_for_order(placed["id"], SALES))
    assert data[0]["status"] == "FULFILLED"

    prod = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert prod["on_hand"] == 2, "10 debited by 8"
    assert prod["reorder_needed"] is True, "2 <= reorder_point 2 (inclusive)"


def test_fulfill_debits_onhand_by_line_qty(api):
    """PRD 2.8: "every debit of `on_hand` at fulfillment is matched, on a
    compensating cancellation, by an exact restoration of the same quantity."
    PRD 3.4: "that transition debits the line's product `on_hand` by the line's
    `qty`."

    Design: Difficulty/transitive_cascade/fulfill_cascades_line_to_onhand_to_reorder_flag_depth3
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, reorder_point=2,
                             reorder_qty=20, on_hand=10)
    placed = setup_placed_order(product["id"], qty=8)
    validate_success(api.fulfill_order(
        placed["id"], {"expected_sales_order_version": placed["version"]}, SALES), 200)
    prod = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert prod["on_hand"] == 2


def test_special_order_confirm_cascades_invoice_to_balance(api):
    """PRD 3.9: "Confirmation also runs a depth-two cascade: it creates an
    `Invoice` whose `amount_cents` equals `confirmed_total_cents` and whose
    `status` is `ISSUED`, and the owning account's `balance_cents` is recomputed
    to include the new invoice."

    Design: Difficulty/transitive_cascade/special_order_confirm_cascades_invoice_to_balance_depth2
    """
    quoted, vendor, account = setup_quoted_special_order(
        qty=5, quoted_unit_cents=4000)  # goods 20000 < 50000 -> +1500 = 21500
    ch = make_contractor_headers(account["id"])
    confirmed = validate_success(api.confirm_special_order(quoted["id"], ch), 200)
    assert confirmed["confirmed_total_cents"] == 21500

    acct = validate_success(api.get_contractor_account(account["id"], ACCOUNTS), 200)
    assert acct["balance_cents"] == 21500


def test_special_order_confirm_locks_total_with_surcharge(api):
    """PRD 3.9: "On confirmation the `confirmed_total_cents` is locked: it is
    the goods value (`quoted_unit_cents` multiplied by `qty`) plus a drop-ship
    surcharge, where the surcharge is 0 when the goods value is at least 50000
    cents (free shipping at or above that threshold) and 1500 cents otherwise."

    Design: Difficulty/transitive_cascade/special_order_confirm_cascades_invoice_to_balance_depth2
    """
    quoted, vendor, account = setup_quoted_special_order(
        qty=5, quoted_unit_cents=4000)
    ch = make_contractor_headers(account["id"])
    confirmed = validate_success(api.confirm_special_order(quoted["id"], ch), 200)
    # 4000 * 5 = 20000 goods, below 50000 -> +1500 surcharge.
    assert confirmed["confirmed_total_cents"] == 20000 + 1500


# ─── Difficulty: compensating_invariant ─────────────────────────────────────

def test_cancel_fulfilled_order_restores_onhand_exactly(api):
    """PRD 3.5: "each `FULFILLED` line moves to `RESTOCKED` and restores its
    product's `on_hand` by exactly the line's `qty` — preserving the inventory
    conservation invariant."

    Design: Difficulty/compensating_invariant/cancel_fulfilled_order_restores_onhand_units_invariant
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=10)
    fulfilled = setup_fulfilled_order(product["id"], qty=8)  # on_hand now 2
    cancelled = validate_success(api.cancel_order(fulfilled["id"], SALES), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"

    prod = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert prod["on_hand"] == 10, "exactly the 8 restored (2 -> 10)"

    data, _ = validate_paginated(api.list_order_lines_for_order(fulfilled["id"], SALES))
    assert data[0]["status"] == "RESTOCKED"


def test_cancel_fulfilled_order_moves_lines_to_restocked(api):
    """PRD 3.5: "Cancelling a `FULFILLED` order is a fuller compensation: each
    `FULFILLED` line moves to `RESTOCKED` and restores its product's `on_hand`
    by exactly the line's `qty` — preserving the inventory conservation
    invariant."

    Design: Difficulty/compensating_invariant/cancel_fulfilled_order_restores_onhand_units_invariant
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=10)
    fulfilled = setup_fulfilled_order(product["id"], qty=8)
    validate_success(api.cancel_order(fulfilled["id"], SALES), 200)
    data, _ = validate_paginated(api.list_order_lines_for_order(fulfilled["id"], SALES))
    assert data[0]["status"] == "RESTOCKED"


def test_void_invoice_restores_account_balance_exactly(api):
    """PRD 3.6: "Voiding an invoice is the compensating money operation: from
    `INVOICED` it moves `payment_status` to `VOIDED`, again requiring an
    `ISSUED` invoice on the order (else `ERR_INVOICE_NOT_FOUND`), setting the
    invoice's `status` to `VOID`, and recomputing the account's `balance_cents`
    back to exactly its pre-invoice value."

    Design: Difficulty/compensating_invariant/void_invoice_restores_account_balance_money_invariant
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    invoiced = setup_invoiced_order(product["id"], qty=10,
                                    contractor_account_id=account["id"])
    acct_before = validate_success(
        api.get_contractor_account(account["id"], ACCOUNTS), 200)
    assert acct_before["balance_cents"] == 10000

    voided = validate_success(api.void_invoice(invoiced["id"], ACCOUNTS), 200)
    assert voided["payment_status"] == "VOIDED"

    acct_after = validate_success(
        api.get_contractor_account(account["id"], ACCOUNTS), 200)
    assert acct_after["balance_cents"] == 0, "restored to pre-invoice value"


def test_void_invoice_sets_payment_status_voided(api):
    """PRD 3.6: "from `INVOICED` it moves `payment_status` to `VOIDED`, again
    requiring an `ISSUED` invoice on the order (else `ERR_INVOICE_NOT_FOUND`),
    setting the invoice's `status` to `VOID`."

    Design: Difficulty/compensating_invariant/void_invoice_restores_account_balance_money_invariant
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    invoiced = setup_invoiced_order(product["id"], qty=10,
                                    contractor_account_id=account["id"])
    voided = validate_success(api.void_invoice(invoiced["id"], ACCOUNTS), 200)
    assert voided["payment_status"] == "VOIDED"


# ─── Corner: endpoints ──────────────────────────────────────────────────────

def test_po_receive_restocks_and_clears_reorder_flag(api):
    """PRD 3.10: "Receiving a submitted purchase order advances it from
    `SUBMITTED` to `RECEIVED` and restocks the catalog: for each line the line's
    product `on_hand` increases by the line's `qty`, and that product's
    `reorder_needed` is recomputed, which may clear the flag now that stock has
    risen."

    Design: Corner/endpoints/po_receive_restocks_and_clears_reorder_flag
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, reorder_point=5,
                             reorder_qty=50, on_hand=1)
    before = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert before["reorder_needed"] is True, "1 <= reorder_point 5"

    submitted = setup_submitted_po(vendor, product["id"], qty=50,
                                   unit_cost_cents=500)
    validate_success(api.receive_purchase_order(submitted["id"], INVENTORY), 200)

    prod = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert prod["on_hand"] == 51, "1 + 50"
    assert prod["reorder_needed"] is False, "51 > reorder_point 5"


def test_cancel_placed_order_restocks_lines_no_onhand_change(api):
    """PRD 3.5: "Cancelling a `PLACED` order moves all of its lines to `status`
    `RESTOCKED`; because a placed order never debited stock, no `on_hand` change
    occurs."

    Design: Corner/endpoints/cancel_placed_unbilled_order_restocks_lines_no_onhand_change
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    placed = setup_placed_order(product["id"], qty=10)
    cancelled = validate_success(api.cancel_order(placed["id"], SALES), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"

    data, _ = validate_paginated(api.list_order_lines_for_order(placed["id"], SALES))
    assert data[0]["status"] == "RESTOCKED"

    prod = validate_success(api.get_product(product["id"], INVENTORY), 200)
    assert prod["on_hand"] == 100, "PLACED never debited, so unchanged"


# ─── Corner: cross_cutting (derived_field_reconciliation) ───────────────────

def test_balance_reconciles_to_zero_after_pay(api):
    """PRD 3.6: "The invoice's `status` moves to `PAID`, which drops it out of
    the issued-invoice sweep, so the account's `balance_cents` is recomputed
    downward."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_reconciles_after_pay
    """
    vendor = create_vendor()
    product = create_product(vendor_id=vendor["id"], sell_mode="EACH",
                             list_price_cents=1000, on_hand=100)
    account = create_account(credit_limit_cents=1000000, net_terms_days=30)
    invoiced = setup_invoiced_order(product["id"], qty=10,
                                    contractor_account_id=account["id"])
    paid = validate_success(api.pay_order(invoiced["id"], ACCOUNTS), 200)
    assert paid["payment_status"] == "PAID"

    acct = validate_success(api.get_contractor_account(account["id"], ACCOUNTS), 200)
    assert acct["balance_cents"] == 0, "PAID invoice leaves the ISSUED sweep"
