"""Shared business-logic helpers: derived-field reconciliation and cascades
(PRD 2.9, 3.3, 3.8, 3.10, 3.11)."""
import db


def recompute_total_charges(encounter):
    """encounter.total_charges_cents = sum of POSTED charge amounts (PRD 3.3)."""
    total = 0
    for c in db.charges.values():
        if c["encounter_id"] == encounter["id"] and c["status"] == "POSTED":
            total += c["amount_cents"]
    encounter["total_charges_cents"] = total
    return total


def statement_for_encounter(encounter_id):
    """Return the most recent (by seq) PatientStatement for an encounter, or None.

    Only one live statement is created per encounter in the modeled flows, but
    a correction/appeal reversal can close one before another is issued; the
    latest by insertion order is the active billing view."""
    matches = [s for s in db.patient_statements.values() if s["encounter_id"] == encounter_id]
    if not matches:
        return None
    return max(matches, key=lambda s: s["_seq"])


def recompute_account_balance(encounter):
    """account_balance = max(0, patient_responsibility - payments - written_off)
    (PRD 3.10). Payments and written_off come from the encounter's statement."""
    stmt = statement_for_encounter(encounter["id"])
    paid = 0
    written = 0
    if stmt is not None:
        for p in db.payments.values():
            if p["statement_id"] == stmt["id"]:
                paid += p["amount_cents"]
        written = stmt.get("written_off_cents", 0)
    balance = max(0, encounter["patient_responsibility_cents"] - paid - written)
    encounter["account_balance_cents"] = balance
    return balance
