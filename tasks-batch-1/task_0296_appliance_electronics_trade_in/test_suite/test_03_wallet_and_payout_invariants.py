"""Wallet-ledger settlement (store-credit vs external) and the payout-reversal
conservation invariants over wallet_balance_cents and lifetime_payout_cents.
"""
import pytest
from test_helpers import (
    validate_success,
    setup_catalog_model_customer,
    create_received_trade_in,
    inspect,
    get_payouts,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
FINANCE = TEST_USERS["finance_operator_headers"]


def _accept_at_60000(api, customer, model):
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=[])
    return ti


# ─────────────────────────────────────────────────────────────────────────────
# dual_variant_calc / wallet_settlement_store_credit_vs_external_diverge
# ─────────────────────────────────────────────────────────────────────────────

def test_store_credit_moves_wallet_balance(api):
    """PRD §3.7: "when and only when the `method` is `STORE_CREDIT`, the customer's
    `wallet_balance_cents` is increased by the same amount; for `ACH` and `CHECK`
    payouts the wallet balance is untouched and only the lifetime total moves."

    After one STORE_CREDIT payout of 60000, wallet_balance_cents is 60000.

    Design: Difficulty/dual_variant_calc/wallet_settlement_store_credit_vs_external_diverge
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti1 = _accept_at_60000(api, customer, model)
    validate_success(api.create_payout(ti1["id"], {"method": "STORE_CREDIT"}, FINANCE), expected_status=201)

    cust = validate_success(api.get_customer(customer["id"], ADMIN))
    assert cust["wallet_balance_cents"] == 60000


def test_external_payout_moves_only_lifetime_not_wallet(api):
    """PRD §3.7: "The customer's `lifetime_payout_cents` is increased by the payout
    amount in every case."
    PRD §3.7: "for `ACH` and `CHECK` payouts the wallet balance is untouched and only
    the lifetime total moves."

    Two 60000 payouts on the same customer — first STORE_CREDIT, then ACH — leave the
    wallet at 60000 (only the store-credit one moved it) but lifetime at 120000 (both).

    Design: Difficulty/dual_variant_calc/wallet_settlement_store_credit_vs_external_diverge
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti1 = _accept_at_60000(api, customer, model)
    validate_success(api.create_payout(ti1["id"], {"method": "STORE_CREDIT"}, FINANCE), expected_status=201)
    ti2 = _accept_at_60000(api, customer, model)
    validate_success(api.create_payout(ti2["id"], {"method": "ACH"}, FINANCE), expected_status=201)

    cust = validate_success(api.get_customer(customer["id"], ADMIN))
    assert cust["wallet_balance_cents"] == 60000, "only the STORE_CREDIT payout should touch the wallet"
    assert cust["lifetime_payout_cents"] == 120000, "both payouts move the lifetime total"


# ─────────────────────────────────────────────────────────────────────────────
# compensating_invariant / payout_reversal_conserves_lifetime_payout
# ─────────────────────────────────────────────────────────────────────────────

def test_reversal_moves_payout_to_reversed(api):
    """PRD §3.7: "Reversal moves the payout to the terminal `REVERSED` state and
    unwinds the ledger exactly".

    Reversing an ACH payout transitions it to REVERSED.

    Design: Difficulty/compensating_invariant/payout_reversal_conserves_lifetime_payout
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = _accept_at_60000(api, customer, model)
    payout = validate_success(api.create_payout(ti["id"], {"method": "ACH"}, FINANCE), expected_status=201)
    validate_success(api.reverse_payout(ti["id"], payout["id"], FINANCE))

    payouts = get_payouts(ti["id"])
    assert payouts[0]["status"] == "REVERSED"


def test_reversal_conserves_lifetime_payout(api):
    """PRD §3.7: "the customer's `lifetime_payout_cents` is decreased by the payout
    amount".
    PRD §3.7: "The invariant is that issuing a payout and then reversing it leaves
    both `wallet_balance_cents` and `lifetime_payout_cents` exactly at their pre-issue
    values, with no net drift."

    Issue+reverse an ACH payout leaves lifetime_payout_cents back at 0.

    Design: Difficulty/compensating_invariant/payout_reversal_conserves_lifetime_payout
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = _accept_at_60000(api, customer, model)
    payout = validate_success(api.create_payout(ti["id"], {"method": "ACH"}, FINANCE), expected_status=201)
    validate_success(api.reverse_payout(ti["id"], payout["id"], FINANCE))

    cust = validate_success(api.get_customer(customer["id"], ADMIN))
    assert cust["lifetime_payout_cents"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# compensating_invariant / storecredit_reversal_conserves_wallet_balance
# ─────────────────────────────────────────────────────────────────────────────

def test_storecredit_reversal_conserves_wallet_balance(api):
    """PRD §3.7: "only if the payout's `method` was `STORE_CREDIT` — the
    `wallet_balance_cents` is decreased by the same amount."
    PRD §3.7: "The invariant is that issuing a payout and then reversing it leaves
    both `wallet_balance_cents` and `lifetime_payout_cents` exactly at their pre-issue
    values, with no net drift."

    A STORE_CREDIT payout credits the wallet to 60000; reversing it returns the wallet
    to 0.

    Design: Difficulty/compensating_invariant/storecredit_reversal_conserves_wallet_balance
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = _accept_at_60000(api, customer, model)
    payout = validate_success(api.create_payout(ti["id"], {"method": "STORE_CREDIT"}, FINANCE), expected_status=201)

    after_issue = validate_success(api.get_customer(customer["id"], ADMIN))
    assert after_issue["wallet_balance_cents"] == 60000

    validate_success(api.reverse_payout(ti["id"], payout["id"], FINANCE))
    after_reverse = validate_success(api.get_customer(customer["id"], ADMIN))
    assert after_reverse["wallet_balance_cents"] == 0


def test_storecredit_reversal_marks_payout_reversed(api):
    """PRD §3.7: "Reversal moves the payout to the terminal `REVERSED` state".

    Reversing a STORE_CREDIT payout transitions it to REVERSED.

    Design: Difficulty/compensating_invariant/storecredit_reversal_conserves_wallet_balance
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = _accept_at_60000(api, customer, model)
    payout = validate_success(api.create_payout(ti["id"], {"method": "STORE_CREDIT"}, FINANCE), expected_status=201)
    validate_success(api.reverse_payout(ti["id"], payout["id"], FINANCE))

    payouts = get_payouts(ti["id"])
    assert payouts[0]["status"] == "REVERSED"
