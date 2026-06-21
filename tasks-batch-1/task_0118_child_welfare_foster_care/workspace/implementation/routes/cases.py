"""Case routes (PRD §3.3, §3.6, §3.9)."""
from flask import Blueprint, request

import clock
import db
import errors
import helpers
import middleware
import response
from services import compute, serialize

bp = Blueprint("cases", __name__)


def _held_hearing_of_type(case_id, hearing_type):
    for h in db.hearings.values():
        if h["case_id"] == case_id and h["hearing_type"] == hearing_type and h["status"] == "HELD":
            return h
    return None


def _held_tpr_terminated(case_id):
    for h in db.hearings.values():
        if (h["case_id"] == case_id and h["hearing_type"] == "TPR"
                and h["status"] == "HELD" and h.get("ruling") == "TERMINATE_RIGHTS"):
            return h
    return None


def _case_plan_for(case_id):
    for p in db.case_plans.values():
        if p["case_id"] == case_id:
            return p
    return None


@bp.route("/cases", methods=["POST"])
def create_case():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    body = helpers.get_body()
    investigation_id = helpers.require_str(body, "investigation_id")
    investigation = db.investigations.get(investigation_id)
    if investigation is None:
        raise errors.not_found("Investigation not found.")
    # A case opens only from UNSAFE or CONDITIONALLY_SAFE.
    if investigation["status"] not in ("UNSAFE", "CONDITIONALLY_SAFE"):
        raise errors.investigation_not_removal()

    record = {
        "investigation_id": investigation_id,
        "status": "OPEN",
        "removal_date": None,
        "permanency_goal": "REUNIFICATION",
    }
    db.stamp_create(record)
    db.cases[record["id"]] = record

    # Bubble-up: mark the originating referral LINKED.
    referral = db.referrals.get(investigation["referral_id"])
    if referral is not None and referral["status"] == "SCREENED_IN":
        referral["linked_case_id"] = record["id"]
        referral["status"] = "LINKED"
        db.bump(referral)

    return response.success(serialize.case(record), 201)


@bp.route("/cases/<cid>", methods=["GET"])
def get_case(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Judge"})
    record = db.cases.get(cid)
    if record is None:
        raise errors.not_found("Case not found.")
    # months_in_care / tpr_clock_breached are recomputed on read by serialize.case.
    return response.success(serialize.case(record), 200)


@bp.route("/cases", methods=["GET"])
def list_cases():
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Admin", "Caseworker", "Judge"})
    limit, offset = helpers.pagination()
    status = request.args.get("status")
    permanency_goal = request.args.get("permanency_goal")
    investigation_id = request.args.get("investigation_id")
    records = list(db.cases.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if permanency_goal is not None:
        records = [r for r in records if r["permanency_goal"] == permanency_goal]
    if investigation_id is not None:
        records = [r for r in records if r["investigation_id"] == investigation_id]
    page, total = helpers.paginate(records, limit, offset)
    return response.list_success([serialize.case(r) for r in page], limit, offset, total)


@bp.route("/cases/<cid>/recompute-clock", methods=["POST"])
def recompute_clock(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.cases.get(cid)
    if record is None:
        raise errors.not_found("Case not found.")
    # Persist the computed values. (Computed fields are also derived on read;
    # this endpoint explicitly recomputes and persists against the current clock.)
    # months_in_care/tpr_clock_breached are not stored scalar fields — they are
    # always derived — so this is a no-op beyond returning the freshly derived
    # projection, which honours "recompute and persist against the current clock".
    return response.success(serialize.case(record), 200)


@bp.route("/cases/<cid>/advance-permanency", methods=["POST"])
def advance_permanency(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.cases.get(cid)
    if record is None:
        raise errors.not_found("Case not found.")
    if record["status"] != "IN_PLACEMENT":
        raise errors.invalid_state("Case is not IN_PLACEMENT.")
    # Requires a HELD PERMANENCY hearing on this case.
    if _held_hearing_of_type(cid, "PERMANENCY") is None:
        raise errors.hearing_prereq_missing("A HELD PERMANENCY hearing is required.")
    record["status"] = "PERMANENCY_PLANNING"
    db.bump(record)
    return response.success(serialize.case(record), 200)


def _children_of_case(case_id):
    return [c for c in db.children.values() if c["case_id"] == case_id]


def _drive_children_permanent(case_id):
    """Cascade: children in {PLACED, TRIAL_HOME_VISIT} -> PERMANENT."""
    for child in _children_of_case(case_id):
        if child["status"] in ("PLACED", "TRIAL_HOME_VISIT"):
            child["status"] = "PERMANENT"
            db.bump(child)


@bp.route("/cases/<cid>/close", methods=["POST"])
def close_case(cid):
    _, role = middleware.authenticate()
    middleware.authorize(role, {"Caseworker"})
    record = db.cases.get(cid)
    if record is None:
        raise errors.not_found("Case not found.")
    if record["status"] != "PERMANENCY_PLANNING":
        raise errors.invalid_state("Case is not in PERMANENCY_PLANNING.")

    goal = record["permanency_goal"]
    plan = _case_plan_for(cid)

    if goal == "REUNIFICATION":
        if plan is None or plan["status"] != "COMPLETED":
            raise errors.plan_not_complete("CasePlan must be COMPLETED for reunification close.")
        # The child's active placement (if any) must have ended ENDED_REUNIFIED;
        # a still-ACTIVE placement blocks the close as an invalid-state precondition.
        for child in _children_of_case(cid):
            for p in db.placements.values():
                if p["child_id"] == child["id"] and p["status"] == "ACTIVE":
                    raise errors.invalid_state("Child still has an ACTIVE placement; end it to ENDED_REUNIFIED first.")
        new_status = "CLOSED_REUNIFIED"
    elif goal == "ADOPTION":
        if _held_tpr_terminated(cid) is None:
            raise errors.tpr_not_terminated()
        new_status = "CLOSED_ADOPTED"
    elif goal == "APPLA":
        children = _children_of_case(cid)
        # APPLA close requires the child's age_years >= 16.
        eligible = any(compute.age_years(c) >= compute.APPLA_MIN_AGE for c in children)
        if not eligible:
            raise errors.age_not_eligible("Child must be at least 16 for APPLA close.")
        new_status = "CLOSED_APPLA"
    else:
        raise errors.goal_mismatch()

    record["status"] = new_status
    db.bump(record)
    _drive_children_permanent(cid)
    return response.success(serialize.case(record), 200)
