"""SiteVisit endpoints."""

from flask import request, Blueprint
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from errors import (
    make_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SITE_VISIT_TOO_SOON,
)
from datetime import date, timedelta

bp = Blueprint("site_visits", __name__)


def serialize_visit(visit):
    return {
        "id": visit["id"],
        "created_at": visit["created_at"],
        "updated_at": visit["updated_at"],
        "version": visit["version"],
        "association_id": visit["association_id"],
        "visit_date": visit["visit_date"],
        "status": visit["status"],
        "completed_at": visit.get("completed_at"),
    }


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


@bp.route("/site-visits", methods=["POST"])
def create_site_visit():
    require_roles("AssociationManager")
    body = request.get_json(force=True, silent=True) or {}

    required = ["association_id", "visit_date"]
    allowed = set(required)
    for field in required:
        if field not in body:
            raise make_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    for key in body:
        if key not in allowed:
            raise make_error(ERR_INVALID_REQUEST, f"Unknown field: {key}")

    assoc_id = body["association_id"]
    visit_date_str = body["visit_date"]

    assoc = store.associations.get(assoc_id)
    if not assoc:
        raise make_error(ERR_NOT_FOUND, f"Association {assoc_id} not found")

    # Validate date format
    try:
        new_date = date.fromisoformat(visit_date_str)
    except (ValueError, TypeError):
        raise make_error(ERR_INVALID_REQUEST, "visit_date must be YYYY-MM-DD")

    # Check 30-day gap from every other visit of this association
    for v in store.site_visits.values():
        if v["association_id"] == assoc_id:
            existing_date = date.fromisoformat(v["visit_date"])
            diff = abs((new_date - existing_date).days)
            if diff < 30:
                raise make_error(ERR_SITE_VISIT_TOO_SOON, f"Visit date too close to existing visit on {v['visit_date']}")

    visit = store.make_common_fields()
    visit.update({
        "association_id": assoc_id,
        "visit_date": visit_date_str,
        "status": "SCHEDULED",
        "completed_at": None,
    })
    store.site_visits[visit["id"]] = visit
    return success_object(serialize_visit(visit), 201)


@bp.route("/site-visits/<id>/complete", methods=["POST"])
def complete_site_visit(id):
    require_roles("AssociationManager")
    visit = store.site_visits.get(id)
    if not visit:
        raise make_error(ERR_NOT_FOUND, f"SiteVisit {id} not found")

    if visit["status"] != "SCHEDULED":
        raise make_error(ERR_INVALID_STATE, f"Visit is {visit['status']}, not SCHEDULED")

    visit["status"] = "COMPLETED"
    visit["completed_at"] = store.now_iso()
    store.touch(visit)

    # Recompute association's next_site_visit_due_date (and bump version)
    assoc = store.associations.get(visit["association_id"])
    if assoc:
        store.touch(assoc)

    return success_object(serialize_visit(visit))


@bp.route("/associations/<id>/site-visits", methods=["GET"])
def list_site_visits(id):
    require_roles(*ANY_ROLE)
    assoc = store.associations.get(id)
    if not assoc:
        raise make_error(ERR_NOT_FOUND, f"Association {id} not found")

    status_filter = request.args.get("status")
    visits = [v for v in store.site_visits.values() if v["association_id"] == id]
    if status_filter:
        visits = [v for v in visits if v["status"] == status_filter]
    visits.sort(key=lambda v: v["created_at"])

    limit, offset = _parse_pagination()
    total = len(visits)
    page = visits[offset:offset + limit]
    return success_list([serialize_visit(v) for v in page], total, limit, offset)
