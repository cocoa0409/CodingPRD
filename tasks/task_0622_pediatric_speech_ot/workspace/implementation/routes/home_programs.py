"""Home-program endpoints (PRD §3.9)."""

from flask import Blueprint, request

import errors
from errors import ApiError
from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_int, optional_bool
from services.common import new_record, touch, lookup, paginate, sorted_by_created
from services import serialize

bp = Blueprint("home_programs", __name__)


@bp.route("/clinic/plans-of-care/<plan_id>/home-programs", methods=["POST"])
@require_roles("Therapist")
def assign(plan_id, user_id=None, role=None):
    lookup(db.plans_of_care, plan_id)
    body = get_body()
    title = require_str(body, "title")
    weekly_target = require_int(body, "weekly_target_sessions", minimum=1)
    parent_done = optional_bool(body, "parent_training_completed", default=False)
    rec = new_record({
        "plan_of_care_id": plan_id,
        "assigned_by_therapist_id": user_id,  # X-User-ID of the Therapist.
        "title": title,
        "weekly_target_sessions": weekly_target,
        "parent_training_completed": parent_done,
        "status": "ASSIGNED",
    })
    db.home_programs[rec["id"]] = rec
    return success(serialize.home_program(rec), status=201)


@bp.route("/clinic/home-programs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_home_programs(user_id=None, role=None):
    items = list(db.home_programs.values())
    for field in ("plan_of_care_id", "assigned_by_therapist_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [h for h in items if h[field] == val]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.home_program(h) for h in page], limit, offset, total)


@bp.route("/clinic/home-programs/<home_program_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_home_program(home_program_id, user_id=None, role=None):
    rec = lookup(db.home_programs, home_program_id)
    return success(serialize.home_program(rec), status=200)


@bp.route("/clinic/home-programs/<home_program_id>/activate", methods=["POST"])
@require_roles("Therapist")
def activate(home_program_id, user_id=None, role=None):
    hp = lookup(db.home_programs, home_program_id)
    body = get_body()
    # If parent_training_completed provided true, set it first, before the
    # training-complete precondition is evaluated.
    if "parent_training_completed" in body and body["parent_training_completed"] is not None:
        flag = optional_bool(body, "parent_training_completed", default=False)
        hp["parent_training_completed"] = flag
        touch(hp)
    if hp["status"] != "ASSIGNED":
        raise ApiError(errors.ERR_HOME_PROGRAM_NOT_ASSIGNED, 409,
                       "Home program must be ASSIGNED to activate.")
    if not hp["parent_training_completed"]:
        raise ApiError(errors.ERR_PARENT_TRAINING_INCOMPLETE, 409,
                       "Parent training is not complete.")
    plan = db.plans_of_care.get(hp["plan_of_care_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise ApiError(errors.ERR_PLAN_NOT_ACTIVE, 409,
                       "Parent plan of care is not ACTIVE.")
    hp["status"] = "ACTIVE"
    touch(hp)
    return success(serialize.home_program(hp), status=200)


@bp.route("/clinic/home-programs/<home_program_id>/complete", methods=["POST"])
@require_roles("Therapist")
def complete(home_program_id, user_id=None, role=None):
    hp = lookup(db.home_programs, home_program_id)
    if hp["status"] != "ACTIVE":
        raise ApiError(errors.ERR_HOME_PROGRAM_NOT_ACTIVE, 409,
                       "Home program must be ACTIVE to complete.")
    hp["status"] = "COMPLETED"
    touch(hp)
    return success(serialize.home_program(hp), status=200)


@bp.route("/clinic/home-programs/<home_program_id>/cancel", methods=["POST"])
@require_roles("Therapist")
def cancel(home_program_id, user_id=None, role=None):
    hp = lookup(db.home_programs, home_program_id)
    if hp["status"] not in ("ASSIGNED", "ACTIVE"):
        raise ApiError(errors.ERR_HOME_PROGRAM_NOT_CANCELLABLE, 409,
                       "Home program must be ASSIGNED or ACTIVE to cancel.")
    hp["status"] = "CANCELLED"
    touch(hp)
    return success(serialize.home_program(hp), status=200)
