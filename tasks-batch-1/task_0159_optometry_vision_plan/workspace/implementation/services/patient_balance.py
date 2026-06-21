"""Derived patient outstanding-balance reconciliation (PRD §3.8).

outstanding_patient_balance_cents = sum over the patient's claims whose
claim_status is ADJUDICATED or SETTLED_PARTIAL of
(patient_responsibility_cents - settled_cents).
"""
from db import db

_CONTRIBUTING_STATUSES = {"ADJUDICATED", "SETTLED_PARTIAL"}


def recompute_for_patient(patient_id):
    total = 0
    for c in db.claims.values():
        if c.get("patient_id") != patient_id:
            continue
        if c["claim_status"] in _CONTRIBUTING_STATUSES:
            total += c["patient_responsibility_cents"] - c["settled_cents"]
    patient = db.patients.get(patient_id)
    if patient is not None:
        patient["outstanding_patient_balance_cents"] = total
    return total
