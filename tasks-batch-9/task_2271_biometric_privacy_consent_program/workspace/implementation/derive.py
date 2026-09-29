"""Derived counters and the program posture gate (PRD 2.6, 2.9).

Derived fields are recomputed, never patched.  Recomputation never refreshes
`updated_at` and never increments `version` on its own; callers that are
declared to be mutations do that explicitly.
"""

import constants as K
from calc import inventory_completeness_pct
from store import db


# --- collection point counters ---------------------------------------------

def asset_consents(asset_id):
    return [c for c in db.consents.values() if c["asset_id"] == asset_id]


def refresh_asset_counters(asset):
    rows = asset_consents(asset["id"])
    asset["enrolled_subject_count"] = sum(1 for c in rows if c["status"] == "GRANTED")
    asset["consent_gap_count"] = sum(
        1 for c in rows if c["status"] in ("SOLICITED", "RESOLICIT_REQUIRED", "EXPIRED")
    )
    return asset


# --- data subject derived fields -------------------------------------------

def subject_consents(subject_id):
    return [c for c in db.consents.values() if c["data_subject_id"] == subject_id]


def subject_accommodations(subject_id):
    return [a for a in db.accommodations.values() if a["data_subject_id"] == subject_id]


def refresh_subject(subject):
    consents = subject_consents(subject["id"])
    accommodations = subject_accommodations(subject["id"])
    subject["active_accommodation_count"] = sum(
        1 for a in accommodations if a["status"] in ("PROVISIONED", "ACTIVE")
    )
    has_granted = any(c["status"] == "GRANTED" for c in consents)
    has_refusal = any(c["status"] in ("DECLINED", "REVOKED") for c in consents)
    has_live_accommodation = subject["active_accommodation_count"] > 0
    if has_refusal and not has_granted:
        subject["enrollment_status"] = "OPTED_OUT"
    elif has_granted:
        subject["enrollment_status"] = "ENROLLED"
    elif has_live_accommodation:
        subject["enrollment_status"] = "ALTERNATIVE"
    else:
        subject["enrollment_status"] = "NOT_ENROLLED"
    return subject


# --- program counters and posture ------------------------------------------

def program_assets(program_id):
    return [a for a in db.assets.values() if a["program_id"] == program_id]


def program_vendor_ids(program_id):
    return set(v["id"] for v in db.vendors.values() if v["program_id"] == program_id)


def open_deletion_obligations(program_id):
    vendor_ids = program_vendor_ids(program_id)
    return [
        c
        for c in db.contracts.values()
        if c["vendor_id"] in vendor_ids
        and c["status"] == "TERMINATED"
        and c.get("deletion_certificate_ref") is None
    ]


def refresh_program(program):
    program_id = program["id"]
    assets = program_assets(program_id)
    program["gated_asset_count"] = sum(1 for a in assets if a["status"] == "GATED")
    program["consent_gap_count"] = sum(
        int(a.get("consent_gap_count") or 0) for a in assets if a["status"] in ("ACTIVE", "GATED")
    )
    open_obligations = open_deletion_obligations(program_id)
    program["open_deletion_obligation_count"] = len(open_obligations)
    program["pra_exposure_cents"] = sum(
        int(a["exposure_cents"])
        for a in db.assessments.values()
        if a["program_id"] == program_id and a["status"] == "FINAL"
    )
    program["inventory_completeness_pct"] = inventory_completeness_pct(program_id)

    overdue = [
        c
        for c in open_obligations
        if c.get("deletion_deadline_at") is not None and db.clock > c["deletion_deadline_at"]
    ]

    # Pinned precedence: FROZEN first, RESTRICTED second, OPEN last.
    if len(overdue) > 0:
        program["posture"] = "FROZEN"
    elif int(program["exposure_ceiling_cents"]) > 0 and (
        int(program["pra_exposure_cents"]) * 100
        >= K.POSTURE_FREEZE_EXPOSURE_PCT * int(program["exposure_ceiling_cents"])
    ):
        program["posture"] = "FROZEN"
    elif (
        int(program["gated_asset_count"]) > 0
        or int(program["consent_gap_count"]) > 0
        or len(open_obligations) > 0
    ):
        program["posture"] = "RESTRICTED"
    else:
        program["posture"] = "OPEN"
    return program


def refresh_all():
    """Recompute every derived field in the store.  Idempotent, versionless."""
    for asset in db.assets.values():
        refresh_asset_counters(asset)
    for subject in db.subjects.values():
        refresh_subject(subject)
    for program in db.programs.values():
        refresh_program(program)


def program_of_asset(asset):
    return db.programs.get(asset["program_id"])


def program_of_vendor(vendor):
    return db.programs.get(vendor["program_id"])


def program_of_contract(contract):
    vendor = db.vendors.get(contract["vendor_id"])
    if vendor is None:
        return None
    return db.programs.get(vendor["program_id"])


def program_of_subject(subject):
    return db.programs.get(subject["program_id"])
