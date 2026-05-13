"""Waitlist endpoints."""
from flask import request

from clock import iso_now, parse_dt
from db import LOCK, get_db, new_id
from errors import APIError
from helpers import (paginate, parse_pagination, require_body, require_enum,
                     require_field)
from middleware import require_roles
from response import empty, list_success, success
from services import waitlist as waitlist_svc


BED_TYPE = {"SINGLE", "DOUBLE", "MULTI", "INTENSIVE_CARE"}


def _serialize(w):
    return dict(w)


def register(app):

    @app.post("/waitlist")
    @require_roles("Admin", "Family")
    def create_waitlist_entry(user_id, role):
        body = require_body()
        elder_id = require_field(body, "elder_id", str)
        requested_bed_type = require_enum(body, "requested_bed_type", BED_TYPE)
        with LOCK:
            db = get_db()
            elder = db.elders.get(elder_id)
            if elder is None:
                raise APIError("ERR_FK_NOT_FOUND", f"Elder {elder_id} not found", 404)
            if elder.get("status") != "PENDING_ADMISSION":
                raise APIError("ERR_INVALID_STATE",
                               "Elder must be PENDING_ADMISSION to enqueue", 409)
            entry_id = new_id()
            queued_at = iso_now()
            priority = waitlist_svc.compute_priority(elder)
            entry = {
                "id": entry_id,
                "elder_id": elder_id,
                "requested_bed_type": requested_bed_type,
                "priority_score": priority,
                "queued_at": queued_at,
                "status": "QUEUED",
                "offered_bed_id": None,
                "created_at": queued_at,
            }
            db.waitlist[entry_id] = entry
            # If a matching AVAILABLE bed already exists, immediately offer it
            for bed in db.beds.values():
                if bed["status"] == "AVAILABLE" and bed["bed_type"] == requested_bed_type:
                    # Only promote if higher priority than existing OFFERED for this bed type
                    waitlist_svc.promote_for_bed(bed)
                    break
            return success(_serialize(entry), status=201)

    @app.get("/waitlist")
    @require_roles("Admin")
    def list_waitlist(user_id, role):
        limit, offset = parse_pagination()
        status_f = request.args.get("status")
        type_f = request.args.get("requested_bed_type")
        db = get_db()
        items = list(db.waitlist.values())
        if status_f:
            items = [w for w in items if w["status"] == status_f]
        if type_f:
            items = [w for w in items if w["requested_bed_type"] == type_f]
        # Sorted by priority desc, queued_at asc
        items.sort(key=lambda w: (-w["priority_score"], parse_dt(w["queued_at"])))
        page, total = paginate(items, limit, offset)
        return list_success([_serialize(w) for w in page], limit, offset, total)

    @app.post("/waitlist/<wid>/decline")
    @require_roles("Family", "Admin")
    def decline_waitlist(user_id, role, wid):
        with LOCK:
            db = get_db()
            entry = db.waitlist.get(wid)
            if entry is None:
                raise APIError("ERR_NOT_FOUND", f"WaitlistEntry {wid} not found", 404)
            if entry["status"] != "OFFERED":
                raise APIError("ERR_INVALID_STATE",
                               f"Entry is {entry['status']}, not OFFERED", 409)
            offered_bed_id = entry.get("offered_bed_id")
            entry["status"] = "QUEUED"
            entry["offered_bed_id"] = None
            db.waitlist_offered_at.pop(wid, None)
            # Re-promote next eligible
            if offered_bed_id:
                bed = db.beds.get(offered_bed_id)
                if bed is not None and bed["status"] == "AVAILABLE":
                    waitlist_svc.promote_for_bed(bed)
            return success(_serialize(entry))

    @app.delete("/waitlist/<wid>")
    @require_roles("Family", "Admin")
    def cancel_waitlist(user_id, role, wid):
        with LOCK:
            db = get_db()
            entry = db.waitlist.get(wid)
            if entry is None:
                raise APIError("ERR_NOT_FOUND", f"WaitlistEntry {wid} not found", 404)
            offered_bed_id = entry.get("offered_bed_id") if entry["status"] == "OFFERED" else None
            entry["status"] = "CANCELLED"
            entry["offered_bed_id"] = None
            db.waitlist_offered_at.pop(wid, None)
            if offered_bed_id:
                bed = db.beds.get(offered_bed_id)
                if bed is not None and bed["status"] == "AVAILABLE":
                    waitlist_svc.promote_for_bed(bed)
            return empty(204)
