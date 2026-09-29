"""Capacity determinations and medication consent (PRD §3.7)."""

from datetime import timedelta

from flask import Blueprint

import serializers
from auth import ANY_ROLE, ATTENDING_PSYCHIATRIST, context
from envelope import list_response, object_response
from errors import fail
from store import base_row, db, ordered, touch
from validation import apply_filters, body, filters, pagination, vbool, venum, vint, vstr

bp = Blueprint("consents", __name__)

SURROGATE_RELATIONSHIPS = ("SPOUSE", "PARENT", "ADULT_CHILD", "GUARDIAN")
SURROGATE_SCOPES = ("NONE", "MEDICATION_ONLY", "FULL")
CONSENT_BASES = ("PATIENT_CONSENT", "SURROGATE_CONSENT", "EMERGENCY_OVERRIDE")
MEDICATION_SCOPES = ("MEDICATION_ONLY", "FULL")
EMERGENCY_OVERRIDE_HOURS = 72


def _active_determination(admission_id):
    for row in ordered(list(db.capacity_determinations.values())):
        if row["admission_id"] == admission_id and row["status"] == "ACTIVE":
            return row
    return None


def _patient_has_active_hold(patient_id):
    return any(
        h["patient_id"] == patient_id and h["status"] == "ACTIVE" for h in db.holds.values()
    )


# --------------------------------------------------------------------------- #
# Capacity determinations
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/capacity-determinations")
def create_capacity_determination():
    user_id, _role = context((ATTENDING_PSYCHIATRIST,))
    data = body()
    admission_id = vstr(data, "admission_id")
    expected_admission_version = vint(data, "expected_admission_version")
    capacity_present = vbool(data, "capacity_present")
    surrogate_name = vstr(data, "surrogate_name", required=False)
    surrogate_relationship = venum(
        data, "surrogate_relationship", SURROGATE_RELATIONSHIPS, required=False
    )
    surrogate_authority_scope = venum(
        data, "surrogate_authority_scope", SURROGATE_SCOPES, required=False
    )

    admission = db.admissions.get(admission_id)
    if admission is None:
        fail("ERR_ADMISSION_NOT_FOUND", "admission not found")
    if expected_admission_version != admission["version"]:
        fail(
            "ERR_STALE_ADMISSION_VERSION",
            "expected_admission_version does not match the admission's version",
        )

    supplied = [surrogate_name, surrogate_relationship, surrogate_authority_scope]
    if capacity_present:
        if any(value is not None for value in supplied):
            fail("ERR_SURROGATE_REQUIRED", "surrogate fields must be omitted when capacity is present")
    else:
        if any(value is None for value in supplied):
            fail("ERR_SURROGATE_REQUIRED", "all three surrogate fields are required when capacity is absent")

    prior = _active_determination(admission_id)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    row = base_row()
    row.update(
        {
            "admission_id": admission_id,
            "determined_by_clinician_id": user_id,
            "capacity_present": capacity_present,
            "surrogate_name": surrogate_name,
            "surrogate_relationship": surrogate_relationship,
            "surrogate_authority_scope": surrogate_authority_scope,
            "determined_at": db.now(),
            "status": "ACTIVE",
        }
    )
    db.capacity_determinations[row["id"]] = row

    admission["capacity_present"] = capacity_present
    touch(admission)
    return object_response(serializers.capacity_determination(row), 201)


@bp.get("/behavioral-health/capacity-determinations/<determination_id>")
def get_capacity_determination(determination_id):
    context(ANY_ROLE)
    row = db.capacity_determinations.get(determination_id)
    if row is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "capacity determination not found")
    return object_response(serializers.capacity_determination(row))


@bp.get("/behavioral-health/capacity-determinations")
def list_capacity_determinations():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.capacity_determinations.values()),
        filters("admission_id", "determined_by_clinician_id", "status"),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response(
        [serializers.capacity_determination(r) for r in page], limit, offset, total
    )


# --------------------------------------------------------------------------- #
# Medication consents
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/medication-consents")
def create_medication_consent():
    user_id, _role = context((ATTENDING_PSYCHIATRIST,))
    data = body()
    admission_id = vstr(data, "admission_id")
    medication_name = vstr(data, "medication_name")
    consent_basis = venum(data, "consent_basis", CONSENT_BASES)
    capacity_determination_id = vstr(data, "capacity_determination_id", required=False)
    emergency_justification = vstr(data, "emergency_justification", required=False)
    if consent_basis == "SURROGATE_CONSENT" and capacity_determination_id is None:
        fail("ERR_INVALID_REQUEST", "capacity_determination_id is required for SURROGATE_CONSENT")
    if consent_basis == "EMERGENCY_OVERRIDE" and not emergency_justification:
        fail("ERR_INVALID_REQUEST", "emergency_justification is required for EMERGENCY_OVERRIDE")

    admission = db.admissions.get(admission_id)
    if admission is None:
        fail("ERR_ADMISSION_NOT_FOUND", "admission not found")
    cited = None
    if capacity_determination_id is not None:
        cited = db.capacity_determinations.get(capacity_determination_id)
        if cited is None:
            fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "capacity determination not found")

    expires_at = None
    if consent_basis == "PATIENT_CONSENT":
        active = _active_determination(admission_id)
        if active is None or not active["capacity_present"]:
            fail("ERR_CAPACITY_LACKING", "patient consent requires an ACTIVE finding of capacity")
    elif consent_basis == "SURROGATE_CONSENT":
        if (
            cited["status"] != "ACTIVE"
            or cited["capacity_present"]
            or cited["surrogate_authority_scope"] not in MEDICATION_SCOPES
        ):
            fail(
                "ERR_SURROGATE_SCOPE_INSUFFICIENT",
                "the cited determination does not authorize a surrogate medication consent",
            )
    else:
        if not _patient_has_active_hold(admission["patient_id"]):
            fail("ERR_NO_ACTIVE_HOLD", "an emergency override requires an ACTIVE hold")
        if admission["legal_status"] != "INVOLUNTARY":
            fail("ERR_NO_ACTIVE_HOLD", "an emergency override requires an involuntary admission")
        expires_at = db.now() + timedelta(hours=EMERGENCY_OVERRIDE_HOURS)

    row = base_row()
    row.update(
        {
            "admission_id": admission_id,
            "capacity_determination_id": (
                capacity_determination_id if consent_basis == "SURROGATE_CONSENT" else None
            ),
            "prescribing_clinician_id": user_id,
            "medication_name": medication_name,
            "consent_basis": consent_basis,
            "emergency_justification": (
                emergency_justification if consent_basis == "EMERGENCY_OVERRIDE" else None
            ),
            "expires_at": expires_at,
            "status": "ACTIVE",
        }
    )
    db.medication_consents[row["id"]] = row
    return object_response(serializers.medication_consent(row), 201)


@bp.get("/behavioral-health/medication-consents/<consent_id>")
def get_medication_consent(consent_id):
    context(ANY_ROLE)
    row = db.medication_consents.get(consent_id)
    if row is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "medication consent not found")
    return object_response(serializers.medication_consent(row))


@bp.get("/behavioral-health/medication-consents")
def list_medication_consents():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.medication_consents.values()),
        filters("admission_id", "capacity_determination_id", "prescribing_clinician_id", "status"),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.medication_consent(r) for r in page], limit, offset, total)
