"""BiometricScreening endpoints (PRD §3.4)."""
from datetime import datetime, time, timezone

from flask import Blueprint

from db import DB
from errors import ApiError, invalid
from middleware import require_roles
from response import success
from services import serializers
from services.common import (
    check_employee_scope, get_enrollment_or_404, get_screening_or_404,
    parse_body, require_fields, stamp_new, touch,
)
from clock import iso_from_dt

bp = Blueprint("screenings", __name__)


def _strict_overlap(a_start, a_end, b_start, b_end):
    """new.start < other.end AND new.end > other.start; adjacency does not
    count (PRD §3.4)."""
    return a_start < b_end and a_end > b_start


@bp.post("/wellness/biometric-screenings")
@require_roles("Employee")
def create_screening():
    body = parse_body()
    vals = require_fields(body, [
        ("enrollment_id", "string", True),
        ("clinic_location", "string", True),
        ("slot_start", "datetime", True),
        ("slot_end", "datetime", True),
    ])
    enr = get_enrollment_or_404(vals["enrollment_id"])
    check_employee_scope(enr)
    if enr["participation_status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE",
            "Screening scheduling requires an ACTIVE enrollment",
        )
    slot_start, slot_end = vals["slot_start"], vals["slot_end"]
    if not slot_end > slot_start:
        raise invalid("slot_end must be strictly after slot_start")
    program = DB.programs[enr["program_id"]]
    employer = DB.employers[program["employer_id"]]
    # kiosk capacity (stage 8) before the plan-year temporal rule (stage 9)
    overlapping = 0
    for other in DB.screenings.values():
        if other["status"] != "SCHEDULED":
            continue
        if other["clinic_location"] != vals["clinic_location"]:
            continue
        if _strict_overlap(slot_start, slot_end, other["_slot_start"], other["_slot_end"]):
            overlapping += 1
    if overlapping >= employer["kiosk_capacity"]:
        raise ApiError(
            "ERR_KIOSK_CAPACITY_EXCEEDED",
            "Overlapping SCHEDULED screenings at this clinic_location reached kiosk_capacity",
        )
    # plan-year window: slot_start >= plan_year_start and slot_end <= plan_year_end
    py_start = datetime.combine(program["_pys"], time.min, tzinfo=timezone.utc)
    py_end = datetime.combine(program["_pye"], time.min, tzinfo=timezone.utc)
    if slot_start < py_start or slot_end > py_end:
        raise ApiError(
            "ERR_SLOT_OUTSIDE_WINDOW",
            "Screening slot must sit inside the program plan year",
        )
    rec = stamp_new({
        "enrollment_id": enr["id"],
        "clinic_location": vals["clinic_location"],
        "slot_start": iso_from_dt(slot_start),
        "slot_end": iso_from_dt(slot_end),
        "_slot_start": slot_start,
        "_slot_end": slot_end,
        "bmi": None,
        "systolic_bp": None,
        "total_cholesterol": None,
        "glucose": None,
        "targets_met": None,
        "status": "SCHEDULED",
    })
    DB.screenings[rec["id"]] = rec
    return success(serializers.screening(rec), status=201)


@bp.post("/wellness/biometric-screenings/<sid>/result")
@require_roles("BenefitsAdmin")
def result_screening(sid):
    sc = get_screening_or_404(sid)
    body = parse_body()
    vals = require_fields(body, [
        ("bmi", "number", True),
        ("systolic_bp", "int", True),
        ("total_cholesterol", "int", True),
        ("glucose", "int", True),
    ])
    if sc["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SCHEDULED screening may be resulted"
        )
    sc["bmi"] = vals["bmi"]
    sc["systolic_bp"] = vals["systolic_bp"]
    sc["total_cholesterol"] = vals["total_cholesterol"]
    sc["glucose"] = vals["glucose"]
    targets = (
        (1 if vals["bmi"] < 30.0 else 0)
        + (1 if vals["systolic_bp"] < 140 else 0)
        + (1 if vals["total_cholesterol"] < 200 else 0)
        + (1 if vals["glucose"] < 100 else 0)
    )
    sc["targets_met"] = targets
    sc["status"] = "RESULTED"
    touch(sc)
    # verification axis modulation (PRD §3.4)
    enr = DB.enrollments[sc["enrollment_id"]]
    if targets <= 1 and enr["verification_status"] == "VERIFIED":
        enr["verification_status"] = "FLAGGED"
        touch(enr)
    elif targets >= 3 and enr["verification_status"] == "FLAGGED":
        enr["verification_status"] = "VERIFIED"
        touch(enr)
    return success(serializers.screening(sc))
