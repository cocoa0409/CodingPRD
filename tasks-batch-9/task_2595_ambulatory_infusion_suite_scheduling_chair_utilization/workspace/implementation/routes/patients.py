"""Patients, no-show risk reads, and treatment plans (PRD 3.3, 3.9)."""

from flask import Blueprint

import db
from db import apply_changes, must, new_row, rows
from errors import ApiError
from middleware import authenticate, require_patient_owner
from response import created, ok
from routes.common import paged
from services import derive, present
from validators import (
    body,
    opt_bool,
    q_enum,
    q_str,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("patients", __name__)

ALL_STAFF = ("Scheduler", "InfusionNurse", "Pharmacist", "AuthorizationSpecialist", "MedicalDirector")
TIERS = ("STANDARD", "ELEVATED", "INTENSIVE")
STEERING = ("SUITE", "HOME_INFUSION_REVIEW")
PLAN_STATUSES = ("ACTIVE", "SUSPENDED", "COMPLETED", "SUPERSEDED")
RISK_VARIANTS = ("ROLLING_6", "QUARTER_TO_DATE")


# ------------------------------------------------------------------ patients
@bp.post("/patients")
def create_patient():
    authenticate("Scheduler")
    data = body()
    mrn = req_str(data, "mrn", 1, 32)
    full_name = req_str(data, "full_name", 1, 120)
    req_num(data, "weight_kg", 1, 400)
    for patient in rows("patients"):
        if patient["mrn"] == mrn:
            raise ApiError("ERR_DUPLICATE_MRN")
    row = new_row(
        "patients",
        {
            "mrn": mrn,
            "full_name": full_name,
            "weight_kg": data["weight_kg"],
            "completed_appointment_count": 0,
            "no_show_strikes": 0,
            "no_show_risk_score": 0.0,
            "reminder_tier": "STANDARD",
            "waste_liability_cents": 0,
            "steering_status": "SUITE",
        },
    )
    return created(present.plain(row))


@bp.get("/patients/<patient_id>")
def read_patient(patient_id):
    authenticate("Scheduler", "InfusionNurse", "MedicalDirector", "Patient")
    require_patient_owner(patient_id if db.get("patients", patient_id) else None)
    return ok(present.plain(must("patients", patient_id)))


@bp.get("/patients")
def list_patients():
    authenticate("Scheduler", "InfusionNurse", "MedicalDirector")
    mrn = q_str("mrn")
    tier = q_enum("reminder_tier", TIERS)
    steering = q_enum("steering_status", STEERING)
    items = []
    for patient in rows("patients"):
        if mrn is not None and patient["mrn"] != mrn:
            continue
        if tier is not None and patient["reminder_tier"] != tier:
            continue
        if steering is not None and patient["steering_status"] != steering:
            continue
        items.append(patient)
    return paged("patients", items)


@bp.get("/patients/<patient_id>/no-show-risk")
def read_no_show_risk(patient_id):
    authenticate("Scheduler", "MedicalDirector", "Patient")
    require_patient_owner(patient_id if db.get("patients", patient_id) else None)
    variant = q_enum("variant", RISK_VARIANTS, "ROLLING_6")
    patient = must("patients", patient_id)
    if variant == "QUARTER_TO_DATE":
        score, considered = derive.quarter_to_date(patient_id)
    else:
        score, considered = derive.rolling_six(patient_id)
    return ok(
        {
            "patient_id": patient_id,
            "variant": variant,
            "score": float(score),
            "reminder_tier": patient["reminder_tier"],
            "considered_appointment_count": considered,
        }
    )


# ------------------------------------------------------------------ plans
@bp.post("/treatment-plans")
def create_plan():
    authenticate("Scheduler", "MedicalDirector")
    data = body()
    patient_id = req_str(data, "patient_id", 1, None)
    drug_id = req_str(data, "drug_id", 1, None)
    req_num(data, "dose_mg_per_kg", None, 100, exclusive_lo=0)
    total_cycles = req_int(data, "total_cycles", 1, 52)
    premed_waived = opt_bool(data, "premed_waived", False)
    must("patients", patient_id)
    must("drugs", drug_id)
    row = new_row(
        "plans",
        {
            "patient_id": patient_id,
            "drug_id": drug_id,
            "supersedes_plan_id": None,
            "dose_mg_per_kg": data["dose_mg_per_kg"],
            "total_cycles": total_cycles,
            "premed_waived": premed_waived,
            "completed_cycles": 0,
            "first_dose_completed": False,
            "status": "ACTIVE",
        },
    )
    return created(present.plain(row))


@bp.get("/treatment-plans/<plan_id>")
def read_plan(plan_id):
    authenticate(*(ALL_STAFF + ("Patient",)))
    return ok(present.plain(must("plans", plan_id)))


@bp.get("/treatment-plans")
def list_plans():
    authenticate(*ALL_STAFF)
    patient_id = q_str("patient_id")
    drug_id = q_str("drug_id")
    supersedes = q_str("supersedes_plan_id")
    status = q_enum("status", PLAN_STATUSES)
    items = []
    for plan in rows("plans"):
        if patient_id is not None and plan["patient_id"] != patient_id:
            continue
        if drug_id is not None and plan["drug_id"] != drug_id:
            continue
        if supersedes is not None and plan["supersedes_plan_id"] != supersedes:
            continue
        if status is not None and plan["status"] != status:
            continue
        items.append(plan)
    return paged("plans", items)


@bp.post("/treatment-plans/<plan_id>/revisions")
def revise_plan(plan_id):
    authenticate("Scheduler", "MedicalDirector")
    data = body()
    req_num(data, "dose_mg_per_kg", None, 100, exclusive_lo=0)
    total_cycles = req_int(data, "total_cycles", 1, 52)
    premed_waived = opt_bool(data, "premed_waived", False)
    expected_version = req_int(data, "expected_treatment_plan_version", None, None)
    plan = must("plans", plan_id)
    if expected_version != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION")
    # The supersede edge is declared out of both ACTIVE and SUSPENDED (PRD 3.3).
    if plan["status"] == "COMPLETED":
        raise ApiError("ERR_PLAN_COMPLETED")
    if plan["status"] == "SUPERSEDED":
        raise ApiError("ERR_PLAN_SUPERSEDED")
    apply_changes(plan, {"status": "SUPERSEDED"})
    replacement = new_row(
        "plans",
        {
            "patient_id": plan["patient_id"],
            "drug_id": plan["drug_id"],
            "supersedes_plan_id": plan["id"],
            "dose_mg_per_kg": data["dose_mg_per_kg"],
            "total_cycles": total_cycles,
            "premed_waived": premed_waived,
            "completed_cycles": 0,
            "first_dose_completed": False,
            "status": "ACTIVE",
        },
    )
    derive.cancel_live_visits(plan)
    return created(present.plain(replacement))


@bp.post("/treatment-plans/<plan_id>/resume")
def resume_plan(plan_id):
    authenticate("MedicalDirector")
    data = body()
    req_str(data, "reason", 1, None)
    plan = must("plans", plan_id)
    if plan["status"] == "COMPLETED":
        raise ApiError("ERR_PLAN_COMPLETED")
    if plan["status"] == "SUPERSEDED":
        raise ApiError("ERR_PLAN_SUPERSEDED")
    if plan["status"] != "SUSPENDED":
        raise ApiError("ERR_PLAN_SUSPENDED")
    patient = db.get("patients", plan["patient_id"])
    if (patient or {}).get("steering_status") != "SUITE":
        raise ApiError("ERR_PATIENT_STEERING_HOLD")
    apply_changes(plan, {"status": "ACTIVE"})
    return ok(present.plain(plan))
