"""PreRegistration lifecycle + recording births (PRD §3.1, §3.2)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import services
from errors import (
    APIError,
    ERR_ADMIT_WINDOW_CLOSED,
    ERR_DUPLICATE_BIRTH_SEQUENCE,
    invalid_request,
    invalid_state,
    not_found,
)
from helpers import (
    get_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("registrations", __name__)

REG_STATUSES = {"DRAFT", "SUBMITTED", "ADMITTED", "BIRTH_RECORDED", "CLOSED", "CANCELLED"}


def _get_reg(reg_id):
    reg = db.pre_registrations.get(reg_id)
    if reg is None:
        raise not_found("Pre-registration not found.")
    return reg


@bp.post("/registrations")
def create_registration():
    require_roles("IntakeClerk")
    body = get_body()
    mother_full_name = require_field(body, "mother_full_name", str)
    mother_dob = require_field(body, "mother_dob", str)
    due_date = require_field(body, "due_date", str)
    payer_policy_id = require_field(body, "payer_policy_id", str)
    planned_delivery_facility = require_field(body, "planned_delivery_facility", str)
    birth_plan_flags = optional_field(body, "birth_plan_flags", dict, default={})
    row = {
        "id": db.new_id(),
        "mother_full_name": mother_full_name,
        "mother_dob": mother_dob,
        "due_date": due_date,
        "payer_policy_id": payer_policy_id,
        "planned_delivery_facility": planned_delivery_facility,
        "birth_plan_flags": birth_plan_flags,
        "status": "DRAFT",
        "admitted_at": None,
        "newborn_count": 0,
    }
    db.stamp_create(row)
    db.pre_registrations[row["id"]] = row
    return ok_object(db.public(row), 201)


@bp.get("/registrations/<reg_id>")
def get_registration(reg_id):
    require_roles("IntakeClerk", "AttendingNurse", "RegistrySupervisor")
    reg = _get_reg(reg_id)
    services.recompute_newborn_count(reg_id)
    return ok_object(db.public(reg))


@bp.get("/registrations")
def list_registrations():
    require_roles("IntakeClerk", "RegistrySupervisor")
    limit, offset = parse_pagination()
    payer_policy_id = request.args.get("payer_policy_id")
    status = request.args.get("status")
    rows = list(db.pre_registrations.values())
    if payer_policy_id is not None:
        rows = [r for r in rows if r["payer_policy_id"] == payer_policy_id]
    if status is not None:
        require_enum(status, "status", REG_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/registrations/<reg_id>/submit")
def submit_registration(reg_id):
    require_roles("IntakeClerk")
    reg = _get_reg(reg_id)
    if reg["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT registration may be submitted.")
    # Required intake fields present (they are required at create, but verify).
    for f in ("mother_full_name", "mother_dob", "due_date", "payer_policy_id",
              "planned_delivery_facility"):
        if not reg.get(f):
            raise invalid_request(f"Required field {f!r} is missing.")
    # payer_policy_id must resolve to an existing policy.
    if db.insurance_policies.get(reg["payer_policy_id"]) is None:
        raise not_found("payer_policy_id does not resolve to an insurance policy.")
    reg["status"] = "SUBMITTED"
    db.stamp_update(reg)
    return ok_object(db.public(reg))


@bp.post("/registrations/<reg_id>/admit")
def admit_registration(reg_id):
    require_roles("IntakeClerk")
    reg = _get_reg(reg_id)
    if reg["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED registration may be admitted.")
    # Admit window: clock DATE within [due_date - 21, due_date + 21] inclusive.
    now_date = db.current_utc_dt().date()
    due = db.parse_date(reg["due_date"]).date()
    lo = due - timedelta(days=21)
    hi = due + timedelta(days=21)
    if now_date < lo or now_date > hi:
        raise APIError(ERR_ADMIT_WINDOW_CLOSED,
                       "Current clock date is outside the admit window.", 422)
    reg["status"] = "ADMITTED"
    reg["admitted_at"] = db.current_utc_iso()
    db.stamp_update(reg)
    return ok_object(db.public(reg))


@bp.post("/registrations/<reg_id>/cancel")
def cancel_registration(reg_id):
    require_roles("IntakeClerk")
    reg = _get_reg(reg_id)
    if reg["status"] not in ("DRAFT", "SUBMITTED"):
        raise invalid_state("Only a DRAFT or SUBMITTED registration may be cancelled.")
    services.recompute_newborn_count(reg_id)
    if reg["newborn_count"] != 0:
        raise invalid_state("A registration with recorded newborns cannot be cancelled.")
    reg["status"] = "CANCELLED"
    db.stamp_update(reg)
    return ok_object(db.public(reg))


@bp.post("/registrations/<reg_id>/close")
def close_registration(reg_id):
    require_roles("RegistrySupervisor")
    reg = _get_reg(reg_id)
    if reg["status"] != "BIRTH_RECORDED":
        raise invalid_state("Only a BIRTH_RECORDED registration may be closed.")
    kids = [n for n in db.newborns.values() if n["pre_registration_id"] == reg_id]
    if not all(n["clinical_status"] == "DISCHARGED" for n in kids):
        raise invalid_state("All newborns must be DISCHARGED before closing.")
    reg["status"] = "CLOSED"
    db.stamp_update(reg)
    return ok_object(db.public(reg))


@bp.post("/registrations/<reg_id>/newborns")
def record_birth(reg_id):
    require_roles("AttendingNurse")
    reg = _get_reg(reg_id)
    body = get_body()
    birth_datetime = require_field(body, "birth_datetime", str)
    try:
        db.parse_iso(birth_datetime)
    except ValueError as e:
        raise invalid_request(str(e))
    birth_sequence = require_field(body, "birth_sequence", int)
    if birth_sequence < 1:
        raise invalid_request("birth_sequence must be >= 1.")
    weight_grams = require_field(body, "weight_grams", int)
    if weight_grams < 200:
        raise invalid_request("weight_grams must be >= 200.")
    gestational_age_weeks = require_field(body, "gestational_age_weeks", int)
    if not (20 <= gestational_age_weeks <= 45):
        raise invalid_request("gestational_age_weeks must be between 20 and 45.")
    apgar_5min = require_field(body, "apgar_5min", int)
    if not (0 <= apgar_5min <= 10):
        raise invalid_request("apgar_5min must be between 0 and 10.")
    legal_name = optional_field(body, "legal_name", str, default=None)

    # State: registration must be ADMITTED (first birth) or BIRTH_RECORDED (multiples).
    if reg["status"] not in ("ADMITTED", "BIRTH_RECORDED"):
        raise invalid_state("Births may only be recorded against an ADMITTED registration.")

    # birth_sequence unique within the registration.
    for n in db.newborns.values():
        if n["pre_registration_id"] == reg_id and n["birth_sequence"] == birth_sequence:
            raise APIError(ERR_DUPLICATE_BIRTH_SEQUENCE,
                           "birth_sequence is already used under this registration.", 409)

    newborn = {
        "id": db.new_id(),
        "pre_registration_id": reg_id,
        "birth_datetime": birth_datetime,
        "birth_sequence": birth_sequence,
        "weight_grams": weight_grams,
        "gestational_age_weeks": gestational_age_weeks,
        "apgar_5min": apgar_5min,
        "legal_name": legal_name,
        "clinical_status": "BORN",
        "care_location": "WELL_BABY_NURSERY",
        "discharge_readiness_score": 0,
        "discharged_at": None,
    }
    db.stamp_create(newborn)
    newborn["discharge_readiness_score"] = services.compute_discharge_readiness(newborn)
    db.newborns[newborn["id"]] = newborn

    # First birth advances ADMITTED -> BIRTH_RECORDED; multiples keep BIRTH_RECORDED.
    if reg["status"] == "ADMITTED":
        reg["status"] = "BIRTH_RECORDED"
    services.recompute_newborn_count(reg_id)
    db.stamp_update(reg)

    services.append_audit("BIRTH_RECORDED", request.headers.get("X-User-Role"),
                          newborn["id"],
                          {"pre_registration_id": reg_id,
                           "birth_sequence": birth_sequence})
    return ok_object(db.public(newborn), 201)


@bp.get("/registrations/<reg_id>/newborns")
def list_registration_newborns(reg_id):
    require_roles("AttendingNurse", "Neonatologist", "RegistrySupervisor")
    _get_reg(reg_id)
    limit, offset = parse_pagination()
    rows = [n for n in db.newborns.values() if n["pre_registration_id"] == reg_id]
    rows = sort_created_at_asc(rows)
    for n in rows:
        n["discharge_readiness_score"] = services.compute_discharge_readiness(n)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)
