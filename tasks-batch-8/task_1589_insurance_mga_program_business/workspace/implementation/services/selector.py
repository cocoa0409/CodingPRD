"""TPA assignment selector (scaffold calculation tpa_assignment).

candidates: ACTIVE appointments of the program whose claim_type matches and
whose CLOSED window contains the occurrence_date.
rank: authority_limit_cents DESC, created_at ASC, tpa license_number ASC
(a business field, never an opaque id).
"""
from db import STORE


def select_appointment(program_id, claim_type, occurrence_date):
    cands = [
        a for a in STORE.tpa_appointments.values()
        if a["program_id"] == program_id
        and a["claim_type"] == claim_type
        and a["status"] == "ACTIVE"
        and a["effective_from"] <= occurrence_date <= a["effective_to"]
    ]
    if not cands:
        return None

    def key(a):
        tpa = STORE.tpas.get(a["tpa_id"])
        license_number = tpa["license_number"] if tpa is not None else ""
        return (-a["authority_limit_cents"], a["created_at"], license_number, a["_seq"])

    cands.sort(key=key)
    return cands[0]
