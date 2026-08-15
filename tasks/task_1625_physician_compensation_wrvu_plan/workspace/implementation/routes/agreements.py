"""PhysicianAgreement endpoints (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_PLAN_NOT_ACTIVE, ERR_DUPLICATE_RESOURCE, ERR_SEGREGATION_OF_DUTIES,
    ERR_FMV_COOLING_OFF, ERR_FMV_STALE, ERR_FMV_CAP_EXCEEDED,
    ERR_NOT_OWN_RESOURCE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public, agreement_out
from services.ledger import void_draft_statements, projected_annual_productivity_cents
from util import CLOCK, parse_iso_datetime, add_months_dt, parse_date_strict
from validate import (
    get_body, req_int, req_enum, req_date, require_path_resource, require_body_ref,
)

bp = Blueprint("agreements", __name__)

AGREEMENT_READ_ROLES = ["CompAnalyst", "CompCommittee", "ComplianceOfficer", "Physician"]
NON_TERMINAL_AGREEMENT_STATUSES = ("DRAFT", "PENDING_FMV", "FMV_APPROVED", "EFFECTIVE", "AMENDMENT_REQUIRED")


def _owner_id(agreement):
    return agreement["physician_id"]


@bp.post("/physician-agreements")
def create_agreement():
    caller = authorized(["CompAnalyst"])
    body = get_body()
    # Priority 4: body FK existence (when present and well-typed)
    physician_id = body.get("physician_id")
    plan_id = body.get("plan_id")
    require_body_ref("physicians", physician_id, "physician_id")
    plan = require_body_ref("comp_plans", plan_id, "plan_id")
    # Priority 8: referenced plan must be FMV_APPROVED or ACTIVE
    if plan is not None and plan["status"] not in ("FMV_APPROVED", "ACTIVE"):
        raise_error(ERR_PLAN_NOT_ACTIVE,
                    "agreement creation requires the plan to be FMV_APPROVED or ACTIVE")
    # Priority 14: payload shape
    if not isinstance(physician_id, str) or not physician_id:
        raise_error(ERR_VALIDATION, "missing or invalid field: physician_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise_error(ERR_VALIDATION, "missing or invalid field: plan_id")
    base_salary_cents = req_int(body, "base_salary_cents", positive=True)
    period_draw_cents = req_int(body, "period_draw_cents", non_negative=True)
    effective_date = req_date(body, "effective_date")
    # Priority 21: one non-terminal agreement per (physician, plan)
    for a in db["physician_agreements"].values():
        if (a["physician_id"] == physician_id and a["plan_id"] == plan_id
                and a["status"] in NON_TERMINAL_AGREEMENT_STATUSES):
            raise_error(ERR_DUPLICATE_RESOURCE,
                        "a non-terminal agreement already exists for this physician and plan")
    rec = new_record("physician_agreements", {
        "physician_id": physician_id,
        "plan_id": plan_id,
        "pinned_plan_version": plan["version"],
        "base_salary_cents": base_salary_cents,
        "period_draw_cents": period_draw_cents,
        "effective_date": effective_date,
        "status": "DRAFT",
        "fmv_reviewed_at": None,
        "fmv_reviewer_user_id": None,
        "fmv_benchmark_percentile": None,
        "last_fmv_rejected_at": None,
        "created_by_user_id": caller.user_id,
        "ytd_wrvu_credited": 0.0,
        "lifetime_paid_cents": 0,
        "pending_trueup_adjustment_cents": 0,
    })
    return success_object(agreement_out(rec), status=201)


@bp.get("/physician-agreements")
def list_agreements():
    caller = authorized(AGREEMENT_READ_ROLES)
    physician_id = request.args.get("physician_id")
    if caller.role == "Physician":
        if physician_id is not None and physician_id != caller.user_id:
            raise_error(ERR_NOT_OWN_RESOURCE,
                        "a Physician may list only its own agreements")
        physician_id = caller.user_id
    filters = {
        "physician_id": physician_id,
        "plan_id": request.args.get("plan_id"),
        "status": request.args.get("status"),
    }
    return list_response("physician_agreements", filters, serializer=agreement_out)


@bp.get("/physician-agreements/<rid>")
def get_agreement(rid):
    caller = authorized(AGREEMENT_READ_ROLES)
    rec = db["physician_agreements"].get(rid)
    if rec is not None and caller.role == "Physician" and rec["physician_id"] != caller.user_id:
        raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may read only its own agreements")
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"agreement not found: {rid}")
    return success_object(agreement_out(rec))


@bp.post("/physician-agreements/<rid>/submit-fmv")
def submit_fmv(rid):
    authorized(["CompAnalyst"])
    agr = require_path_resource("physician_agreements", rid)
    # State guard fires first; cooling-off follows it (PRD 3.3)
    if agr["status"] not in ("DRAFT", "EFFECTIVE"):
        raise_error(ERR_INVALID_STATE,
                    "submit-fmv requires status DRAFT or EFFECTIVE")
    rejected = agr.get("last_fmv_rejected_at")
    if rejected is not None:
        rejected_date = parse_iso_datetime(rejected).date()
        if CLOCK.today() < rejected_date + timedelta(days=30):
            raise_error(ERR_FMV_COOLING_OFF,
                        "submit-fmv within 30 days after the last FMV rejection")
    agr["status"] = "PENDING_FMV"
    touch("physician_agreements", agr)
    return success_object(agreement_out(agr))


@bp.post("/physician-agreements/<rid>/fmv-review")
def fmv_review(rid):
    caller = authorized(["ComplianceOfficer"])
    agr = require_path_resource("physician_agreements", rid)
    # State guard before segregation of duties (PRD 3.3)
    if agr["status"] != "PENDING_FMV":
        raise_error(ERR_INVALID_STATE, "fmv-review requires status PENDING_FMV")
    if caller.user_id == agr["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "FMV reviewer must differ from the agreement creator")
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVED", "REJECTED"})
    percentile = req_int(body, "benchmark_percentile", minimum=0, maximum=100)
    if decision == "APPROVED":
        agr["status"] = "FMV_APPROVED"
        agr["fmv_reviewed_at"] = CLOCK.now_iso()
        agr["fmv_reviewer_user_id"] = caller.user_id
        agr["fmv_benchmark_percentile"] = percentile
    else:
        agr["status"] = "DRAFT"
        agr["last_fmv_rejected_at"] = CLOCK.now_iso()
    touch("physician_agreements", agr)
    return success_object(agreement_out(agr))


@bp.post("/physician-agreements/<rid>/activate")
def activate_agreement(rid):
    authorized(["CompCommittee"])
    agr = require_path_resource("physician_agreements", rid)
    if agr["status"] != "FMV_APPROVED":
        raise_error(ERR_INVALID_STATE, "agreement activation requires status FMV_APPROVED")
    plan = db["comp_plans"].get(agr["plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise_error(ERR_PLAN_NOT_ACTIVE, "the referenced plan is not ACTIVE")
    # FMV freshness: logical clock must be no later than fmv_reviewed_at + 12 months
    reviewed = parse_iso_datetime(agr["fmv_reviewed_at"])
    if CLOCK.now() > add_months_dt(reviewed, 12):
        raise_error(ERR_FMV_STALE, "FMV review is older than 12 months")
    # FMV cap: base salary + projected annual productivity at current YTD pace
    phys = db["physicians"].get(agr["physician_id"])
    projected = projected_annual_productivity_cents(agr, plan, phys, CLOCK.today())
    if agr["base_salary_cents"] + projected > plan["fmv_cap_cents"]:
        raise_error(ERR_FMV_CAP_EXCEEDED,
                    "projected annual total compensation exceeds the plan FMV cap")
    agr["status"] = "EFFECTIVE"
    touch("physician_agreements", agr)
    return success_object(agreement_out(agr))


@bp.post("/physician-agreements/<rid>/terminate")
def terminate_agreement(rid):
    authorized(["CompCommittee"])
    agr = require_path_resource("physician_agreements", rid)
    if agr["status"] not in ("EFFECTIVE", "AMENDMENT_REQUIRED"):
        raise_error(ERR_INVALID_STATE,
                    "terminate requires status EFFECTIVE or AMENDMENT_REQUIRED")
    agr["status"] = "TERMINATED"
    touch("physician_agreements", agr)
    void_draft_statements(agr)
    return success_object(agreement_out(agr))


@bp.post("/physician-agreements/<rid>/repin")
def repin_agreement(rid):
    authorized(["CompAnalyst"])
    agr = require_path_resource("physician_agreements", rid)
    if agr["status"] != "AMENDMENT_REQUIRED":
        raise_error(ERR_INVALID_STATE, "repin requires status AMENDMENT_REQUIRED")
    successor = None
    for p in db["comp_plans"].values():
        if p["supersedes_plan_id"] == agr["plan_id"] and p["status"] == "ACTIVE":
            successor = p
            break
    if successor is None:
        raise_error(ERR_INVALID_STATE,
                    "no ACTIVE successor plan exists for this agreement's plan")
    agr["plan_id"] = successor["id"]
    agr["pinned_plan_version"] = successor["version"]
    agr["status"] = "EFFECTIVE"
    touch("physician_agreements", agr)
    return success_object(agreement_out(agr))
