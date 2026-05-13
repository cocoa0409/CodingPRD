"""Visit reservation endpoints."""
import datetime as _dt
from flask import request

from clock import iso_now, now, parse_dt
from db import LOCK, get_db
from errors import APIError
from helpers import (new_entity, paginate, parse_pagination, require_body,
                     require_enum, require_field, touch)
from middleware import require_roles
from response import empty, list_success, success
from routes.epidemic import _get_or_create_config


RELATIONS = {"SPOUSE", "CHILD", "SIBLING", "OTHER_FAMILY", "FRIEND", "OTHER"}


def _serialize(r):
    return dict(r)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection."""
    return a_start < b_end and b_start < a_end


def register(app):

    @app.post("/elders/<eid>/visit-reservations")
    @require_roles("Family", "Admin")
    def create_reservation(user_id, role, eid):
        body = require_body()
        visitor_name = require_field(body, "visitor_name", str)
        visitor_id_number = require_field(body, "visitor_id_number", str)
        visitor_relation = require_enum(body, "visitor_relation", RELATIONS)
        slot_start_at_s = require_field(body, "slot_start_at", str)
        slot_end_at_s = require_field(body, "slot_end_at", str)
        try:
            slot_start = parse_dt(slot_start_at_s)
            slot_end = parse_dt(slot_end_at_s)
        except Exception:
            raise APIError("ERR_VALIDATION",
                           "slot_start_at/slot_end_at must be ISO8601", 422)
        with LOCK:
            db = get_db()
            elder = db.elders.get(eid)
            if elder is None:
                raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
            if elder.get("status") != "ADMITTED":
                raise APIError("ERR_INVALID_STATE",
                               "Elder must be ADMITTED to receive visits", 409)
            # Visit slot conflict (priority 15)
            for r in db.visit_reservations.values():
                if r["elder_id"] == eid and r["status"] in ("RESERVED", "CHECKED_IN"):
                    rs = parse_dt(r["slot_start_at"])
                    re = parse_dt(r["slot_end_at"])
                    if _overlaps(slot_start, slot_end, rs, re):
                        raise APIError("ERR_VISIT_SLOT_CONFLICT",
                                       "Overlapping reservation exists", 409)
            # Visit daily cap (priority 16)
            cfg = _get_or_create_config()
            max_per_day = cfg["max_visitors_per_day"]
            calendar_day = slot_start.date()
            same_day_count = 0
            for r in db.visit_reservations.values():
                if r["elder_id"] == eid and r["status"] in ("RESERVED", "CHECKED_IN"):
                    if parse_dt(r["slot_start_at"]).date() == calendar_day:
                        same_day_count += 1
            if same_day_count + 1 > max_per_day:
                raise APIError("ERR_VISIT_DAILY_LIMIT",
                               "Per-elder daily reservation cap exceeded", 409)
            # Slot duration (priority 17)
            duration = (slot_end - slot_start).total_seconds() / 60.0
            if duration < 15 or duration > 120:
                raise APIError("ERR_INVALID_SLOT_DURATION",
                               "Slot duration must be in [15, 120] minutes", 422)
            r = new_entity({
                "elder_id": eid,
                "visitor_name": visitor_name,
                "visitor_id_number": visitor_id_number,
                "visitor_relation": visitor_relation,
                "slot_start_at": slot_start_at_s,
                "slot_end_at": slot_end_at_s,
                "status": "RESERVED",
                "health_screening": None,
                "epidemic_mode_at_reservation": cfg["mode"],
                "check_in_at": None,
                "check_out_at": None,
            })
            db.visit_reservations[r["id"]] = r
            return success(_serialize(r), status=201)

    @app.post("/visit-reservations/<rid>/check-in")
    @require_roles("Admin")
    def check_in(user_id, role, rid):
        body = require_body()
        visitor_id_number = require_field(body, "visitor_id_number", str)
        health = body.get("health_screening")
        if not isinstance(health, dict):
            raise APIError("ERR_VALIDATION", "health_screening object required", 422)
        with LOCK:
            db = get_db()
            r = db.visit_reservations.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", f"VisitReservation {rid} not found", 404)
            if r["status"] != "RESERVED":
                raise APIError("ERR_INVALID_STATE",
                               f"Reservation is {r['status']}, expected RESERVED", 409)
            # ID match
            if r["visitor_id_number"] != visitor_id_number:
                raise APIError("ERR_INVALID_STATE",
                               "visitor_id_number does not match reservation", 409)
            elder = db.elders.get(r["elder_id"])
            if elder is None or elder.get("status") != "ADMITTED":
                raise APIError("ERR_INVALID_STATE", "Elder no longer admitted", 409)
            # Check-in window: [slot_start - 15min, slot_end]
            slot_start = parse_dt(r["slot_start_at"])
            slot_end = parse_dt(r["slot_end_at"])
            current = now()
            if current < slot_start - _dt.timedelta(minutes=15) or current > slot_end:
                raise APIError("ERR_INVALID_STATE",
                               "Check-in outside permitted window", 409)
            # Priority 11 then 12: health screening errors evaluated before lockdown
            # Per PRD §2.7, priority 11 is screening (priority 11) BEFORE
            # priority 12 lockdown. Hmm actually reading PRD again:
            # Priority list 11=health screening, 12=visit lockdown.
            # Lower priority number = checked first. So health screening (11)
            # is checked first; if it fails the rejection is ERR_HEALTH_SCREENING_FAILED.
            # But scaffold §3.6 says "If the live mode is LOCKDOWN, check-in
            # is rejected with ERR_VISITATION_LOCKED and reservation moves to DENIED."
            # Both validations can both fire; the lower priority wins —
            # so screening (11) wins over lockdown (12) when both fail.
            cfg = _get_or_create_config()
            temp = health.get("temperature_c")
            symptoms = health.get("symptoms") or []
            recent_exp = health.get("recent_exposure", False)
            if temp is None or not isinstance(temp, (int, float)) or isinstance(temp, bool):
                raise APIError("ERR_VALIDATION", "temperature_c must be a number", 422)
            if not isinstance(symptoms, list):
                raise APIError("ERR_VALIDATION", "symptoms must be a list", 422)
            if not isinstance(recent_exp, bool):
                raise APIError("ERR_VALIDATION", "recent_exposure must be bool", 422)

            screening_failed = (
                temp >= cfg["max_temperature_c"]
                or bool(symptoms)
                or (r["epidemic_mode_at_reservation"] != "NORMAL" and recent_exp)
            )
            r["health_screening"] = health
            if screening_failed:
                r["status"] = "DENIED"
                touch(r)
                raise APIError("ERR_HEALTH_SCREENING_FAILED",
                               "Health screening failed", 422)
            if cfg["mode"] == "LOCKDOWN":
                r["status"] = "DENIED"
                touch(r)
                raise APIError("ERR_VISITATION_LOCKED",
                               "Visit check-in locked down", 403)
            r["status"] = "CHECKED_IN"
            r["check_in_at"] = iso_now()
            touch(r)
            return success(_serialize(r))

    @app.post("/visit-reservations/<rid>/check-out")
    @require_roles("Admin")
    def check_out(user_id, role, rid):
        with LOCK:
            db = get_db()
            r = db.visit_reservations.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", f"VisitReservation {rid} not found", 404)
            if r["status"] != "CHECKED_IN":
                raise APIError("ERR_INVALID_STATE",
                               f"Reservation is {r['status']}, expected CHECKED_IN", 409)
            r["status"] = "COMPLETED"
            r["check_out_at"] = iso_now()
            touch(r)
            return success(_serialize(r))

    @app.delete("/visit-reservations/<rid>")
    @require_roles("Family", "Admin")
    def cancel_reservation(user_id, role, rid):
        with LOCK:
            db = get_db()
            r = db.visit_reservations.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", f"VisitReservation {rid} not found", 404)
            if r["status"] != "RESERVED":
                raise APIError("ERR_INVALID_STATE",
                               f"Reservation is {r['status']}, cannot cancel", 409)
            r["status"] = "CANCELLED"
            touch(r)
            return empty(204)

    @app.get("/elders/<eid>/visit-reservations")
    @require_roles("Admin", "Family")
    def list_reservations(user_id, role, eid):
        limit, offset = parse_pagination()
        status_f = request.args.get("status")
        db = get_db()
        if db.elders.get(eid) is None:
            raise APIError("ERR_NOT_FOUND", f"Elder {eid} not found", 404)
        items = [r for r in db.visit_reservations.values() if r["elder_id"] == eid]
        if status_f:
            items = [r for r in items if r["status"] == status_f]
        items.sort(key=lambda r: r["created_at"])
        page, total = paginate(items, limit, offset)
        return list_success([_serialize(r) for r in page], limit, offset, total)
