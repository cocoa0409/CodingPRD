"""Perpetual-care fund ledger: conservation invariant and zero-floor boundary."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_issued_deed, post_care_entry, get_cemetery_balance,
    create_cemetery,
)


# ── Difficulty: compensating_invariant / perpetual_care_ledger_balance_conserved ──

def test_care_fund_balance_conserved_across_mixed_entries(api):
    """PRD §2.7: "it is the sum of amount_cents across all CONTRIBUTION and INTEREST
    entries for that cemetery, minus the sum of amount_cents across all DISBURSEMENT
    entries for that cemetery."

    Design: Difficulty/compensating_invariant/perpetual_care_ledger_balance_conserved
    """
    r = setup_issued_deed(purchase_price_cents=1000000, sale_type="NEW_SALE")
    cem_id = r["cemetery"]["id"]
    # Contribution 150000 already posted on issuance.
    validate_success(post_care_entry(cem_id, "INTEREST", 10000, note="q2 interest"), 201)
    validate_success(post_care_entry(cem_id, "DISBURSEMENT", 40000,
                                     source_deed_id=r["deed"]["id"], note="landscaping"), 201)
    assert get_cemetery_balance(cem_id) == 120000


def test_care_fund_balance_after_interest_before_disbursement(api):
    """PRD §2.7: "it is the sum of amount_cents across all CONTRIBUTION and INTEREST
    entries for that cemetery, minus the sum of amount_cents across all DISBURSEMENT
    entries for that cemetery."

    Design: Difficulty/compensating_invariant/perpetual_care_ledger_balance_conserved
    """
    r = setup_issued_deed(purchase_price_cents=1000000, sale_type="NEW_SALE")
    cem_id = r["cemetery"]["id"]
    validate_success(post_care_entry(cem_id, "INTEREST", 10000, note="q2 interest"), 201)
    # 150000 contribution + 10000 interest, no disbursement yet.
    assert get_cemetery_balance(cem_id) == 160000


# ── Difficulty: boundary_precision_check / care_fund_zero_floor_blocks_overdraw ──

def test_disbursement_to_exact_zero_succeeds(api):
    """PRD §2.7: "Any DISBURSEMENT that would drive the running balance below zero is
    rejected with ERR_CARE_FUND_INSUFFICIENT; the fund may reach exactly zero but
    never go negative."

    Design: Difficulty/boundary_precision_check/care_fund_zero_floor_blocks_overdraw
    """
    r = setup_issued_deed(purchase_price_cents=1000000, sale_type="NEW_SALE")
    cem_id = r["cemetery"]["id"]
    validate_success(post_care_entry(cem_id, "DISBURSEMENT", 150000, note="grounds upkeep"), 201)
    assert get_cemetery_balance(cem_id) == 0


def test_disbursement_below_zero_rejected(api):
    """PRD §2.7: "Any DISBURSEMENT that would drive the running balance below zero is
    rejected with ERR_CARE_FUND_INSUFFICIENT; the fund may reach exactly zero but
    never go negative."

    Design: Difficulty/boundary_precision_check/care_fund_zero_floor_blocks_overdraw
    """
    r = setup_issued_deed(purchase_price_cents=1000000, sale_type="NEW_SALE")
    cem_id = r["cemetery"]["id"]
    validate_success(post_care_entry(cem_id, "DISBURSEMENT", 150000, note="grounds upkeep"), 201)
    res = post_care_entry(cem_id, "DISBURSEMENT", 1, note="overdraw")
    validate_error(res, "ERR_CARE_FUND_INSUFFICIENT")
    # Balance unchanged after the rejected overdraw.
    assert get_cemetery_balance(cem_id) == 0


# ── Corner: endpoints / computed_read_cemetery_fund_balance ──

def test_cemetery_read_reflects_contribution(api):
    """PRD §2.7: "A cemetery's perpetual_care_fund_balance_cents is a computed field"
    PRD §3.1: "a cemetery read includes its live fund balance."

    Design: Corner/endpoints/computed_read_cemetery_fund_balance
    """
    r = setup_issued_deed(purchase_price_cents=1000000, sale_type="NEW_SALE")
    assert get_cemetery_balance(r["cemetery"]["id"]) == 150000
