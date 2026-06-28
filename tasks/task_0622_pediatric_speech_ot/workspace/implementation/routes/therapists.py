"""Therapist endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import db
from response import success, list_success
from middleware import require_roles, ALL_ROLES
from validation import get_body, require_str, require_int, require_enum
from services.common import new_record, lookup, paginate, sorted_by_created
from services import serialize

bp = Blueprint("therapists", __name__)


@bp.route("/clinic/therapists", methods=["POST"])
@require_roles("ClinicAdmin")
def create_therapist(user_id=None, role=None):
    body = get_body()
    full_name = require_str(body, "full_name")
    discipline = require_enum(body, "discipline", {"SLP", "OT"})
    max_caseload = require_int(body, "max_caseload", minimum=1)
    weekly_cap = require_int(body, "weekly_visit_minutes_cap", minimum=0)
    rec = new_record({
        "full_name": full_name,
        "discipline": discipline,
        "max_caseload": max_caseload,
        "weekly_visit_minutes_cap": weekly_cap,
        "current_caseload": 0,
        "status": "ACTIVE",
    })
    db.therapists[rec["id"]] = rec
    return success(serialize.therapist(rec), status=201)


@bp.route("/clinic/therapists", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_therapists(user_id=None, role=None):
    items = list(db.therapists.values())
    discipline = request.args.get("discipline")
    status = request.args.get("status")
    if discipline is not None:
        items = [t for t in items if t["discipline"] == discipline]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return list_success([serialize.therapist(t) for t in page], limit, offset, total)


@bp.route("/clinic/therapists/<therapist_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_therapist(therapist_id, user_id=None, role=None):
    rec = lookup(db.therapists, therapist_id)
    return success(serialize.therapist(rec), status=200)
