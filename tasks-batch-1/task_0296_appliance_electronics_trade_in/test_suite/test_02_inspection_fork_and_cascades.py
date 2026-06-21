"""The inspection fork (MATCH / REQUOTE / RECYCLE), the Quote terminal branches,
and the multi-hop cascades they fan across quotes, dispositions, and the wallet.
"""
import pytest
from test_helpers import (
    validate_success,
    find_quote,
    setup_catalog_model_customer,
    create_received_trade_in,
    create_quoted_trade_in,
    inspect,
    set_clock,
    get_quotes,
    get_disposition_records,
    api_client,
    make_customer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
FINANCE = TEST_USERS["finance_operator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / tradein_inspect_fork_three_branches
# ─────────────────────────────────────────────────────────────────────────────

def test_inspect_fork_selects_match_accept(api):
    """PRD §3.6: "On `MATCH`, the trade-in auto-accepts at the originally locked
    amount: it advances from `INSPECTED` to `ACCEPTED`, the initial `LOCKED` quote
    moves to `HONORED`, and the trade-in's `final_value_cents` is set to that honored
    quote's `amount_cents`."

    Verified findings matching the declared ones (GOOD+CRACKED_SCREEN) keep the value
    within tolerance, so the inspect fork lands on ACCEPTED.

    Design: Difficulty/non_linear_state_machine/tradein_inspect_fork_three_branches
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspect(ti["id"], "GOOD", verified_defects=["CRACKED_SCREEN"])

    refreshed = validate_success(api.get_trade_in(ti["id"], ADMIN))
    assert refreshed["status"] == "ACCEPTED"


def test_inspect_fork_selects_requote_and_recycle(api):
    """PRD §3.6: "On `REQUOTE`, the trade-in advances from `INSPECTED` to `REQUOTED`".
    PRD §3.6: "On `RECYCLE`, the trade-in advances from `INSPECTED` to the terminal
    `RECYCLED` state".

    The same /inspect trigger fans into REQUOTED (downgrade above floor) or RECYCLED
    (at/below floor) depending purely on the verified findings.

    Design: Difficulty/non_linear_state_machine/tradein_inspect_fork_three_branches
    """
    _cat, model, customer = setup_catalog_model_customer()

    ti_req = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspect(ti_req["id"], "FAIR", verified_defects=["WATER_DAMAGE"])
    assert validate_success(api.get_trade_in(ti_req["id"], ADMIN))["status"] == "REQUOTED"

    ti_rec = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspect(ti_rec["id"], "POOR", verified_powers_on=False, verified_defects=["WATER_DAMAGE"])
    assert validate_success(api.get_trade_in(ti_rec["id"], ADMIN))["status"] == "RECYCLED"


# ─────────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / quote_lock_branches_to_three_terminals
# ─────────────────────────────────────────────────────────────────────────────

def test_locked_quote_honored_on_match(api):
    """PRD §3.6: "the initial `LOCKED` quote moves to `HONORED`".

    A LOCKED INITIAL quote resolves to the HONORED terminal when the trade-in
    auto-accepts on a MATCH inspection.

    Design: Difficulty/non_linear_state_machine/quote_lock_branches_to_three_terminals
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspect(ti["id"], "GOOD", verified_defects=["CRACKED_SCREEN"])

    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["status"] == "HONORED"


def test_locked_quote_superseded_and_expired_terminals(api):
    """PRD §3.6: "the prior `INITIAL` quote moves to `SUPERSEDED`".
    PRD §3.5: "it moves the trade-in to `EXPIRED` and moves the locked `Quote` to
    `EXPIRED` as well."

    A LOCKED quote reaches SUPERSEDED when a REQUOTE replaces it, and reaches EXPIRED
    when the expiry sweep fires past lock_expires_at.

    Design: Difficulty/non_linear_state_machine/quote_lock_branches_to_three_terminals
    """
    _cat, model, customer = setup_catalog_model_customer()

    # SUPERSEDED via REQUOTE
    ti_sup = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspect(ti_sup["id"], "FAIR", verified_defects=["WATER_DAMAGE"])
    initial_sup = find_quote(get_quotes(ti_sup["id"]), kind="INITIAL")
    assert initial_sup["status"] == "SUPERSEDED"

    # EXPIRED via sweep
    set_clock("2026-06-01T00:00:00Z")
    ti_exp = create_quoted_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    set_clock("2026-07-01T00:00:00Z")
    validate_success(api.sweep_expiry(ti_exp["id"], ADMIN))
    initial_exp = find_quote(get_quotes(ti_exp["id"]), kind="INITIAL")
    assert initial_exp["status"] == "EXPIRED"


# ─────────────────────────────────────────────────────────────────────────────
# transitive_cascade / inspect_recycle_cascade_depth3
# ─────────────────────────────────────────────────────────────────────────────

def test_recycle_cascade_supersedes_quote(api):
    """PRD §3.6: "On `RECYCLE`, the trade-in advances from `INSPECTED` to the terminal
    `RECYCLED` state: the prior locked quote moves to `SUPERSEDED`, and a
    `DispositionRecord` with `disposition` of `RECYCLE` is created."

    A RECYCLE inspection drives the trade-in to RECYCLED and supersedes the locked
    INITIAL quote.

    Design: Difficulty/transitive_cascade/inspect_recycle_cascade_depth3
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspect(ti["id"], "POOR", verified_powers_on=False, verified_defects=["WATER_DAMAGE"])

    assert validate_success(api.get_trade_in(ti["id"], ADMIN))["status"] == "RECYCLED"
    initial = find_quote(get_quotes(ti["id"]), kind="INITIAL")
    assert initial["status"] == "SUPERSEDED"


def test_recycle_cascade_creates_recycle_disposition(api):
    """PRD §3.6: "a `DispositionRecord` with `disposition` of `RECYCLE` is created."

    The RECYCLE branch mints exactly one RECYCLE disposition record.

    Design: Difficulty/transitive_cascade/inspect_recycle_cascade_depth3
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(
        customer, model, declared_grade="GOOD", declared_defects=["CRACKED_SCREEN"], declared_powers_on=True
    )
    inspect(ti["id"], "POOR", verified_powers_on=False, verified_defects=["WATER_DAMAGE"])

    records = get_disposition_records(ti["id"])
    recycle = [r for r in records if r["disposition"] == "RECYCLE"]
    assert len(recycle) == 1, f"expected exactly one RECYCLE disposition, got {len(recycle)}"


# ─────────────────────────────────────────────────────────────────────────────
# transitive_cascade / payout_storecredit_cascade_depth2
# ─────────────────────────────────────────────────────────────────────────────

def test_storecredit_payout_credits_wallet(api):
    """PRD §3.7: "when and only when the `method` is `STORE_CREDIT`, the customer's
    `wallet_balance_cents` is increased by the same amount".

    A STORE_CREDIT payout on a 60000-accepted trade-in raises the customer's
    wallet_balance_cents to 60000.

    Design: Difficulty/transitive_cascade/payout_storecredit_cascade_depth2
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=[])
    validate_success(api.create_payout(ti["id"], {"method": "STORE_CREDIT"}, FINANCE), expected_status=201)

    cust = validate_success(api.get_customer(customer["id"], ADMIN))
    assert cust["wallet_balance_cents"] == 60000


def test_payout_creates_refurbish_disposition(api):
    """PRD §3.7: "Issuing also creates a `DispositionRecord` with `disposition` of
    `REFURBISH_INVENTORY`, routing the now-bought unit into refurbishment stock."

    Issuing the payout mints exactly one REFURBISH_INVENTORY disposition record.

    Design: Difficulty/transitive_cascade/payout_storecredit_cascade_depth2
    """
    _cat, model, customer = setup_catalog_model_customer()
    ti = create_received_trade_in(customer, model, declared_grade="FLAWLESS")
    inspect(ti["id"], "FLAWLESS", verified_defects=[])
    validate_success(api.create_payout(ti["id"], {"method": "STORE_CREDIT"}, FINANCE), expected_status=201)

    records = get_disposition_records(ti["id"])
    refurb = [r for r in records if r["disposition"] == "REFURBISH_INVENTORY"]
    assert len(refurb) == 1, f"expected exactly one REFURBISH_INVENTORY disposition, got {len(refurb)}"
