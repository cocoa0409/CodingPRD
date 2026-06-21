"""Child routes (PRD §3.3, §3.8 trial visit, §3.10 aging out)."""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import middleware
import response
from services import compute, serialize

bp = Blueprint("children", __name__)


def _case_plan_for(case_id):
    for p in db.case_plans.values():
        if p["case_id"] == case_id:
            return p
    return None


@bp.route("/children", methods=["POST"])
def create_child():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    body = helpers.get_body()
    case_id = helpers.require_str(body, "case_id")
    full_name = helpers.require_str(body, "full_name")
    dob = helpers.require_dt(body, "date_of_birth")
    case = db.cases.get(case_id)
    if case is None:
        raise errors.not_found("Case not found.")
    record = {
        "case_id": case_id,
        "full_name": full_name,
        "date_of_birth": clock.iso(dob),
        "status": "IN_HOME",
        "current_placement_id": None,
    }
    db.stamp_create(record)
    db.children[record["id"]] = record
    return response.success(serialize.child(record), 201)


@bp.route("/children/<cid>", methods=["GET"])
def get_child(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Judge"})
    record = db.children.get(cid)
    if record is None:
        raise errors.not_found("Child not found.")
    return response.success(serialize.child(record), 200)


@bp.route("/children", methods=["GET"])
def list_children():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Judge"})
    limit, offset = helpers.pagination()
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    current_placement_id = request.args.get("current_placement_id")
    records = list(db.children.values())
    if case_id is not None:
        records = [r for r in records if r["case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if current_placement_id is not None:
        records = [r for r in records if r.get("current_placement_id") == current_placement_id]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.child(r) for r in page], limit, offset, total)


@bp.route("/children/<cid>/trial-home-visit", methods=["POST"])
def trial_home_visit(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.children.get(cid)
    if record is None:
        raise errors.not_found("Child not found.")
    if record["status"] != "PLACED":
        raise errors.invalid_state("Child is not PLACED.")
    case = db.cases.get(record["case_id"])
    if case is None or case["permanency_goal"] != "REUNIFICATION":
        raise errors.goal_mismatch("Case permanency_goal must be REUNIFICATION for a trial home visit.")
    plan = _case_plan_for(record["case_id"])
    compliance = plan["compliance_pct"] if plan is not None else 0
    if compliance < compute.TRIAL_VISIT_COMPLIANCE:
        raise errors.plan_not_complete("CasePlan compliance must be at least 80 for a trial home visit.")
    record["status"] = "TRIAL_HOME_VISIT"
    db.bump(record)
    return response.success(serialize.child(record), 200)


@bp.route("/children/<cid>/revoke-trial", methods=["POST"])
def revoke_trial(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.children.get(cid)
    if record is None:
        raise errors.not_found("Child not found.")
    if record["status"] != "TRIAL_HOME_VISIT":
        raise errors.invalid_state("Child is not in TRIAL_HOME_VISIT.")
    record["status"] = "PLACED"
    db.bump(record)
    return response.success(serialize.child(record), 200)


@bp.route("/children/<cid>/age-out", methods=["POST"])
def age_out(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.children.get(cid)
    if record is None:
        raise errors.not_found("Child not found.")
    if record["status"] not in ("PLACED", "TRIAL_HOME_VISIT"):
        raise errors.invalid_state("Child must be PLACED or in TRIAL_HOME_VISIT to age out.")
    if compute.age_years(record) < compute.AGING_OUT_AGE:
        raise errors.age_not_eligible("Child is below aging-out age (18).")
    # Cascade: if the child holds an ACTIVE placement, disrupt it and release the bed.
    placement_id = record.get("current_placement_id")
    if placement_id is not None:
        placement = db.placements.get(placement_id)
        if placement is not None and placement["status"] == "ACTIVE":
            placement["status"] = "DISRUPTED"
            placement["end_at"] = clock.iso(clock.now())
            db.bump(placement)
            # active_placement_count is computed on read; no stored counter to decrement.
    record["status"] = "AGED_OUT"
    record["current_placement_id"] = None
    db.bump(record)
    return response.success(serialize.child(record), 200)
