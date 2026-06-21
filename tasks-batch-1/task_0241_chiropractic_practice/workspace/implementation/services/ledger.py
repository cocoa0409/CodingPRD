"""Ledger entry creation and patient balance maintenance (PRD §2.9)."""
import db
from models import new_record, touch


def add_entry(patient, entry_type, amount_cents, appointment_id=None, memo=None):
    """Append a LedgerEntry and adjust patient.ledger_balance_cents.

    amount_cents is signed: positive raises the balance (CHARGE/NO_SHOW_FEE),
    negative lowers it (payments/write-offs). LedgerEntry carries only id +
    created_at (no version/updated_at) per PRD §2.4.
    """
    rec = new_record(
        {
            "patient_id": patient["id"],
            "appointment_id": appointment_id,
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "memo": memo,
        },
        common=False,
    )
    db.ledger_entries[rec["id"]] = rec
    patient["ledger_balance_cents"] += amount_cents
    touch(patient)
    return rec
