"""Plan-of-care endpoints (PRD §3.3) plus cascade on hold/discharge."""

from flask import Blueprint, request

import errors
from errors import ApiError
from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_int
from services.common import new_record, touch, lookup, paginate, sorted_by_created
from services import serialize, engine

bp = Blueprint("plans", __name__)


@bp.route("/clinic/plans-of-care", methods=["POST"])
@require_roles("Evaluator")
def create_plan(user_id=None, role=None):
    body = get_body()
    child_id = require_str(body, "child_id")
    evaluation_id = require_str(body, "evaluation_id")
    primary_therapist_id = require_str(body, "primary_therapist_id")
    planned = require_int(body, "planned_weekly_minutes", minimum=0)
    # FK existence (PRD §2.5).
    lookup(db.children, child_id)
    evaluation = lookup(db.evaluations, evaluation_id)
    lookup(db.therapists, primary_therapist_id)
    rec = new_record({
        "child_id": child_id,
        "evaluation_id": evaluation_id,
        "primary_therapist_id": primary_therapist_id,
        # discipline copied from the source evaluation at creation.
        "discipline": evaluation["discipline"],
        "planned_weekly_minutes": planned,
        "goal_count": 0,
        "overall_progress_pct": 0,
        "status": "DRAFT",
    })
    db.plans_of_care[rec["id"]] = rec
    return success(serialize.plan_of_care(rec), status=201)


@bp.route("/clinic/plans-of-care", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plans(user_id=None, role=None):
    items = list(db.plans_of_care.values())
    for field in ("child_id", "evaluation_id", "primary_therapist_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p[field] == val]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.plan_of_care(p) for p in page], limit, offset, total)


@bp.route("/clinic/plans-of-care/<plan_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_plan(plan_id, user_id=None, role=None):
    rec = lookup(db.plans_of_care, plan_id)
    return success(serialize.plan_of_care(rec), status=200)


@bp.route("/clinic/plans-of-care/<plan_id>/activate", methods=["POST"])
@require_roles("Evaluator")
def activate_plan(plan_id, user_id=None, role=None):
    plan = lookup(db.plans_of_care, plan_id)
    therapist = db.therapists[plan["primary_therapist_id"]]
    if plan["status"] == "DRAFT":
        # Initial activation: source evaluation FINALIZED (not superseded),
        # therapist ACTIVE + discipline match, caseload < max.
        evaluation = db.evaluations[plan["evaluation_id"]]
        if evaluation["status"] != "FINALIZED":
            raise ApiError(errors.ERR_EVALUATION_NOT_FINALIZED, 409,
                           "Source evaluation is not FINALIZED.")
        if therapist["status"] != "ACTIVE" or therapist["discipline"] != plan["discipline"]:
            raise ApiError(errors.ERR_THERAPIST_DISCIPLINE_MISMATCH, 409,
                           "Primary therapist inactive or discipline mismatch.")
        if therapist["current_caseload"] >= therapist["max_caseload"]:
            raise ApiError(errors.ERR_CASELOAD_EXCEEDED, 409,
                           "Therapist caseload would be exceeded.")
        plan["status"] = "ACTIVE"
        touch(plan)
        therapist["current_caseload"] += 1
        touch(therapist)
        return success(serialize.plan_of_care(plan), status=200)
    elif plan["status"] == "ON_HOLD":
        # Re-activation: re-check caseload.
        if therapist["current_caseload"] >= therapist["max_caseload"]:
            raise ApiError(errors.ERR_CASELOAD_EXCEEDED, 409,
                           "Therapist caseload would be exceeded.")
        plan["status"] = "ACTIVE"
        touch(plan)
        therapist["current_caseload"] += 1
        touch(therapist)
        return success(serialize.plan_of_care(plan), status=200)
    else:
        # Not DRAFT and not ON_HOLD: initial activation precondition is the
        # mismatched one => ERR_PLAN_NOT_DRAFT.
        raise ApiError(errors.ERR_PLAN_NOT_DRAFT, 409,
                       "Plan must be DRAFT or ON_HOLD to activate.")


@bp.route("/clinic/plans-of-care/<plan_id>/hold", methods=["POST"])
@require_roles("Therapist")
def hold_plan(plan_id, user_id=None, role=None):
    plan = lookup(db.plans_of_care, plan_id)
    if plan["status"] != "ACTIVE":
        raise ApiError(errors.ERR_PLAN_NOT_ACTIVE, 409, "Plan must be ACTIVE to hold.")
    therapist = db.therapists[plan["primary_therapist_id"]]
    plan["status"] = "ON_HOLD"
    touch(plan)
    # Slot freed while on hold.
    therapist["current_caseload"] -= 1
    touch(therapist)
    # Cascade: cancel this plan's SCHEDULED appointments (release + promote).
    _cancel_plan_appointments(plan_id)
    return success(serialize.plan_of_care(plan), status=200)


@bp.route("/clinic/plans-of-care/<plan_id>/discharge", methods=["POST"])
@require_roles("Evaluator")
def discharge_plan(plan_id, user_id=None, role=None):
    plan = lookup(db.plans_of_care, plan_id)
    if plan["status"] not in ("ACTIVE", "ON_HOLD"):
        raise ApiError(errors.ERR_PLAN_NOT_DISCHARGEABLE, 409,
                       "Plan must be ACTIVE or ON_HOLD to discharge.")
    was_active = plan["status"] == "ACTIVE"
    therapist = db.therapists[plan["primary_therapist_id"]]
    plan["status"] = "DISCHARGED"
    touch(plan)
    if was_active:
        therapist["current_caseload"] -= 1
        touch(therapist)
    # Cascade: cancel SCHEDULED appointments (release + promote).
    _cancel_plan_appointments(plan_id)
    # Cascade: cancel ASSIGNED/ACTIVE home programs under this plan.
    for hp in db.home_programs.values():
        if hp["plan_of_care_id"] == plan_id and hp["status"] in ("ASSIGNED", "ACTIVE"):
            hp["status"] = "CANCELLED"
            touch(hp)
    return success(serialize.plan_of_care(plan), status=200)


def _cancel_plan_appointments(plan_id):
    """Cancel every SCHEDULED appointment of a plan; each release + waitlist promote."""
    # Snapshot ids so mutation during iteration is safe.
    appt_ids = [
        a["id"]
        for a in db.appointments.values()
        if a["plan_of_care_id"] == plan_id and a["status"] == "SCHEDULED"
    ]
    for appt_id in appt_ids:
        appt = db.appointments[appt_id]
        appt["status"] = "CANCELLED"
        touch(appt)
        auth = db.authorizations[appt["authorization_id"]]
        engine.reconcile_authorization(auth)
        child = db.children.get(appt["child_id"])
        if child is not None:
            engine.recompute_child(child)
        # Waitlist promotion on the freed therapist slot.
        engine.run_waitlist_promotion(appt["therapist_id"])
