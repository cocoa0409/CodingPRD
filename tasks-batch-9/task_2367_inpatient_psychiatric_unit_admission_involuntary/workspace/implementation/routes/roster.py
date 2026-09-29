"""Roster, unit and bed inventory, patient registration (PRD §3.1, §3.2)."""

from flask import Blueprint

import calc
import serializers
from auth import (
    ANY_ROLE,
    CHARGE_NURSE,
    COMPLIANCE_OFFICER,
    INTAKE_CLINICIAN,
    context,
)
from cascades import recompute_unit
from envelope import list_response, object_response
from errors import fail
from store import base_row, db, ordered
from validation import apply_filters, body, filters, pagination, venum, vint, vstr

bp = Blueprint("roster", __name__)

STAFF_ROLES = ("INTAKE_CLINICIAN", "PSYCHIATRIST", "CHARGE_NURSE", "RIGHTS_ADVOCATE")
GENDER_MIXING_POLICIES = ("SEPARATE_BY_ROOM", "SEPARATE_BY_WING", "MIXED_ALLOWED")
BED_TYPES = ("STANDARD", "LIGATURE_RESISTANT_OBSERVATION", "SECLUSION")
BED_STATUSES = ("AVAILABLE", "OCCUPIED", "BLOCKED_CLEANING", "OUT_OF_SERVICE")
GENDER_CARE_CATEGORIES = ("MALE", "FEMALE", "NONBINARY")


# --------------------------------------------------------------------------- #
# Clinicians
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/clinicians")
def create_clinician():
    context((COMPLIANCE_OFFICER,))
    data = body()
    full_name = vstr(data, "full_name")
    staff_role = venum(data, "staff_role", STAFF_ROLES)
    license_number = vstr(data, "license_number")
    if any(c["license_number"] == license_number for c in db.clinicians.values()):
        fail("ERR_INVALID_REQUEST", "license_number must be unique across clinicians")

    row = base_row()
    row.update(
        {
            "full_name": full_name,
            "staff_role": staff_role,
            "license_number": license_number,
            "booked_docket_minutes": 0,
        }
    )
    db.clinicians[row["id"]] = row
    return object_response(serializers.clinician(row), 201)


@bp.get("/behavioral-health/clinicians/<clinician_id>")
def get_clinician(clinician_id):
    context(ANY_ROLE)
    row = db.clinicians.get(clinician_id)
    if row is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "clinician not found")
    return object_response(serializers.clinician(row))


# --------------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/units")
def create_unit():
    context((COMPLIANCE_OFFICER,))
    data = body()
    name = vstr(data, "name")
    policy = venum(data, "gender_mixing_policy", GENDER_MIXING_POLICIES)
    seclusion_room_count = vint(data, "seclusion_room_count", minimum=0)

    row = base_row()
    row.update(
        {
            "name": name,
            "gender_mixing_policy": policy,
            "seclusion_room_count": seclusion_room_count,
            "licensed_placement_bed_count": 0,
            "raw_available_bed_count": 0,
            "posture": "CLOSED",
            "effective_available_bed_count": 0,
            "occupied_bed_count": 0,
            "active_seclusion_count": 0,
            "open_rights_violation_count": 0,
        }
    )
    db.units[row["id"]] = row
    # A brand-new unit has no beds: the four-step computation yields CLOSED.
    calc.compute_unit_counters(row)
    return object_response(serializers.unit(row), 201)


@bp.get("/behavioral-health/units/<unit_id>")
def get_unit(unit_id):
    context(ANY_ROLE)
    row = db.units.get(unit_id)
    if row is None:
        fail("ERR_UNIT_NOT_FOUND", "unit not found")
    return object_response(serializers.unit(row))


# --------------------------------------------------------------------------- #
# Beds
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/beds")
def create_bed():
    context((COMPLIANCE_OFFICER,))
    data = body()
    unit_id = vstr(data, "unit_id")
    room_number = vstr(data, "room_number")
    wing_code = vstr(data, "wing_code")
    bed_label = vstr(data, "bed_label")
    bed_type = venum(data, "bed_type", BED_TYPES)

    unit = db.units.get(unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND", "unit not found")
    for existing in db.beds.values():
        if (
            existing["unit_id"] == unit_id
            and existing["room_number"] == room_number
            and existing["bed_label"] == bed_label
        ):
            fail("ERR_INVALID_REQUEST", "bed_label must be unique within its room on this unit")

    row = base_row()
    row.update(
        {
            "unit_id": unit_id,
            "room_number": room_number,
            "wing_code": wing_code,
            "bed_label": bed_label,
            "bed_type": bed_type,
            "status": "AVAILABLE",
        }
    )
    db.beds[row["id"]] = row
    recompute_unit(unit)
    return object_response(serializers.bed(row), 201)


@bp.get("/behavioral-health/units/<unit_id>/beds")
def list_unit_beds(unit_id):
    context(ANY_ROLE)
    limit, offset = pagination()
    unit = db.units.get(unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND", "unit not found")
    rows = [b for b in db.beds.values() if b["unit_id"] == unit_id]
    rows = apply_filters(rows, filters("status", "bed_type"))
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.bed(r) for r in page], limit, offset, total)


@bp.patch("/behavioral-health/beds/<bed_id>")
def update_bed(bed_id):
    context((COMPLIANCE_OFFICER, CHARGE_NURSE))
    data = body()
    status = venum(data, "status", BED_STATUSES)
    row = db.beds.get(bed_id)
    if row is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "bed not found")

    row["status"] = status
    from store import touch

    touch(row)
    recompute_unit(db.units.get(row["unit_id"]))
    return object_response(serializers.bed(row))


# --------------------------------------------------------------------------- #
# Patients
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/patients")
def create_patient():
    context((COMPLIANCE_OFFICER, INTAKE_CLINICIAN))
    data = body()
    mrn = vstr(data, "mrn")
    legal_name = vstr(data, "legal_name")
    age_years = vint(data, "age_years", minimum=0, maximum=120)
    gender = venum(data, "gender_care_category", GENDER_CARE_CATEGORIES)
    if any(p["mrn"] == mrn for p in db.patients.values()):
        fail("ERR_INVALID_REQUEST", "mrn must be unique across patients")

    row = base_row()
    row.update(
        {
            "mrn": mrn,
            "legal_name": legal_name,
            "age_years": age_years,
            "is_minor": age_years < 18,
            "gender_care_category": gender,
            "active_hold_count": 0,
        }
    )
    db.patients[row["id"]] = row
    return object_response(serializers.patient(row), 201)


@bp.get("/behavioral-health/patients/<patient_id>")
def get_patient(patient_id):
    context(ANY_ROLE)
    row = db.patients.get(patient_id)
    if row is None:
        fail("ERR_PATIENT_NOT_FOUND", "patient not found")
    return object_response(serializers.patient(row))
