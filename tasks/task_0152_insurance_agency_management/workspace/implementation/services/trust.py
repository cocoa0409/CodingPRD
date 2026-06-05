"""Trust ledger posting helpers (PRD §2.6, §3.9).

A TrustLedgerEntry is immutable (id + created_at only). The sign of amount_cents
is fixed by entry_type:
  PREMIUM_RECEIPT, OPENING_BALANCE  -> positive
  CARRIER_REMITTANCE, COMMISSION_DISBURSEMENT, RETURN_PREMIUM_REFUND -> negative
"""
from db import store, new_common
from services import derived

POSITIVE_TYPES = {"PREMIUM_RECEIPT", "OPENING_BALANCE"}
NEGATIVE_TYPES = {"CARRIER_REMITTANCE", "COMMISSION_DISBURSEMENT", "RETURN_PREMIUM_REFUND"}
ALL_ENTRY_TYPES = POSITIVE_TYPES | NEGATIVE_TYPES


def post_entry(trust_account_id, entry_type, amount_cents, policy_id=None):
    """Create and store an immutable ledger entry. No version/updated_at."""
    rec = new_common(extra_quartet=False)
    rec.update(
        trust_account_id=trust_account_id,
        policy_id=policy_id,
        entry_type=entry_type,
        amount_cents=amount_cents,
    )
    store.trust_ledger_entries[rec["id"]] = rec
    return rec


def trust_account_for_state(state_code):
    """Return the (unique) trust account for a state, or None."""
    for ta in store.trust_accounts.values():
        if ta["state_code"] == state_code:
            return ta
    return None


def balance(trust_account_id):
    return derived.trust_balance(trust_account_id)
