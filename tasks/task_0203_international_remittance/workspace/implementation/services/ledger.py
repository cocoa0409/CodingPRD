"""LedgerEntry creation + refund execution (PRD §2.9, §3.4, §3.7, §3.8).

Ledger entries are immutable audit records (id + created_at only). Debits are
negative, credits positive, in send-currency minor units.
"""
import db
from services.common import stamp_create, touch, now_iso
from services.clock import parse_iso
from services import calculations


def write_entry(transfer_id, entry_type, amount_minor, memo=None):
    entry = {
        "transfer_id": transfer_id,
        "entry_type": entry_type,
        "amount_minor": amount_minor,
        "memo": memo,
    }
    stamp_create(entry, versioned=False)
    db.ledger_entries[entry["id"]] = entry
    return entry


def sender_debit_entry(transfer_id):
    """Return the SENDER_DEBIT ledger entry for a transfer, or None."""
    for e in db.ledger_entries.values():
        if e["transfer_id"] == transfer_id and e["entry_type"] == "SENDER_DEBIT":
            return e
    return None


def funded_seconds_ago(transfer):
    """Seconds between the SENDER_DEBIT created_at and the current clock."""
    debit = sender_debit_entry(transfer["id"])
    if debit is None:
        return None
    funded_at = parse_iso(debit["created_at"])
    delta = (db.get_clock() - funded_at).total_seconds()
    return delta


def compute_refundable(transfer):
    """Computed refundable_minor: what a SENDER_CANCEL at the current instant
    would return (PRD §3.7). Reflects the grace-window-dependent fee treatment.
    """
    if transfer["funding_status"] != "FUNDED":
        return 0
    secs = funded_seconds_ago(transfer)
    if secs is None:
        secs = 0
    _, _, total = calculations.refund_amount(transfer, "SENDER_CANCEL", secs)
    return total


def execute_refund(transfer, corridor, reason):
    """Create a Refund, write REFUND_CREDIT + FEE_REVERSAL ledger entries when
    money actually moves, restore the corridor reservation, and drive the
    transfer to REFUNDED. Returns the created Refund record.

    Used by both POST /refunds and the compensating COMPLIANCE_REJECT chain.
    The caller is responsible for state-precondition validation; this performs
    the side effects and the refund_amount computation.
    """
    secs = funded_seconds_ago(transfer)
    if secs is None:
        secs = 0
    principal_refunded, fee_refunded, total = calculations.refund_amount(
        transfer, reason, secs)

    was_funded = transfer["funding_status"] == "FUNDED"
    if was_funded:
        # Restore corridor reservation and write the compensating credits.
        corridor["reserved_minor"] -= transfer["send_principal_minor"]
        write_entry(transfer["id"], "REFUND_CREDIT", principal_refunded,
                    "Refund of send principal")
        # PRD §3.8 conservation invariant: the four entries must net to exactly
        # fee_minor - fee_refunded_minor (the fee the provider keeps). With
        # SENDER_DEBIT=-(P+F), FEE_REVENUE=+F, REFUND_CREDIT=+P fixed, the
        # FEE_REVERSAL amount that yields that net is fee_minor - fee_refunded
        # (0 on a full reversal, the retained fee otherwise).
        fee_reversal_amount = transfer["fee_minor"] - fee_refunded
        write_entry(transfer["id"], "FEE_REVERSAL", fee_reversal_amount,
                    "Reversal of disclosed fee (net-to-retained-fee)")

    transfer["delivery_status"] = "REFUNDED"
    touch(transfer)

    refund = {
        "transfer_id": transfer["id"],
        "reason": reason,
        "principal_refunded_minor": principal_refunded,
        "fee_refunded_minor": fee_refunded,
        "total_refunded_minor": total,
        "status": "ISSUED",
    }
    stamp_create(refund, versioned=True)
    db.refunds[refund["id"]] = refund
    return refund
