"""Physician endpoints (PRD 3.1, 3.9)."""

from flask import Blueprint, request

import domain as D
from db import store, new_record, bump
from errors import (
    ApiError, ERR_VALIDATION, ERR_PHYSICIAN_NOT_FOUND, ERR_INVALID_STATE,
)
from middleware import get_context, require_role, ALL_ROLES
from response import success_object, paginate

bp = Blueprint("physicians", __name__)


@bp.route("/onboarding/physicians", methods=["POST"])
def create_physician():
    _uid, role = get_context()
    require_role(role, ["Recruiter"])
    body = D.get_body()
    full_name = D.req_str(body, "full_name")
    specialty = D.req_enum(body, "specialty", D.SPECIALTIES)
    email = D.req_str(body, "email")
    hire_type = D.req_enum(body, "hire_type", D.HIRE_TYPES)
    for p in store.physicians.values():
        if p["email"] == email:
            raise ApiError(ERR_VALIDATION, 400, "email must be unique per physician")
    rec = new_record()
    rec.update({
        "full_name": full_name,
        "specialty": specialty,
        "email": email,
        "hire_type": hire_type,
        "status": "PROSPECT",
    })
    store.physicians[rec["id"]] = rec
    return success_object(D.serialize_physician(rec), status=201)


@bp.route("/onboarding/physicians/<pid>", methods=["GET"])
def get_physician(pid):
    get_context()
    p = store.physicians.get(pid)
    if p is None:
        raise ApiError(ERR_PHYSICIAN_NOT_FOUND, 404, "Physician not found")
    return success_object(D.serialize_physician(p))


@bp.route("/onboarding/physicians", methods=["GET"])
def list_physicians():
    get_context()
    specialty = request.args.get("specialty")
    status = request.args.get("status")
    records = sorted(store.physicians.values(), key=lambda r: r["_seq"])
    if specialty is not None:
        records = [r for r in records if r["specialty"] == specialty]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([D.serialize_physician(r) for r in records], request.args)


@bp.route("/onboarding/physicians/<pid>/mark-active", methods=["POST"])
def mark_active(pid):
    _uid, role = get_context()
    require_role(role, ["OnboardingDirector"])
    p = store.physicians.get(pid)
    if p is None:
        raise ApiError(ERR_PHYSICIAN_NOT_FOUND, 404, "Physician not found")
    if p["status"] != "PROSPECT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PROSPECT physician can be marked active")
    p["status"] = "ACTIVE"
    bump(p)
    return success_object(D.serialize_physician(p))


@bp.route("/onboarding/physicians/<pid>/separate", methods=["POST"])
def separate(pid):
    _uid, role = get_context()
    require_role(role, ["OnboardingDirector"])
    p = store.physicians.get(pid)
    if p is None:
        raise ApiError(ERR_PHYSICIAN_NOT_FOUND, 404, "Physician not found")
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE physician can be separated")
    p["status"] = "SEPARATED"
    bump(p)
    case = D.case_for_physician(pid)
    if case is not None:
        panel = D.panel_of_case(case["id"])
        if panel is not None and panel["status"] in ("OPEN", "FROZEN"):
            panel["status"] = "CLOSED"
            bump(panel)
        for assignment in D.assignments_of_case(case["id"]):
            if assignment["status"] == "ACTIVE":
                assignment["status"] = "COMPLETED"
                bump(assignment)
        guarantee = D.guarantee_of_case(case["id"])
        if guarantee is not None and guarantee["status"] == "ACTIVE":
            guarantee["status"] = "SETTLED"
            bump(guarantee)
        for campaign in D.campaigns_of_case(case["id"]):
            if campaign["status"] == "ACTIVE":
                campaign["status"] = "COMPLETED"
                bump(campaign)
        case["case_status"] = "SEPARATED"
        bump(case)
    return success_object(D.serialize_physician(p))
