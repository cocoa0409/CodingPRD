"""active_certificate_selection (scaffold 1.3 / PRD 3.1).

Candidates: vessel's certificates that are ACTIVE, effective on or before the
reference date D, and expiring strictly after D. Ranked by expiry_date DESC,
ties broken by created_at DESC (never by id). Empty set -> no qualifying
certificate."""

import db
from money import INSURANCE_MIN_LIABILITY_CENTS


def select_certificate(vessel_id, ref_date):
    cands = [
        c for c in db.certificates.values()
        if c["vessel_id"] == vessel_id
        and c["status"] == "ACTIVE"
        and c["_effective"] <= ref_date
        and c["_expiry"] > ref_date
    ]
    if not cands:
        return None
    cands.sort(key=lambda c: (c["_expiry"], c["created_at"], c["_seq"]), reverse=True)
    return cands[0]


def qualifying_certificate_for_submit(vessel_id, today):
    """Submit gate: a qualifying certificate at the current date (no coverage
    minimum at submit)."""
    return select_certificate(vessel_id, today)


def qualifying_certificate_for_slot(vessel_id, slot_start_date):
    """Slot booking gate: selection at the slot's scheduled start date plus the
    liability-coverage minimum."""
    cert = select_certificate(vessel_id, slot_start_date)
    if cert is None:
        return None
    if cert["liability_coverage_cents"] < INSURANCE_MIN_LIABILITY_CENTS:
        return None
    return cert
