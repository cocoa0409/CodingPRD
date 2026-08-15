"""Paraprofessional endpoints (PRD §3.3): roster, status, qualifications."""
from flask import Blueprint, request

import db
import services as svc
from errors import ERR_PLAN_NOT_ACTIVE, ApiError
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    QUALIFICATIONS, as_date_str, as_enum, as_int, as_str, bad_request,
    body_json, need, opt,
)

bp = Blueprint("paras", __name__)

ADMIN = {"DistrictStaffingAdmin"}
ANY = {"Any"}
PARA_STATUSES = {"ACTIVE", "ON_LEAVE", "SEPARATED"}
# Declared transitions of the Paraprofessional state machine.
ALLOWED_TRANSITIONS = {
    ("ACTIVE", "ON_LEAVE"),
    ("ON_LEAVE", "ACTIVE"),
    ("ACTIVE", "SEPARATED"),
    ("ON_LEAVE", "SEPARATED"),
}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/paraprofessionals")
def create_para():
    _auth(ADMIN)
    body = body_json(request)
    plan_id = need(body, "plan_id")
    plan = svc.get_plan(as_str(plan_id, "plan_id"))
    home_building_id = need(body, "home_building_id")
    building = svc.get_building(as_str(home_building_id, "home_building_id"))
    full_name = as_str(need(body, "full_name"), "full_name")
    email = as_str(need(body, "email"), "email")
    wage = as_int(need(body, "base_hourly_wage_cents"), "base_hourly_wage_cents")
    if wage <= 0:
        bad_request("base_hourly_wage_cents must be > 0")
    cap = as_int(need(body, "contracted_max_weekly_minutes"),
                 "contracted_max_weekly_minutes")
    if cap <= 0:
        bad_request("contracted_max_weekly_minutes must be > 0")
    hire_date = as_date_str(need(body, "hire_date"), "hire_date")
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "roster writes require plan DRAFT or ACTIVE")
    for p in db.STORE["paras"].values():
        if p["plan_id"] == plan["id"] and p["email"] == email:
            bad_request("email must be unique within the plan")
    para = {
        "plan_id": plan["id"],
        "home_building_id": building["id"],
        "full_name": full_name,
        "email": email,
        "base_hourly_wage_cents": wage,
        "contracted_max_weekly_minutes": cap,
        "hire_date": hire_date,
        "qualifications": [],
        "confirmed_benefit_eligible": None,
        "benefit_variance_cents": 0,
        "status": "ACTIVE",
        "_benefit_flag": False,
    }
    svc.stamp_new(para)
    db.STORE["paras"][para["id"]] = para
    return success(svc.ser_para(para), "object", 201)


@bp.get("/sped-staffing/paraprofessionals")
def list_paras():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    home_building_id = request.args.get("home_building_id")
    status = request.args.get("status")
    items = []
    for p in svc.sorted_records("paras"):
        if plan_id is not None and p["plan_id"] != plan_id:
            continue
        if home_building_id is not None and p["home_building_id"] != home_building_id:
            continue
        if status is not None and p["status"] != status:
            continue
        items.append(svc.ser_para(p))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/paraprofessionals/<paraId>")
def get_para(paraId):
    _auth(ANY)
    para = svc.get_para(paraId)
    return success(svc.ser_para(para), "object", 200)


@bp.post("/sped-staffing/paraprofessionals/<paraId>/set-status")
def set_para_status(paraId):
    _auth(ADMIN)
    para = svc.get_para(paraId)
    body = body_json(request)
    target = as_enum(need(body, "status"), "status", PARA_STATUSES)
    if (para["status"], target) not in ALLOWED_TRANSITIONS:
        bad_request("status transition %s -> %s is not allowed"
                    % (para["status"], target))
    para["status"] = target
    svc.touch(para)
    if target == "SEPARATED":
        plan = db.STORE["plans"][para["plan_id"]]
        live = [a for a in db.STORE["assignments"].values()
                if a["para_id"] == para["id"]
                and a["status"] in ("PROPOSED", "QUALIFICATION_VERIFIED",
                                    "ACTIVE", "SUSPENDED")]
        svc.end_assignments_cascade(live, plan, "COORDINATOR_ENDED")
    return success(svc.ser_para(para), "object", 200)


@bp.post("/sped-staffing/paraprofessionals/<paraId>/qualifications")
def add_qualification(paraId):
    _auth(ADMIN)
    para = svc.get_para(paraId)
    body = body_json(request)
    qual = as_enum(need(body, "qualification"), "qualification", QUALIFICATIONS)
    completed_on = as_date_str(need(body, "completed_on"), "completed_on")
    expires_on = body.get("expires_on")
    if expires_on is not None:
        expires_on = as_date_str(expires_on, "expires_on")
    para["qualifications"].append({
        "qualification": qual,
        "completed_on": completed_on,
        "expires_on": expires_on,
        "revoked": False,
    })
    svc.touch(para)
    return success(svc.ser_para(para), "object", 200)


@bp.post("/sped-staffing/paraprofessionals/<paraId>/qualifications/revoke")
def revoke_qualification(paraId):
    _auth(ADMIN)
    para = svc.get_para(paraId)
    body = body_json(request)
    qual = as_enum(need(body, "qualification"), "qualification", QUALIFICATIONS)
    for q in para["qualifications"]:
        if q["qualification"] == qual and not q["revoked"]:
            q["revoked"] = True
    svc.touch(para)
    # Safety cascade: suspend this para's ACTIVE assignments requiring the
    # revoked credential; auto-create absence reports where a PUBLISHED
    # coverage plan covers (building, current logical date).
    plan = db.STORE["plans"][para["plan_id"]]
    role = request.headers.get("X-User-Role")
    targets = [a for a in db.STORE["assignments"].values()
               if a["para_id"] == para["id"] and a["status"] == "ACTIVE"
               and a["required_qualification_snapshot"] == qual]
    targets.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for a in targets:
        svc.suspend_assignment(a, para, plan)
        svc.maybe_auto_absence(a, plan, role)
    return success(svc.ser_para(para), "object", 200)
