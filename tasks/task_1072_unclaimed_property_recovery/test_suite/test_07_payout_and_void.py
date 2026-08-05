"""Payment and void: the pay cascade that settles a property and debits custody,
the compensating clawback that restores custody exactly, the per-claim zero-sum
ledger invariant, and the pay-before-approve state guard.

Translates queue A (transitive_cascade/claim_pay_property_custody,
compensating_invariant/custody_conservation_pay_void, compensating_invariant/
claim_ledger_zero_sum_on_void) and queue B (pay_before_approve).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures,
)
from test_helpers.assertions import ledger_signed_sum
from test_helpers.test_users import make_examiner_headers, make_approver_headers


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/claim_pay_property_custody
# ---------------------------------------------------------------------------
def test_pay_settles_property_to_claimed(api):
    """PRD §3.8: "Payment moves the claim from APPROVED to PAID and cascades to the underlying
    property, advancing it from ESCHEATED to CLAIMED."

    Design: Difficulty/transitive_cascade/claim_pay_property_custody
    """
    ctx = fixtures.setup_approved_firm_claim(api, amount_cents=100000, interest_bearing=True,
                                             contract_fee_pct=0.10)
    paid = validate_success(api.pay_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    assert paid["status"] == "PAID"
    prop = validate_success(api.get_property(ctx["property"]["id"], ctx["holder_headers"]), 200)
    assert prop["status"] == "CLAIMED", f"paid claim must settle property to CLAIMED, got {prop['status']}"


def test_pay_debits_custody_by_net_plus_fee(api):
    """PRD §3.8: "The cascade writes two debit entries against the custody account whose
    state_code is the property's escheat_state: a PAYOUT_OUT LedgerEntry for the claim's
    net_payout_cents and a FEE_OUT LedgerEntry for the claim's fee_cents ... The account's
    custody_balance_cents is then recomputed and falls by the sum of the net payout and the fee."

    Custody 106000 minus net 94900 minus fee 10600 leaves 500.

    Design: Difficulty/transitive_cascade/claim_pay_property_custody
    """
    ctx = fixtures.setup_approved_firm_claim(api, amount_cents=100000, interest_bearing=True,
                                             contract_fee_pct=0.10)
    validate_success(api.pay_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    account = validate_success(api.get_state_account(ctx["state_account"]["id"], make_examiner_headers()), 200)
    assert account["custody_balance_cents"] == 500, \
        f"custody must fall to 500 after payout, got {account['custody_balance_cents']}"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/custody_conservation_pay_void
# ---------------------------------------------------------------------------
def test_void_returns_claim_and_property(api):
    """PRD §3.8: "Voiding a PAID claim moves it from PAID to VOIDED, a terminal state, and
    compensates the earlier disbursement. The void cascades the property back from CLAIMED to
    ESCHEATED and writes a single CLAWBACK_IN LedgerEntry for the full amount that had left
    custody ..."

    Design: Difficulty/compensating_invariant/custody_conservation_pay_void
    """
    ctx = fixtures.setup_paid_firm_claim(api, amount_cents=100000, interest_bearing=True,
                                         contract_fee_pct=0.10)
    voided = validate_success(api.void_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    assert voided["status"] == "VOIDED"
    prop = validate_success(api.get_property(ctx["property"]["id"], ctx["holder_headers"]), 200)
    assert prop["status"] == "ESCHEATED", f"void must return property to ESCHEATED, got {prop['status']}"


def test_void_restores_custody_balance(api):
    """PRD §3.8: "the account's custody_balance_cents is recomputed and rises by that same sum.
    In keeping with the custody-conservation invariant of Section 2.8, the clawback exactly
    restores the balance that the payment had removed ..."

    Pay drove custody 106000 -> 500; the compensating void restores it to exactly 106000.

    Design: Difficulty/compensating_invariant/custody_conservation_pay_void
    """
    ctx = fixtures.setup_paid_firm_claim(api, amount_cents=100000, interest_bearing=True,
                                         contract_fee_pct=0.10)
    validate_success(api.void_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    account = validate_success(api.get_state_account(ctx["state_account"]["id"], make_examiner_headers()), 200)
    assert account["custody_balance_cents"] == 106000, \
        f"clawback must restore custody to 106000, got {account['custody_balance_cents']}"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/claim_ledger_zero_sum_on_void
# ---------------------------------------------------------------------------
def test_claim_ledger_signed_sum_is_zero_after_void(api):
    """PRD §2.6: "the sign of the movement is implied entirely by its entry_type: REMIT_IN and
    CLAWBACK_IN add to custody, while PAYOUT_OUT and FEE_OUT remove from it."
    PRD §3.8: "writes a single CLAWBACK_IN LedgerEntry for the full amount that had left custody
    — the sum of the claim's net_payout_cents and fee_cents".

    PAYOUT_OUT 94900 and FEE_OUT 10600 (negative) plus CLAWBACK_IN 105500 (positive) net to 0.

    Design: Difficulty/compensating_invariant/claim_ledger_zero_sum_on_void
    """
    ctx = fixtures.setup_paid_firm_claim(api, amount_cents=100000, interest_bearing=True,
                                         contract_fee_pct=0.10)
    validate_success(api.void_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    entries = validate_success(api.list_ledger_entries(
        make_approver_headers("appr-1"), params={"ref_claim_id": ctx["claim"]["id"]}), 200)
    assert ledger_signed_sum(entries) == 0, \
        f"per-claim signed ledger sum must be 0, got {ledger_signed_sum(entries)}"


def test_claim_ledger_has_three_offsetting_entries(api):
    """PRD §3.8: the pay cascade "writes two debit entries ... a PAYOUT_OUT LedgerEntry for the
    claim's net_payout_cents and a FEE_OUT LedgerEntry for the claim's fee_cents", and the void
    "writes a single CLAWBACK_IN LedgerEntry for the full amount that had left custody — the sum
    of the claim's net_payout_cents and fee_cents".
    PRD §2.8: "No operation ever edits or deletes an existing ledger entry to achieve a reversal;
    reversals are always expressed as new, offsetting entries."

    The claim accrues exactly three entries: PAYOUT_OUT 94900, FEE_OUT 10600, CLAWBACK_IN 105500.

    Design: Difficulty/compensating_invariant/claim_ledger_zero_sum_on_void
    """
    ctx = fixtures.setup_paid_firm_claim(api, amount_cents=100000, interest_bearing=True,
                                         contract_fee_pct=0.10)
    validate_success(api.void_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    entries = validate_success(api.list_ledger_entries(
        make_approver_headers("appr-1"), params={"ref_claim_id": ctx["claim"]["id"]}), 200)
    assert len(entries) == 3, f"expected 3 ledger entries for the claim, got {len(entries)}"
    by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
    assert by_type == {"PAYOUT_OUT": 94900, "FEE_OUT": 10600, "CLAWBACK_IN": 105500}, \
        f"ledger movement set mismatch: {by_type}"


# ---------------------------------------------------------------------------
# Corner/state_machines/pay_before_approve_returns_invalid_state
# ---------------------------------------------------------------------------
def test_pay_before_approve_rejected(api):
    """PRD §2.12: "if the target resource is not in a state from which the requested transition
    is defined, the request is rejected with ERR_INVALID_STATE (HTTP 409)."
    PRD §3.8: "Paying an APPROVED claim is a second StateApprover action ..."

    Paying a FILED claim (never approved) is rejected; the claim stays FILED.

    Design: Corner/state_machines/pay_before_approve_returns_invalid_state
    """
    ctx = fixtures.setup_filed_firm_claim(api, amount_cents=50000, interest_bearing=False,
                                          contract_fee_pct=0.10)
    validate_error(api.pay_claim(ctx["claim"]["id"], make_approver_headers("appr-1")),
                   ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    assert after["status"] == "FILED"
