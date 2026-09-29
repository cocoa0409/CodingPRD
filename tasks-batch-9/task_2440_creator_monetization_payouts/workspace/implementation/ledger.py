"""Append-only creator ledger (PRD 2.6).  An entry of zero is never written."""
from calc import ledger_balance_cents
from store import db

MEMO = {
    "ACCRUAL": "REVENUE_EVENT_ACCRUED",
    "ACCRUAL_REVERSAL": "REVENUE_EVENT_RESCORE_REVERSAL",
    "ACCRUAL_RESTORE": "REVENUE_EVENT_RESCORE_RESTORE",
    "WITHHOLDING": "STATEMENT_WITHHOLDING_PROVISIONAL",
    "WITHHOLDING_TRUE_UP": "STATEMENT_WITHHOLDING_TRUE_UP",
    "FUND_CREDIT": "FUND_ALLOCATION_DISBURSED",
    "PAYOUT_DEBIT": "PAYOUT_DEBIT_RESERVED",
    "PAYOUT_FEE": "PAYOUT_FEE_CHARGED",
    "PAYOUT_REVERSAL": "PAYOUT_REVERSAL_RESTORED",
    "CLAWBACK": "CLAWBACK_RECOVERED",
    "DISPUTE_ADJUSTMENT": "DISPUTE_UPHELD_ADJUSTMENT",
}


def append(creator_id, entry_type, amount_cents, source_entity, source_id, memo=None):
    if amount_cents == 0:
        return None
    balance_after = ledger_balance_cents(creator_id) + amount_cents
    return db.insert("ledger", {
        "creator_id": creator_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "balance_after_cents": balance_after,
        "source_entity": source_entity,
        "source_id": source_id,
        "occurred_at": db.now,
        "memo": memo or MEMO[entry_type],
    }, common_fields=False)
