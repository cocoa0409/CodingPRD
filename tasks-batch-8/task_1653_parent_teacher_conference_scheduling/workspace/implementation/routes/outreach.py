"""OutreachTask endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("outreach", __name__)

STAFF = {"SchoolAdmin", "FrontOfficeStaff"}


@bp.route("/conf/outreach-tasks", methods=["GET"])
def list_tasks():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    limit, offset = util.parse_pagination(request.args)
    filters = {
        "family_id": request.args.get("family_id"),
        "window_id": request.args.get("window_id"),
        "booking_id": request.args.get("booking_id"),
        "status": request.args.get("status"),
        "kind": request.args.get("kind"),
    }
    items = list(db.outreach_tasks.values())
    for key, value in filters.items():
        if value is not None:
            items = [t for t in items if t.get(key) == value]
    items.sort(key=lambda t: t["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.outreach_view(t) for t in page],
                                 total, limit, offset)


@bp.route("/conf/outreach-tasks/<oid>", methods=["GET"])
def get_task(oid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    task = core.get_outreach_or_404(oid)
    return response.success_object(serializers.outreach_view(task))


@bp.route("/conf/outreach-tasks", methods=["POST"])
def create_task():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    body = util.get_body()
    util.require_fields(body, ["family_id", "kind"])
    family_id = body["family_id"]
    if not isinstance(family_id, str):
        raise errors.validation("family_id must be a string")
    kind = util.require_enum(body, "kind",
                             {"NO_SHOW_FOLLOW_UP", "RESCHEDULE_ASSIST", "LANGUAGE_ACCESS"})
    booking_id = body.get("booking_id")
    window_id = body.get("window_id")
    note = util.optional_string(body, "note", default=None)

    core.get_family_or_404(family_id)
    resolved_window_id = None
    if booking_id is not None:
        if not isinstance(booking_id, str):
            raise errors.validation("booking_id must be a string")
        booking = core.get_booking_or_404(booking_id)
        if booking["family_id"] != family_id:
            raise errors.validation("booking does not belong to the family")
        resolved_window_id = booking["window_id"]
    if window_id is not None:
        if not isinstance(window_id, str):
            raise errors.validation("window_id must be a string")
        core.get_window_or_404(window_id)
        resolved_window_id = window_id

    task = core.create_outreach_task(family_id=family_id, kind=kind,
                                     booking_id=booking_id,
                                     window_id=resolved_window_id, note=note)
    return response.success_object(serializers.outreach_view(task), status=201)


@bp.route("/conf/outreach-tasks/<oid>/contact", methods=["POST"])
def contact_task(oid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    body = util.get_body()
    task = core.get_outreach_or_404(oid)
    if task["status"] not in ("OPEN", "CONTACTED"):
        raise errors.invalid_state("task must be OPEN or CONTACTED")
    if "note" in body and body["note"] is not None:
        if not isinstance(body["note"], str):
            raise errors.validation("note must be a string")
        task["note"] = body["note"]
    task["status"] = "CONTACTED"
    task["attempts_count"] += 1
    task["version"] += 1
    task["updated_at"] = util.now_iso()
    return response.success_object(serializers.outreach_view(task))


@bp.route("/conf/outreach-tasks/<oid>/resolve", methods=["POST"])
def resolve_task(oid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    body = util.get_body()
    task = core.get_outreach_or_404(oid)
    if task["status"] not in ("OPEN", "CONTACTED"):
        raise errors.invalid_state("task must be OPEN or CONTACTED")
    if "note" in body and body["note"] is not None:
        if not isinstance(body["note"], str):
            raise errors.validation("note must be a string")
        task["note"] = body["note"]
    task["status"] = "RESOLVED"
    task["version"] += 1
    task["updated_at"] = util.now_iso()
    return response.success_object(serializers.outreach_view(task))


@bp.route("/conf/outreach-tasks/<oid>/dismiss", methods=["POST"])
def dismiss_task(oid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF)
    util.get_body()  # optional reason
    task = core.get_outreach_or_404(oid)
    if task["status"] not in ("OPEN", "CONTACTED"):
        raise errors.invalid_state("task must be OPEN or CONTACTED")
    task["status"] = "DISMISSED"
    task["version"] += 1
    task["updated_at"] = util.now_iso()
    return response.success_object(serializers.outreach_view(task))
