"""Coordination-plan endpoints (PRD §3.7)."""

from flask import Blueprint

import errors
from errors import ApiError
from db import db
from response import success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_enum, require_iso_datetime
from services.common import new_record, touch, lookup
from services import serialize, engine

bp = Blueprint("coordination_plans", __name__)


@bp.route("/clinic/coordination-plans", methods=["POST"])
@require_roles("ClinicAdmin")
def create_coordination_plan(user_id=None, role=None):
    body = get_body()
    child_id = require_str(body, "child_id")
    plan_type = require_enum(body, "plan_type", {"IFSP", "IEP"})
    jurisdiction = require_str(body, "jurisdiction")
    review_due = require_iso_datetime(body, "review_due_time")
    lookup(db.children, child_id)
    from clock import format_iso
    rec = new_record({
        "child_id": child_id,
        "plan_type": plan_type,
        "jurisdiction": jurisdiction,
        "review_due_time": format_iso(review_due),
        "status": "DRAFT",
    })
    db.coordination_plans[rec["id"]] = rec
    return success(serialize.coordination_plan(rec), status=201)


@bp.route("/clinic/coordination-plans/<coordination_plan_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_coordination_plan(coordination_plan_id, user_id=None, role=None):
    rec = lookup(db.coordination_plans, coordination_plan_id)
    return success(serialize.coordination_plan(rec), status=200)


@bp.route("/clinic/coordination-plans/<coordination_plan_id>/activate", methods=["POST"])
@require_roles("ClinicAdmin")
def activate(coordination_plan_id, user_id=None, role=None):
    cp = lookup(db.coordination_plans, coordination_plan_id)
    if cp["status"] != "DRAFT":
        raise ApiError(errors.ERR_COORDINATION_NOT_DRAFT, 409,
                       "Coordination plan must be DRAFT to activate.")
    # Child has no other ACTIVE or TRANSITIONING coordination plan.
    for other in db.coordination_plans.values():
        if (
            other["id"] != cp["id"]
            and other["child_id"] == cp["child_id"]
            and other["status"] in ("ACTIVE", "TRANSITIONING")
        ):
            raise ApiError(errors.ERR_COORDINATION_CONFLICT, 409,
                           "Child already has an ACTIVE or TRANSITIONING coordination plan.")
    child = db.children[cp["child_id"]]
    # IFSP age eligibility: age_months_at_intake < 36.
    if cp["plan_type"] == "IFSP" and child["age_months_at_intake"] >= 36:
        raise ApiError(errors.ERR_IFSP_AGE_INELIGIBLE, 409,
                       "Child is too old for an IFSP plan.")
    cp["status"] = "ACTIVE"
    touch(cp)
    # Child.coordination_program set; recompute derives it.
    engine.recompute_child(child)
    return success(serialize.coordination_plan(cp), status=200)


@bp.route("/clinic/coordination-plans/<coordination_plan_id>/begin-transition", methods=["POST"])
@require_roles("ClinicAdmin")
def begin_transition(coordination_plan_id, user_id=None, role=None):
    cp = lookup(db.coordination_plans, coordination_plan_id)
    if cp["status"] != "ACTIVE":
        raise ApiError(errors.ERR_COORDINATION_NOT_ACTIVE, 409,
                       "Coordination plan must be ACTIVE to begin transition.")
    if cp["plan_type"] != "IFSP":
        raise ApiError(errors.ERR_TRANSITION_NOT_APPLICABLE, 409,
                       "Only IFSP plans transition to school.")
    cp["status"] = "TRANSITIONING"
    touch(cp)
    # Child.coordination_program remains EARLY_INTERVENTION; recompute confirms.
    engine.recompute_child(db.children[cp["child_id"]])
    return success(serialize.coordination_plan(cp), status=200)


@bp.route("/clinic/coordination-plans/<coordination_plan_id>/close", methods=["POST"])
@require_roles("ClinicAdmin")
def close(coordination_plan_id, user_id=None, role=None):
    cp = lookup(db.coordination_plans, coordination_plan_id)
    if cp["status"] not in ("ACTIVE", "TRANSITIONING"):
        raise ApiError(errors.ERR_COORDINATION_NOT_CLOSEABLE, 409,
                       "Coordination plan must be ACTIVE or TRANSITIONING to close.")
    cp["status"] = "CLOSED"
    touch(cp)
    # If no other ACTIVE/TRANSITIONING plan for the child, program resets to NONE.
    engine.recompute_child(db.children[cp["child_id"]])
    return success(serialize.coordination_plan(cp), status=200)
