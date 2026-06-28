"""Shared domain helpers (PRD §3.2 checklist, §3.5 lien-in-play, §3.7 balance)."""

from db import db

# Polymorphic required checklist by transaction_type (PRD §3.2 / scaffold §1.2 note)
REQUIRED_CHECKLIST = {
    "TITLE": {"TITLE_CERT", "BILL_OF_SALE", "ODOMETER", "ID_PROOF"},
    "REGISTRATION": {"ID_PROOF", "INSURANCE"},
    "TRANSFER": {"TITLE_CERT", "BILL_OF_SALE", "ID_PROOF"},
    "LIEN": {"LIEN_INSTRUMENT", "ID_PROOF"},
}


def documents_for_transaction(transaction_id):
    return [d for d in db.document_items.values()
            if d["transaction_id"] == transaction_id]


def quotes_for_transaction(transaction_id):
    return [q for q in db.fee_quotes.values()
            if q["transaction_id"] == transaction_id]


def submissions_for_transaction(transaction_id):
    return [s for s in db.submissions.values()
            if s["transaction_id"] == transaction_id]


def lien_packets_for_transaction(transaction_id):
    return [p for p in db.lien_packets.values()
            if p["transaction_id"] == transaction_id]


def active_schedule_for_state(state_code):
    """Return the single ACTIVE FeeSchedule for a state_code, or None."""
    for s in db.fee_schedules.values():
        if s["state_code"] == state_code and s["status"] == "ACTIVE":
            return s
    return None


def checklist_outcome(transaction):
    """Compute the document_status outcome for a checklist evaluation (PRD §3.2).

    VERIFIED when every required checklist_code has a VERIFIED DocumentItem and no
    document on the transaction is REJECTED; otherwise INCOMPLETE.
    """
    docs = documents_for_transaction(transaction["id"])
    required = REQUIRED_CHECKLIST.get(transaction["transaction_type"], set())

    # Any REJECTED document on the transaction -> INCOMPLETE.
    if any(d["doc_status"] == "REJECTED" for d in docs):
        return "INCOMPLETE"

    verified_codes = {d["checklist_code"] for d in docs if d["doc_status"] == "VERIFIED"}
    if required.issubset(verified_codes):
        return "VERIFIED"
    return "INCOMPLETE"


def lien_in_play(transaction):
    """True if a LienPacket exists for the transaction (PRD §3.5).

    The lien recording fee is pulled into the state-fee line whenever a lien
    packet exists for the transaction (any non-... packet counts; presence is
    what matters per §3.8: "The presence of a packet on a transaction also pulls
    the lien recording fee into the state-fee line"). We count any packet that is
    not VOIDED as present.
    """
    for p in db.lien_packets.values():
        if p["transaction_id"] == transaction["id"] and p["packet_status"] != "VOIDED":
            return True
    return False


def settled_quote_for_transaction(transaction_id):
    """Return the SETTLED FeeQuote for a transaction, or None."""
    for q in db.fee_quotes.values():
        if q["transaction_id"] == transaction_id and q["status"] == "SETTLED":
            return q
    return None


def active_quote_for_transaction(transaction_id):
    for q in db.fee_quotes.values():
        if q["transaction_id"] == transaction_id and q["status"] == "ACTIVE":
            return q
    return None


def recompute_account_balance(account):
    """Reconcile Account.outstanding_balance_cents (PRD §3.7 / scaffold account_balance).

    outstanding = max(0, settled_totals - charges + refunds), where:
      settled_totals = sum of SETTLED FeeQuote.total_cents over the account's
                       COMPLETED transactions,
      charges        = sum of CHARGE Payment.amount_cents on the account,
      refunds        = sum of REFUND Payment.amount_cents on the account.
    Order-independent pure sums; clamped at floor 0.
    """
    account_id = account["id"]

    completed_txn_ids = {
        t["id"] for t in db.transactions.values()
        if t["account_id"] == account_id and t["lifecycle_status"] == "COMPLETED"
    }
    settled = sum(
        q["total_cents"] for q in db.fee_quotes.values()
        if q["status"] == "SETTLED" and q["transaction_id"] in completed_txn_ids
    )
    charges = sum(
        p["amount_cents"] for p in db.payments.values()
        if p["account_id"] == account_id and p["kind"] == "CHARGE"
    )
    refunds = sum(
        p["amount_cents"] for p in db.payments.values()
        if p["account_id"] == account_id and p["kind"] == "REFUND"
    )
    account["outstanding_balance_cents"] = max(0, settled - charges + refunds)
