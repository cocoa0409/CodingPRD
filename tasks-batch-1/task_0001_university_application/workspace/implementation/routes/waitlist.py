"""Waitlist endpoints."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import APIError, ERR_NOT_FOUND
from middleware import auth_required
from response import ok_object, ok_array
from routes._helpers import parse_pagination, paginate, order_by_created_at
from services import state_machines

bp = Blueprint("waitlist", __name__)


@bp.get("/schools/<sid>/waitlist")
def list_school_waitlist(sid):
    auth_required({"AdmissionsOfficer", "PlatformAdmin"})()
    if sid not in db.schools:
        raise APIError(ERR_NOT_FOUND, 404, "School not found")
    status_f = request.args.get("status")
    limit, offset = parse_pagination()
    items = []
    for we in db.waitlist_entries.values():
        app = db.applications.get(we["application_id"])
        if not app or app["school_id"] != sid:
            continue
        # If no status filter, default to PENDING per PRD: "List PENDING waitlist entries"
        if status_f is None:
            if we["status"] != "PENDING":
                continue
        else:
            if we["status"] != status_f:
                continue
        items.append(we)
    # Ordered by rank ASC
    items.sort(key=lambda w: w["rank"])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array(page, limit, offset, total)


@bp.get("/waitlist-entries/<wid>")
def read_waitlist(wid):
    auth_required({"Applicant", "AdmissionsOfficer", "PlatformAdmin"})()
    we = db.waitlist_entries.get(wid)
    if we is None:
        raise APIError(ERR_NOT_FOUND, 404, "WaitlistEntry not found")
    if g.user_role == "Applicant":
        app = db.applications.get(we["application_id"])
        if not app or app["applicant_id"] != g.user_id:
            from errors import ERR_FORBIDDEN_OWNER_MISMATCH
            raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this waitlist entry")
    return ok_object(we)


@bp.get("/waitlist-entries")
def list_waitlist():
    auth_required({"Applicant", "AdmissionsOfficer", "PlatformAdmin"})()
    application_id = request.args.get("application_id")
    limit, offset = parse_pagination()
    items = []
    for we in db.waitlist_entries.values():
        if application_id and we["application_id"] != application_id:
            continue
        if g.user_role == "Applicant":
            app = db.applications.get(we["application_id"])
            if not app or app["applicant_id"] != g.user_id:
                continue
        items.append(we)
    items = order_by_created_at(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_array(page, limit, offset, total)


@bp.post("/schools/<sid>/waitlist/promote")
def promote(sid):
    auth_required({"AdmissionsOfficer"})()
    school = db.schools.get(sid)
    if school is None:
        raise APIError(ERR_NOT_FOUND, 404, "School not found")
    app = state_machines.waitlist_promote(school)
    return ok_object(app)
