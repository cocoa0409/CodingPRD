"""Rungs 1-6 and rung 13: identity, role authorisation, existence, the global
write gate, care-team scope, and the device recall gate.

Also owns version-bump granularity: one increment per row per request (PRD 2.5).
"""

from flask import g, request

from errors import fail
from store import DB, new_id, next_seq, now_instant

ROLES = (
    "PlatformAdmin",
    "SleepPhysician",
    "Dentist",
    "LabTechnician",
    "BillingSpecialist",
    "ClinicCoordinator",
    "Patient",
)

UNSCOPED_ROLES = ("PlatformAdmin", "BillingSpecialist", "ClinicCoordinator")

PATH_COLLECTION = {
    "provider_id": ("providers", "ERR_PROVIDER_NOT_FOUND"),
    "payer_id": ("payers", "ERR_RECORD_NOT_FOUND"),
    "patient_id": ("patients", "ERR_PATIENT_NOT_FOUND"),
    "study_id": ("sleep_studies", "ERR_RECORD_NOT_FOUND"),
    "referral_id": ("referrals", "ERR_REFERRAL_NOT_FOUND"),
    "written_order_id": ("written_orders", "ERR_RECORD_NOT_FOUND"),
    "prior_auth_id": ("prior_auths", "ERR_RECORD_NOT_FOUND"),
    "lab_order_id": ("lab_orders", "ERR_RECORD_NOT_FOUND"),
    "lot_id": ("appliance_lots", "ERR_RECORD_NOT_FOUND"),
    "appliance_id": ("appliances", "ERR_APPLIANCE_NOT_FOUND"),
    "visit_id": ("titration_visits", "ERR_RECORD_NOT_FOUND"),
    "adherence_download_id": ("adherence_downloads", "ERR_RECORD_NOT_FOUND"),
    "report_id": ("efficacy_reports", "ERR_RECORD_NOT_FOUND"),
    "claim_id": ("claims", "ERR_RECORD_NOT_FOUND"),
    "repair_order_id": ("repair_orders", "ERR_RECORD_NOT_FOUND"),
    "audit_hold_id": ("audit_holds", "ERR_RECORD_NOT_FOUND"),
}

BODY_REFERENCE = {
    "patient_id": ("patients", "ERR_PATIENT_NOT_FOUND"),
    "provider_id": ("providers", "ERR_PROVIDER_NOT_FOUND"),
    "referring_physician_id": ("providers", "ERR_PROVIDER_NOT_FOUND"),
    "treating_dentist_id": ("providers", "ERR_PROVIDER_NOT_FOUND"),
    "ordering_physician_id": ("providers", "ERR_PROVIDER_NOT_FOUND"),
    "lab_provider_id": ("providers", "ERR_PROVIDER_NOT_FOUND"),
    "performed_by_dentist_id": ("providers", "ERR_PROVIDER_NOT_FOUND"),
    "referral_id": ("referrals", "ERR_REFERRAL_NOT_FOUND"),
    "appliance_id": ("appliances", "ERR_APPLIANCE_NOT_FOUND"),
    "replaces_appliance_id": ("appliances", "ERR_APPLIANCE_NOT_FOUND"),
    "loaner_appliance_id": ("appliances", "ERR_APPLIANCE_NOT_FOUND"),
    "payer_id": ("payers", "ERR_RECORD_NOT_FOUND"),
    "medical_payer_id": ("payers", "ERR_RECORD_NOT_FOUND"),
    "dental_payer_id": ("payers", "ERR_RECORD_NOT_FOUND"),
    "diagnostic_study_id": ("sleep_studies", "ERR_RECORD_NOT_FOUND"),
    "efficacy_study_id": ("sleep_studies", "ERR_RECORD_NOT_FOUND"),
    "written_order_id": ("written_orders", "ERR_RECORD_NOT_FOUND"),
    "prior_auth_id": ("prior_auths", "ERR_RECORD_NOT_FOUND"),
    "lab_order_id": ("lab_orders", "ERR_RECORD_NOT_FOUND"),
    "lot_id": ("appliance_lots", "ERR_RECORD_NOT_FOUND"),
    "repair_order_id": ("repair_orders", "ERR_RECORD_NOT_FOUND"),
}


# ------------------------------------------------------------- rungs 1 and 2

def actor(allowed_roles):
    """Rung 1 then rung 2.  Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not use this endpoint." % role)
    return uid, role


# ------------------------------------------------------------------- rung 3

def path_row(param, value):
    collection, error_id = PATH_COLLECTION[param]
    row = DB[collection].get(value)
    if row is None:
        fail(error_id, "No %s resolves to '%s'." % (param, value))
    return row


# ------------------------------------------------------------------- rung 4

def body_refs(body, ordered_names):
    """Resolve every foreign key supplied in the body, in declaration order."""
    resolved = {}
    for name in ordered_names:
        value = body.get(name)
        if value is None:
            resolved[name] = None
            continue
        collection, error_id = BODY_REFERENCE[name]
        row = DB[collection].get(value) if isinstance(value, str) else None
        if row is None:
            fail(error_id, "No %s resolves to '%s'." % (name, value))
        resolved[name] = row
    return resolved


# ------------------------------------------------------------------- rung 5

def gate_frozen(patient):
    """The global write gate — pre-empts rungs 6 through 35."""
    if patient is not None and patient.get("records_frozen"):
        fail("ERR_RECORDS_FROZEN", "The patient's records are frozen by an open payer audit.")


# ------------------------------------------------------------------- rung 6

def dentist_in_scope(uid, patient_id):
    for referral in DB["referrals"].values():
        if referral["treating_dentist_id"] == uid and referral["patient_id"] == patient_id:
            return True
    return False


def physician_in_scope(uid, patient_id):
    for study in DB["sleep_studies"].values():
        if study["ordering_physician_id"] == uid and study["patient_id"] == patient_id:
            return True
    for referral in DB["referrals"].values():
        if referral["referring_physician_id"] == uid and referral["patient_id"] == patient_id:
            return True
    return False


def in_scope(role, uid, patient_id):
    if role in UNSCOPED_ROLES:
        return True
    if role == "Dentist":
        return dentist_in_scope(uid, patient_id)
    if role == "SleepPhysician":
        return physician_in_scope(uid, patient_id)
    if role == "Patient":
        return uid == patient_id
    return False


def require_scope(role, uid, patient_id):
    if not in_scope(role, uid, patient_id):
        fail("ERR_NOT_CARE_TEAM", "The acting user is outside this patient's care team.")


def require_identity(uid, expected):
    if uid != expected:
        fail("ERR_NOT_CARE_TEAM", "The acting user is outside this patient's care team.")


# ------------------------------------------------------------------ rung 13

def gate_device(appliance):
    """The device gate — pre-empts rungs 14 through 35."""
    if appliance is not None and appliance.get("device_hold_status") == "RECALL_HOLD":
        fail("ERR_DEVICE_RECALL_HOLD", "The appliance is on a lot recall hold.")


# --------------------------------------------------- rows and version bumps

def _touched():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def touch(row):
    """Raise this row's version by exactly 1 — once per request, no matter how
    many rules inside the request wrote to it."""
    if row is None:
        return
    seen = _touched()
    if row["id"] in seen:
        return
    seen.add(row["id"])
    if "version" in row:
        row["version"] = row["version"] + 1
    row["updated_at"] = now_instant()


def new_row(collection, fields, versioned=True):
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = now_instant()
    row["_seq"] = next_seq()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    DB[collection][row["id"]] = row
    _touched().add(row["id"])
    return row


def ordered(rows):
    """Collections sort by created_at ascending; insertion order is the tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def newest(rows):
    items = ordered(rows)
    return items[-1] if items else None
