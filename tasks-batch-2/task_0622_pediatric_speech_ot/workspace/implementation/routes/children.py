"""Children endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_iso_date
from clock import parse_date, whole_months_between
from services.common import new_record, touch, lookup, paginate, sorted_by_created
from services import serialize, engine

bp = Blueprint("children", __name__)


@bp.route("/clinic/children", methods=["POST"])
@require_roles("ClinicAdmin")
def create_child(user_id=None, role=None):
    body = get_body()
    full_name = require_str(body, "full_name")
    dob = require_iso_date(body, "date_of_birth")
    age_months = whole_months_between(parse_date(dob), db.clock.now())
    rec = new_record({
        "full_name": full_name,
        "date_of_birth": dob,
        "age_months_at_intake": age_months,
        "coordination_program": "NONE",
        "active_appointment_count": 0,
        "status": "ACTIVE",
    })
    db.children[rec["id"]] = rec
    return success(serialize.child(rec), status=201)


@bp.route("/clinic/children", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_children(user_id=None, role=None):
    items = list(db.children.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.child(c) for c in page], limit, offset, total)


@bp.route("/clinic/children/<child_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_child(child_id, user_id=None, role=None):
    rec = lookup(db.children, child_id)
    return success(serialize.child(rec), status=200)


@bp.route("/clinic/children/<child_id>/discharge", methods=["POST"])
@require_roles("ClinicAdmin")
def discharge_child(child_id, user_id=None, role=None):
    rec = lookup(db.children, child_id)
    rec["status"] = "DISCHARGED"
    touch(rec)
    return success(serialize.child(rec), status=200)


@bp.route("/clinic/children/<child_id>/authorizations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_child_authorizations(child_id, user_id=None, role=None):
    lookup(db.children, child_id)
    items = [a for a in db.authorizations.values() if a["child_id"] == child_id]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.authorization(a) for a in page], limit, offset, total)


@bp.route("/clinic/children/<child_id>/coordination-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_child_coordination_plans(child_id, user_id=None, role=None):
    lookup(db.children, child_id)
    items = [c for c in db.coordination_plans.values() if c["child_id"] == child_id]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.coordination_plan(c) for c in page], limit, offset, total)
