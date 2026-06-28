"""Append-only LedgerEntry log (audit mirror, PRD §2.6).

Sign convention (fixed):
  CLAIM_PENDING / CLAIM_MATURED       -> +amount (informational; no net move)
  REFERRAL_BONUS / STREAK_BONUS       -> +amount
  CLAIM_CLAWBACK / CLAIM_EXPIRED /
    CASHOUT_DEBIT                     -> -amount
  CASHOUT_REVERSAL                    -> +amount
"""
from db import base_common_fields


def emit_ledger(store, member_id, entry_type, amount_cents,
                reward_claim_id=None, cashout_id=None, referral_id=None):
    entry = base_common_fields(store, full=False)
    entry.update({
        "member_id": member_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reward_claim_id": reward_claim_id,
        "cashout_id": cashout_id,
        "referral_id": referral_id,
    })
    store.ledger_entries[entry["id"]] = entry
    return entry
