"""Case plan routes (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import response
from services import compute, serialize

bp = Blueprint("case_plans", __name__)


def _held_hearing_of_type(case_id, hearing_type):
    for h in db.hearings.values():
        if h["case_id"] == case_id and h["hearing_type"] == hearing_type and h["status"] == "HELD":
            return True
    return False


@bp.route("/case-plans", methods=["POST"])
def create_case_plan():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    body = helpers.get_body()
    case_id = helpers.require_str(body, "case_id")
    required_visits = helpers.require_int(body, "required_visits_per_month")
    objectives_total = helpers.require_int(body, "objectives_total")
    case = db.cases.get(case_id)
    if case is None:
        raise errors.not_found("Case not found.")
    if required_visits < 0 or required_visits > 12:
        raise errors.validation_limit("required_visits_per_month must be between 0 and 12.")
    if objectives_total < 1:
        raise errors.validation_limit("objectives_total must be at least 1.")
    record = {
        "case_id": case_id,
        "status": "DRAFT",
        "required_visits_per_month": required_visits,
        "objectives_total": objectives_total,
        "objectives_met": 0,
        "compliance_pct": 0.0,
    }
    db.stamp_create(record)
    db.case_plans[record["id"]] = record
    return response.success(serialize.case_plan(record), 201)


@bp.route("/case-plans/<pid>", methods=["GET"])
def get_case_plan(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Judge"})
    record = db.case_plans.get(pid)
    if record is None:
        raise errors.not_found("Case plan not found.")
    return response.success(serialize.case_plan(record), 200)


@bp.route("/case-plans", methods=["GET"])
def list_case_plans():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Judge"})
    limit, offset = helpers.pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    records = list(db.case_plans.values())
    if case_id is not None:
        records = [r for r in records if r["case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.case_plan(r) for r in page], limit, offset, total)


@bp.route("/case-plans/<pid>/objectives", methods=["POST"])
def update_objectives(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.case_plans.get(pid)
    if record is None:
        raise errors.not_found("Case plan not found.")
    body = helpers.get_body()
    objectives_met = helpers.require_int(body, "objectives_met")
    # Clamp to [0, objectives_total].
    clamped = max(0, min(objectives_met, record["objectives_total"]))
    record["objectives_met"] = clamped
    record["compliance_pct"] = compute.plan_compliance_pct(clamped, record["objectives_total"])
    db.bump(record)
    return response.success(serialize.case_plan(record), 200)


@bp.route("/case-plans/<pid>/activate", methods=["POST"])
def activate_plan(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.case_plans.get(pid)
    if record is None:
        raise errors.not_found("Case plan not found.")
    if record["status"] not in ("DRAFT", "REVISION"):
        raise errors.invalid_state("Case plan is not DRAFT or REVISION.")
    # A DRAFT requires a HELD DISPOSITION hearing; the REVISION cycle does not.
    if record["status"] == "DRAFT":
        if not _held_hearing_of_type(record["case_id"], "DISPOSITION"):
            raise errors.hearing_prereq_missing("A HELD DISPOSITION hearing is required to activate a DRAFT plan.")
    record["status"] = "ACTIVE"
    db.bump(record)
    return response.success(serialize.case_plan(record), 200)


@bp.route("/case-plans/<pid>/revise", methods=["POST"])
def revise_plan(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.case_plans.get(pid)
    if record is None:
        raise errors.not_found("Case plan not found.")
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Case plan is not ACTIVE.")
    record["status"] = "REVISION"
    db.bump(record)
    return response.success(serialize.case_plan(record), 200)


@bp.route("/case-plans/<pid>/complete", methods=["POST"])
def complete_plan(pid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.case_plans.get(pid)
    if record is None:
        raise errors.not_found("Case plan not found.")
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Case plan is not ACTIVE.")
    if record["compliance_pct"] < compute.PLAN_COMPLETE_COMPLIANCE:
        raise errors.plan_not_complete("compliance_pct must be at least 100 to complete.")
    record["status"] = "COMPLETED"
    db.bump(record)
    return response.success(serialize.case_plan(record), 200)
