"""Backup assignment endpoints."""
from flask import Blueprint, request

import db
from errors import (ApiError, invalid_state, not_resource_owner,
                    ERR_BACKUP_IS_PRIMARY)
from middleware import authenticate, require_roles
from response import array_response, object_response
from services import get_or_404, get_or_ref_404
from validate import (get_json_body, parse_pagination, paginate, require_int,
                      require_str_field)

bp = Blueprint("backups", __name__)


@bp.post("/bookings/<bid>/backup-assignments")
def create_backup(bid):
    caller = authenticate()
    require_roles(caller, {"BookingAgent"})
    booking = get_or_404(db.bookings, bid)
    body = get_json_body()
    # FK existence (priority 5) before remaining well-formedness (priority 6).
    candidate_id = require_str_field(body, "candidate_performer_id")
    candidate = get_or_ref_404(db.performers, candidate_id)
    rank = require_int(body, "rank", minimum=1)

    # Candidate may not be the booking's current active performer.
    active = booking.get("active_performer_id")
    if active is not None and candidate["id"] == active:
        raise ApiError(ERR_BACKUP_IS_PRIMARY, 409,
                       "backup candidate is the current active performer")

    rec = db.make_common()
    rec.update({
        "booking_id": booking["id"],
        "candidate_performer_id": candidate["id"],
        "rank": rank,
        "status": "OFFERED",
    })
    db.backup_assignments[rec["id"]] = rec
    return object_response(rec, 201)


@bp.get("/bookings/<bid>/backup-assignments")
def list_booking_backups(bid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer"})
    limit, offset = parse_pagination()
    get_or_404(db.bookings, bid)
    rows = [b for b in db.backup_assignments.values() if b["booking_id"] == bid]
    status = request.args.get("status")
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


@bp.get("/backup-assignments")
def list_backups():
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer"})
    limit, offset = parse_pagination()
    rows = list(db.backup_assignments.values())
    for field in ("candidate_performer_id", "booking_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [b for b in rows if b.get(field) == val]
    page, total = paginate(rows, limit, offset)
    return array_response(page, limit, offset, total)


@bp.get("/backup-assignments/<aid>")
def get_backup(aid):
    caller = authenticate()
    require_roles(caller, {"StudioAdmin", "BookingAgent", "Performer"})
    rec = get_or_404(db.backup_assignments, aid)
    return object_response(rec)


@bp.post("/backup-assignments/<aid>/accept")
def accept_backup(aid):
    caller = authenticate()
    require_roles(caller, {"Performer"})
    rec = get_or_404(db.backup_assignments, aid)
    # Ownership: acting performer must be the candidate.
    if caller.user_id != rec["candidate_performer_id"]:
        raise not_resource_owner()
    if rec["status"] != "OFFERED":
        raise invalid_state("backup is not in OFFERED state")
    candidate = db.performers[rec["candidate_performer_id"]]
    if candidate["availability_status"] not in ("AVAILABLE", "ON_HOLD"):
        raise invalid_state("candidate is not available to accept")
    rec["status"] = "ACCEPTED"
    db.touch(rec)
    return object_response(rec)


@bp.post("/backup-assignments/<aid>/decline")
def decline_backup(aid):
    caller = authenticate()
    require_roles(caller, {"Performer"})
    rec = get_or_404(db.backup_assignments, aid)
    if caller.user_id != rec["candidate_performer_id"]:
        raise not_resource_owner()
    if rec["status"] != "OFFERED":
        raise invalid_state("backup is not in OFFERED state")
    rec["status"] = "DECLINED"
    db.touch(rec)
    candidate = db.performers[rec["candidate_performer_id"]]
    candidate["reliability_score"] = max(0, candidate["reliability_score"] - 5)
    db.touch(candidate)
    return object_response(rec)
