"""Wholesale delivery invoicing, the account outstanding-balance ledger, credit
limits, and the validation-precedence guards on invoice/release."""
import pytest

from test_helpers import (
    api_client as _ac,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_delivered_delivery, setup_invoiced_delivery,
    setup_account_with_standing_order,
    create_production_day, schedule_delivery,
)

ADMIN = TEST_USERS["shop_admin_headers"]


# =====================================================================
# Difficulty/transitive_cascade/delivery_invoice_bumps_account_outstanding_depth2 (2)
# GLAZED q24 (24*110=2640) + SESAME q12 (1200) raw 3840 * 0.85 = 3264.
# =====================================================================
def test_invoice_moves_delivery_to_invoiced(api):
    """PRD §3.7: "Invoicing is a ShopAdmin operation moving a delivery
    DELIVERED -> INVOICED, and it is the ledger's money moment."

    Design: Difficulty/transitive_cascade/delivery_invoice_bumps_account_outstanding_depth2
    """
    account, _so, day, delivery = setup_delivered_delivery([("GLAZED", 24), ("SESAME", 12)])
    invoiced = validate_success(_ac.invoice_delivery(day["id"], delivery["id"], ADMIN))
    assert invoiced["status"] == "INVOICED"


def test_invoice_bumps_account_outstanding_balance(api):
    """PRD §3.7: "On a successful invoice, the account's outstanding_balance_cents rises
    by amount_cents as a cascade onto the account."

    Design: Difficulty/transitive_cascade/delivery_invoice_bumps_account_outstanding_depth2
    """
    account, _so, day, delivery = setup_delivered_delivery([("GLAZED", 24), ("SESAME", 12)])
    assert delivery["amount_cents"] == 3264, f"amount got {delivery['amount_cents']}"
    validate_success(_ac.invoice_delivery(day["id"], delivery["id"], ADMIN))
    acct = validate_success(_ac.get_wholesale_account(account["id"], ADMIN))
    assert acct["outstanding_balance_cents"] == 3264, (
        f"outstanding rises by 3264; got {acct['outstanding_balance_cents']}")


# =====================================================================
# Difficulty/compensating_invariant/invoice_then_payment_restores_outstanding_balance (2)
# =====================================================================
def test_payment_lowers_outstanding_balance_to_pre_invoice(api):
    """PRD §3.6: "The intended ledger invariant is that invoicing a delivery and then
    paying its exact amount in full returns the outstanding balance to its pre-invoice
    value."

    Design: Difficulty/compensating_invariant/invoice_then_payment_restores_outstanding_balance
    """
    account, _so, _day, _delivery = setup_invoiced_delivery([("GLAZED", 24), ("SESAME", 12)])
    validate_success(_ac.record_payment(account["id"], {"amount_cents": 3264}, ADMIN))
    acct = validate_success(_ac.get_wholesale_account(account["id"], ADMIN))
    assert acct["outstanding_balance_cents"] == 0, (
        f"full payment of 3264 returns balance to pre-invoice 0; "
        f"got {acct['outstanding_balance_cents']}")


def test_invoice_then_partial_then_full_payment_zeroes_balance(api):
    """PRD §3.6: "The outstanding balance is, at any moment, the sum of all amount_cents
    across that account's invoiced wholesale deliveries minus the sum of all payments
    recorded against the account."

    Design: Difficulty/compensating_invariant/invoice_then_payment_restores_outstanding_balance
    """
    account, _so, _day, _delivery = setup_invoiced_delivery([("GLAZED", 24), ("SESAME", 12)])
    validate_success(_ac.record_payment(account["id"], {"amount_cents": 1264}, ADMIN))
    mid = validate_success(_ac.get_wholesale_account(account["id"], ADMIN))
    assert mid["outstanding_balance_cents"] == 2000, (
        f"3264 - 1264 = 2000; got {mid['outstanding_balance_cents']}")
    validate_success(_ac.record_payment(account["id"], {"amount_cents": 2000}, ADMIN))
    acct = validate_success(_ac.get_wholesale_account(account["id"], ADMIN))
    assert acct["outstanding_balance_cents"] == 0, (
        f"remaining 2000 paid -> 0; got {acct['outstanding_balance_cents']}")


# =====================================================================
# Difficulty/cross_entity_state_dependency/invoice_requires_account_active (2)
# =====================================================================
def test_invoice_suspended_account_rejected(api):
    """PRD §3.7: "it requires the owning wholesale account to be ACTIVE (else
    ERR_ACCOUNT_SUSPENDED)."

    Design: Difficulty/cross_entity_state_dependency/invoice_requires_account_active
    """
    account, _so, day, delivery = setup_delivered_delivery([("GLAZED", 12)])
    validate_success(_ac.suspend_account(account["id"], ADMIN))
    resp = _ac.invoice_delivery(day["id"], delivery["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)


def test_invoice_suspended_account_leaves_delivery_delivered(api):
    """PRD §3.7: "it requires the owning wholesale account to be ACTIVE (else
    ERR_ACCOUNT_SUSPENDED)."

    Design: Difficulty/cross_entity_state_dependency/invoice_requires_account_active
    """
    account, _so, day, delivery = setup_delivered_delivery([("GLAZED", 12)])
    validate_success(_ac.suspend_account(account["id"], ADMIN))
    validate_error(_ac.invoice_delivery(day["id"], delivery["id"], ADMIN),
                   ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)
    fetched = validate_success(_ac.get_wholesale_delivery(day["id"], delivery["id"], ADMIN))
    assert fetched["status"] == "DELIVERED", (
        f"rejected invoice leaves delivery DELIVERED; got {fetched['status']}")


# =====================================================================
# Difficulty/priority_pair_validation_conflict/invoice_state_vs_credit_state_wins (2)
# Delivery still SCHEDULED + would breach credit -> state error wins.
# =====================================================================
def test_invoice_scheduled_delivery_state_error_precedes_credit(api):
    """PRD §2.7: "sixth, that the target resource itself is in the correct status for
    the requested transition (HTTP 409, with the error id varying by entity: ...
    ERR_DELIVERY_INVALID_STATE ...)."
    PRD §3.7: "It requires the delivery to be DELIVERED (else ERR_DELIVERY_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/invoice_state_vs_credit_state_wins
    """
    # amount 3264 against tiny credit_limit 100; delivery left SCHEDULED (never picked).
    account, so, _products = setup_account_with_standing_order(
        [("GLAZED", 24), ("SESAME", 12)], discount_pct=0.15, credit_limit_cents=100)
    day = create_production_day()
    delivery = schedule_delivery(day["id"], so["id"],
                                 "2027-06-03T08:00:00Z", "2027-06-03T09:00:00Z")
    resp = _ac.invoice_delivery(day["id"], delivery["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_INVALID_STATE.value)


def test_invoice_scheduled_delivery_not_credit_error(api):
    """PRD §2.7: "an earlier failure masks a later one. The order is: ... fifth, that
    the parent ProductionDay is in the correct status for the operation
    (ERR_DAY_INVALID_STATE, HTTP 409); and sixth, that the target resource itself is in
    the correct status for the requested transition."

    Design: Difficulty/priority_pair_validation_conflict/invoice_state_vs_credit_state_wins
    """
    account, so, _products = setup_account_with_standing_order(
        [("GLAZED", 24), ("SESAME", 12)], discount_pct=0.15, credit_limit_cents=100)
    day = create_production_day()
    delivery = schedule_delivery(day["id"], so["id"],
                                 "2027-06-03T10:00:00Z", "2027-06-03T11:00:00Z")
    err = validate_error(_ac.invoice_delivery(day["id"], delivery["id"], ADMIN),
                         ApiErrorId.ERR_DELIVERY_INVALID_STATE.value)
    assert err["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value


# =====================================================================
# Corner/validations/error_credit_limit_exceeded_on_invoice  (1)
# =====================================================================
def test_credit_limit_exceeded_on_invoice(api):
    """PRD §3.7: "it requires that the account's current outstanding_balance_cents plus
    this delivery's amount_cents not exceed the account's credit_limit_cents (else
    ERR_CREDIT_LIMIT_EXCEEDED, HTTP 402)."

    Design: Corner/validations/error_credit_limit_exceeded_on_invoice
    """
    account, _so, day, delivery = setup_delivered_delivery(
        [("GLAZED", 24), ("SESAME", 12)], credit_limit_cents=3263)
    assert delivery["amount_cents"] == 3264
    validate_error(_ac.invoice_delivery(day["id"], delivery["id"], ADMIN),
                   ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)


# =====================================================================
# Corner/validations/credit_limit_boundary_invoice_succeeds  (1)
# =====================================================================
def test_credit_limit_boundary_invoice_succeeds(api):
    """PRD §3.7: "it requires that the account's current outstanding_balance_cents plus
    this delivery's amount_cents not exceed the account's credit_limit_cents (else
    ERR_CREDIT_LIMIT_EXCEEDED, HTTP 402)."

    Design: Corner/validations/credit_limit_boundary_invoice_succeeds
    """
    account, _so, day, delivery = setup_delivered_delivery(
        [("GLAZED", 24), ("SESAME", 12)], credit_limit_cents=3264)
    assert delivery["amount_cents"] == 3264
    invoiced = validate_success(_ac.invoice_delivery(day["id"], delivery["id"], ADMIN))
    assert invoiced["status"] == "INVOICED"
    acct = validate_success(_ac.get_wholesale_account(account["id"], ADMIN))
    assert acct["outstanding_balance_cents"] == 3264, (
        f"0 + 3264 == limit 3264 is allowed (<=); got {acct['outstanding_balance_cents']}")
