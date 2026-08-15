"""PlanChangeRequest endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_NOT_OWN_RESOURCE, ERR_STALE_VERSION, ERR_SUCCESSOR_MISMATCH,
    ERR_PCR_TIMING, ERR_ACK_INCOMPLETE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public
from services.ledger import compute_modeled_delta
from util import CLOCK, parse_date_strict
from validate import (
    get_body, req_str, req_int, req_date, require_path_resource, require_body_ref,
)

bp = Blueprint("pcrs", __name__)

PCR_READ_ROLES = ["CompAnalyst", "CompCommittee", "Physician"]
WITHDRAWABLE = ("PROPOSED", "MODELED", "COMMUNICATED")


def _is_enrolled(physician_id, plan_id):
    return any(a for a in db["physician_agreements"].values()
               if a["physician_id"] == physician_id and a["plan_id"] == plan_id)


def _check_pcr_read_ownership(caller, pcr):
    if caller.role == "Physician" and not _is_enrolled(caller.user_id, pcr["plan_id"]):
        raise_error(ERR_NOT_OWN_RESOURCE,
                    "a Physician may read plan changes only for plans it is enrolled in")


@bp.post("/plan-change-requests")
def create_pcr():
    authorized(["CompAnalyst"])
    body = get_body()
    # Priority 4: body FK existence
    plan_id = body.get("plan_id")
    successor_plan_id = body.get("successor_plan_id")
    plan = require_body_ref("comp_plans", plan_id, "plan_id")
    succ = require_body_ref("comp_plans", successor_plan_id, "successor_plan_id")
    # Priority 5: proposing is allowed only against an ACTIVE plan (PRD 3.9)
    if plan is not None and plan["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "plan-change requests target an ACTIVE plan")
    # Priority 14: payload shape
    if not isinstance(plan_id, str) or not plan_id:
        raise_error(ERR_VALIDATION, "missing or invalid field: plan_id")
    if not isinstance(successor_plan_id, str) or not successor_plan_id:
        raise_error(ERR_VALIDATION, "missing or invalid field: successor_plan_id")
    effective_date = req_date(body, "effective_date")
    summary = req_str(body, "summary")
    expected = req_int(body, "expected_comp_plan_version")
    # OCC (concurrency rule pcr-create-stale-plan)
    if expected != plan["version"]:
        raise_error(ERR_STALE_VERSION, "plan version has advanced since it was observed")
    # Priority 24: successor linkage
    if succ["supersedes_plan_id"] != plan["id"] or succ["status"] != "FMV_APPROVED":
        raise_error(ERR_SUCCESSOR_MISMATCH,
                    "successor plan must be FMV_APPROVED with supersedes_plan_id == plan_id")
    # Create-with-supersede: withdraw existing PROPOSED/MODELED PCRs for the plan
    for other in db["plan_change_requests"].values():
        if other["plan_id"] == plan["id"] and other["status"] in ("PROPOSED", "MODELED"):
            other["status"] = "WITHDRAWN"
            touch("plan_change_requests", other)
    touch("comp_plans", plan)
    rec = new_record("plan_change_requests", {
        "plan_id": plan["id"],
        "successor_plan_id": succ["id"],
        "effective_date": effective_date,
        "summary": summary,
        "status": "PROPOSED",
        "modeled_delta_cents": None,
        "acknowledged_physician_ids": [],
    })
    return success_object(public(rec), status=201)


@bp.get("/comp-plans/<rid>/plan-change-requests")
def list_plan_pcrs(rid):
    caller = authorized(PCR_READ_ROLES)
    plan = db["comp_plans"].get(rid)
    if plan is not None and caller.role == "Physician" and not _is_enrolled(caller.user_id, rid):
        raise_error(ERR_NOT_OWN_RESOURCE,
                    "a Physician may read plan changes only for plans it is enrolled in")
    if plan is None:
        raise_error(ERR_NOT_FOUND, f"plan not found: {rid}")
    filters = {"plan_id": rid, "status": request.args.get("status")}
    return list_response("plan_change_requests", filters)


@bp.get("/plan-change-requests/<rid>")
def get_pcr(rid):
    caller = authorized(PCR_READ_ROLES)
    rec = db["plan_change_requests"].get(rid)
    if rec is not None:
        _check_pcr_read_ownership(caller, rec)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"plan-change request not found: {rid}")
    return success_object(public(rec))


@bp.post("/plan-change-requests/<rid>/model")
def model_pcr(rid):
    authorized(["CompAnalyst"])
    pcr = require_path_resource("plan_change_requests", rid)
    if pcr["status"] not in ("PROPOSED", "COMMUNICATED"):
        raise_error(ERR_INVALID_STATE, "model requires status PROPOSED or COMMUNICATED")
    pcr["modeled_delta_cents"] = compute_modeled_delta(pcr)
    if pcr["status"] == "COMMUNICATED":
        # Entering MODELED from COMMUNICATED invalidates acknowledgments
        pcr["acknowledged_physician_ids"] = []
    pcr["status"] = "MODELED"
    touch("plan_change_requests", pcr)
    return success_object(public(pcr))


@bp.post("/plan-change-requests/<rid>/communicate")
def communicate_pcr(rid):
    authorized(["CompAnalyst"])
    pcr = require_path_resource("plan_change_requests", rid)
    if pcr["status"] != "MODELED":
        raise_error(ERR_INVALID_STATE, "communicate requires status MODELED")
    if not (parse_date_strict(pcr["effective_date"]) > CLOCK.today()):
        raise_error(ERR_PCR_TIMING,
                    "communicate requires effective_date strictly after the current date")
    pcr["status"] = "COMMUNICATED"
    touch("plan_change_requests", pcr)
    return success_object(public(pcr))


@bp.post("/plan-change-requests/<rid>/revise")
def revise_pcr(rid):
    authorized(["CompAnalyst"])
    pcr = require_path_resource("plan_change_requests", rid)
    if pcr["status"] != "COMMUNICATED":
        raise_error(ERR_INVALID_STATE, "revise requires status COMMUNICATED")
    pcr["acknowledged_physician_ids"] = []
    pcr["modeled_delta_cents"] = compute_modeled_delta(pcr)
    pcr["status"] = "MODELED"
    touch("plan_change_requests", pcr)
    return success_object(public(pcr))


@bp.post("/plan-change-requests/<rid>/acknowledge")
def acknowledge_pcr(rid):
    caller = authorized(["Physician"])
    pcr = require_path_resource("plan_change_requests", rid)
    # Ownership: the acting physician must hold an EFFECTIVE agreement on the plan
    enrolled = any(
        a for a in db["physician_agreements"].values()
        if a["physician_id"] == caller.user_id and a["plan_id"] == pcr["plan_id"]
        and a["status"] == "EFFECTIVE"
    )
    if not enrolled:
        raise_error(ERR_NOT_OWN_RESOURCE,
                    "physician does not hold an EFFECTIVE agreement on this plan")
    if pcr["status"] != "COMMUNICATED":
        raise_error(ERR_INVALID_STATE, "acknowledge requires status COMMUNICATED")
    if caller.user_id in pcr["acknowledged_physician_ids"]:
        raise_error(ERR_INVALID_STATE, "physician has already acknowledged this change")
    pcr["acknowledged_physician_ids"].append(caller.user_id)
    touch("plan_change_requests", pcr)
    return success_object(public(pcr))


@bp.post("/plan-change-requests/<rid>/activate")
def activate_pcr(rid):
    authorized(["CompCommittee"])
    pcr = require_path_resource("plan_change_requests", rid)
    if pcr["status"] != "COMMUNICATED":
        raise_error(ERR_INVALID_STATE, "activate requires status COMMUNICATED")
    # PRD 3.9 ordering: timing, then acknowledgment completeness, then successor
    if CLOCK.today() < parse_date_strict(pcr["effective_date"]):
        raise_error(ERR_PCR_TIMING, "the effective_date has not been reached")
    acked = set(pcr["acknowledged_physician_ids"])
    for a in db["physician_agreements"].values():
        if a["plan_id"] == pcr["plan_id"] and a["status"] == "EFFECTIVE":
            if a["physician_id"] not in acked:
                raise_error(ERR_ACK_INCOMPLETE,
                            "every EFFECTIVE physician on the plan must acknowledge first")
    succ = db["comp_plans"][pcr["successor_plan_id"]]
    if succ["status"] != "FMV_APPROVED":
        raise_error(ERR_SUCCESSOR_MISMATCH, "successor plan is no longer FMV_APPROVED")
    plan = db["comp_plans"][pcr["plan_id"]]
    # Succession cascade (PRD 3.9): the request, both plans, and every touched
    # agreement increment their versions. The successor additionally undergoes
    # its own FMV_APPROVED -> ACTIVE lifecycle transition (activated_at stamp
    # plus that transition's version increment), so it advances by 2 in total.
    pcr["status"] = "EFFECTIVE"
    touch("plan_change_requests", pcr)
    succ["status"] = "ACTIVE"
    succ["activated_at"] = CLOCK.now_iso()
    succ["version"] += 1  # FMV_APPROVED -> ACTIVE transition increment
    touch("comp_plans", succ)  # operation-level increment (both plans)
    plan["status"] = "SUPERSEDED"
    touch("comp_plans", plan)
    for a in db["physician_agreements"].values():
        if a["plan_id"] == plan["id"] and a["status"] == "EFFECTIVE":
            a["status"] = "AMENDMENT_REQUIRED"
            touch("physician_agreements", a)
            for s in db["comp_statements"].values():
                if s["agreement_id"] == a["id"] and s["status"] == "DRAFT":
                    s["status"] = "VOIDED"
                    touch("comp_statements", s)
    return success_object(public(pcr))


@bp.post("/plan-change-requests/<rid>/withdraw")
def withdraw_pcr(rid):
    authorized(["CompAnalyst"])
    pcr = require_path_resource("plan_change_requests", rid)
    if pcr["status"] not in WITHDRAWABLE:
        raise_error(ERR_INVALID_STATE,
                    "withdraw requires status PROPOSED, MODELED, or COMMUNICATED")
    pcr["status"] = "WITHDRAWN"
    touch("plan_change_requests", pcr)
    return success_object(public(pcr))
