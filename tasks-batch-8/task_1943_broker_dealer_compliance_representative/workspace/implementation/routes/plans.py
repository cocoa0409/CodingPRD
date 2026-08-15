"""HeightenedSupervisionPlan endpoints (PRD 3.7): half-open windows, OCC on rep."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_PLAN_ALREADY_ACTIVE,
    ERR_PLAN_NOT_ACTIVE,
    ERR_PLAN_START_IN_PAST,
    ERR_PLAN_WINDOW_OVERLAP,
    ERR_REP_NOT_STATUTORILY_DISQUALIFIED,
    ERR_STALE_REPRESENTATIVE_VERSION,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from util import parse_date, today
from validate import (
    get_body, opt_version, req_date, require_path_resource, require_ref,
    req_str_list, soft_date, soft_int,
)

bp = Blueprint("plans", __name__)


@bp.post("/supervision-plans")
def create_plan():
    authorized(["CompliancePrincipal"])
    body = get_body()
    # Priority 3: FK existence
    rep = require_ref("representatives", body.get("rep_id"), "rep_id")
    # Priority 3.5: OCC on RegisteredRepresentative.version
    expected = body.get("expected_representative_version")
    if rep is not None and soft_int(expected) and expected != rep["version"]:
        raise_error(ERR_STALE_REPRESENTATIVE_VERSION,
                    "expected_representative_version does not match the rep's current "
                    "version")

    start_raw = body.get("start_date")
    end_raw = body.get("end_date")
    if rep is not None:
        # Priority 6: temporal — start_date must not be before the current date
        if soft_date(start_raw) and parse_date(start_raw) < today():
            raise_error(ERR_PLAN_START_IN_PAST,
                        "plan start_date is before the current clock date")
        # Priority 7: half-open [start_date, end_date) windows of the rep's
        # DRAFT/ACTIVE plans must not overlap; touching endpoints are allowed
        if soft_date(start_raw) and soft_date(end_raw):
            new_start = parse_date(start_raw)
            new_end = parse_date(end_raw)
            for p in db["supervision_plans"].values():
                if p["rep_id"] != rep["id"] or p["status"] not in ("DRAFT", "ACTIVE"):
                    continue
                if new_start < parse_date(p["end_date"]) and parse_date(p["start_date"]) < new_end:
                    raise_error(ERR_PLAN_WINDOW_OVERLAP,
                                "plan window overlaps another DRAFT/ACTIVE plan of the rep")

    # Priority 8: schema
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    conditions = req_str_list(body, "conditions", non_empty=True)
    opt_version(body, "expected_representative_version")
    if rep is None:
        raise_error(ERR_VALIDATION, "missing or invalid field: rep_id")

    rec = new_record("supervision_plans", {
        "rep_id": rep["id"],
        "start_date": start_date,
        "end_date": end_date,
        "conditions": conditions,
        "terminated_reason": None,
        "status": "DRAFT",
    })
    touch(rep)  # plan registration pins a rep version bump
    return success_object(public(rec), status=201)


@bp.get("/supervision-plans")
def list_plans():
    return list_response("supervision_plans", filters={
        "rep_id": request.args.get("rep_id"),
        "status": request.args.get("status"),
    })


@bp.get("/supervision-plans/<rid>")
def get_plan(rid):
    return get_one("supervision_plans", rid)


@bp.post("/supervision-plans/<rid>/activate")
def activate_plan(rid):
    authorized(["CompliancePrincipal"])
    plan = require_path_resource("supervision_plans", rid)
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_NOT_ACTIVE, "activate is allowed only from DRAFT")
    rep = db["representatives"].get(plan["rep_id"])
    if rep is None or not rep["is_statutorily_disqualified"]:
        raise_error(ERR_REP_NOT_STATUTORILY_DISQUALIFIED,
                    "activation requires the rep to be statutorily disqualified")
    for p in db["supervision_plans"].values():
        if p["rep_id"] == plan["rep_id"] and p["status"] == "ACTIVE":
            raise_error(ERR_PLAN_ALREADY_ACTIVE,
                        "another plan of the same rep is already ACTIVE")
    plan["status"] = "ACTIVE"
    touch(plan)
    return success_object(public(plan))


@bp.post("/supervision-plans/<rid>/terminate")
def terminate_plan(rid):
    authorized(["CompliancePrincipal"])
    plan = require_path_resource("supervision_plans", rid)
    if plan["status"] != "ACTIVE":
        raise_error(ERR_PLAN_NOT_ACTIVE, "terminate is allowed only from ACTIVE")
    plan["status"] = "TERMINATED"
    plan["terminated_reason"] = "MANUAL"
    touch(plan)
    return success_object(public(plan))
