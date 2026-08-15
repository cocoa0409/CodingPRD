"""Field Day event and contact endpoints (PRD §3.6): live dual scoring with
the duplicate flag, final_score locked at FINALIZED."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_EVENT_FINALIZED, ERR_EVENT_NAME_TAKEN, ERR_EVENT_NOT_OPEN,
    ERR_INVALID_STATE, ERR_MEMBERSHIP_NOT_ACTIVE, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    BANDS, MODES, POWER_CATEGORIES, as_bool, as_dt, as_enum, as_str, body_json,
    need, reject_unknown_fields,
)

bp = Blueprint("fieldday", __name__)

EVENT_STATUSES = {"PLANNING", "OPEN", "SCORING", "FINALIZED"}
ADMIN = {"ClubAdmin"}
READ_ROLES = {"ClubAdmin", "Member"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


@bp.post("/field-day-events")
def create_event():
    _auth(ADMIN)
    body = body_json(request)
    reject_unknown_fields(body, {"name", "start_at", "end_at"})
    name = as_str(need(body, "name"), "name")
    start_at = as_dt(need(body, "start_at"), "start_at")
    end_at = as_dt(need(body, "end_at"), "end_at")
    for e in db.STORE["field_day_events"].values():
        if e["name"] == name:
            raise ApiError(ERR_EVENT_NAME_TAKEN, 409,
                           "field day event name already exists: %s" % name)
    event = {
        "name": name,
        "start_at": start_at,
        "end_at": end_at,
        "status": "PLANNING",
        "_final_score_locked": None,
    }
    svc.stamp_new(event)
    db.STORE["field_day_events"][event["id"]] = event
    return success(svc.ser_event(event), "object", 201)


@bp.get("/field-day-events")
def list_events():
    _auth(READ_ROLES)
    status = request.args.get("status")
    items = [svc.ser_event(e) for e in svc.sorted_records("field_day_events")
             if status is None or e["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/field-day-events/<eid>")
def get_event(eid):
    _auth(READ_ROLES)
    return success(svc.ser_event(svc.get_event(eid)), "object", 200)


@bp.post("/field-day-events/<eid>/set-status")
def set_event_status(eid):
    _auth(ADMIN)
    event = svc.get_event(eid)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", EVENT_STATUSES)
    current = event["status"]
    now = db.now()
    if to == "OPEN":
        if current != "PLANNING":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot open an event in status %s" % current)
        if not (event["start_at"] <= now <= event["end_at"]):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "event may be opened only within [start_at, end_at]")
        event["status"] = "OPEN"
        svc.touch(event)
    elif to == "SCORING":
        if current != "OPEN":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot move an event in status %s to SCORING" % current)
        if now <= event["end_at"]:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "SCORING requires the clock to be past end_at")
        event["status"] = "SCORING"
        svc.touch(event)
    elif to == "FINALIZED":
        if current != "SCORING":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot finalize an event in status %s" % current)
        # Lock final_score: never recomputed afterwards.
        _count, _prov, final = svc.event_scores(event)
        event["_final_score_locked"] = final
        event["status"] = "FINALIZED"
        svc.touch(event)
    else:  # PLANNING is never a manual target
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move an event from %s to %s" % (current, to))
    return success(svc.ser_event(event), "object", 200)


# ---------------------------------------------------------------------------
# Field day contacts
# ---------------------------------------------------------------------------

@bp.post("/field-day-contacts")
def create_contact():
    user_id, role = _auth({"Member"})
    body = body_json(request)
    reject_unknown_fields(body, {"event_id", "worked_callsign", "band", "mode",
                                 "power_category"})
    event_id = as_str(need(body, "event_id"), "event_id")
    event = svc.get_event(event_id)  # body FK existence
    worked_callsign = as_str(need(body, "worked_callsign"), "worked_callsign")
    band = as_enum(need(body, "band"), "band", BANDS)
    mode = as_enum(need(body, "mode"), "mode", MODES)
    power_category = as_enum(need(body, "power_category"), "power_category",
                             POWER_CATEGORIES)
    member = svc.get_member(user_id)
    if event["status"] != "OPEN":
        raise ApiError(ERR_EVENT_NOT_OPEN, 409,
                       "contacts may be logged only while the event is OPEN")
    if member["membership_status"] != "ACTIVE":
        raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                       "membership_status is not ACTIVE")
    contact = {
        "event_id": event["id"],
        "operator_member_id": member["id"],
        "worked_callsign": worked_callsign,
        "band": band,
        "mode": mode,
        "power_category": power_category,
        "is_duplicate": False,
        # calculations.contact_points: computed at creation, immutable after.
        "points": svc.contact_points(mode, band, power_category),
    }
    svc.stamp_new(contact)
    db.STORE["field_day_contacts"][contact["id"]] = contact
    return success(svc.ser_contact(contact), "object", 201)


@bp.get("/field-day-contacts")
def list_contacts():
    _auth(READ_ROLES)
    event_id = request.args.get("event_id")
    operator = request.args.get("operator_member_id")
    is_duplicate = request.args.get("is_duplicate")
    items = []
    for c in svc.sorted_records("field_day_contacts"):
        if event_id is not None and c["event_id"] != event_id:
            continue
        if operator is not None and c["operator_member_id"] != operator:
            continue
        if is_duplicate is not None:
            if is_duplicate.lower() == "true":
                if not c["is_duplicate"]:
                    continue
            elif is_duplicate.lower() == "false":
                if c["is_duplicate"]:
                    continue
            else:
                continue
        items.append(svc.ser_contact(c))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/field-day-contacts/<cid>")
def get_contact(cid):
    _auth(READ_ROLES)
    return success(svc.ser_contact(svc.get_contact(cid)), "object", 200)


@bp.post("/field-day-contacts/<cid>/set-duplicate")
def set_duplicate(cid):
    _auth(ADMIN)
    contact = svc.get_contact(cid)
    body = body_json(request)
    reject_unknown_fields(body, {"is_duplicate"})
    is_duplicate = as_bool(need(body, "is_duplicate"), "is_duplicate")
    event = svc.get_event(contact["event_id"])
    if event["status"] == "FINALIZED":
        raise ApiError(ERR_EVENT_FINALIZED, 409,
                       "duplicate toggling is blocked after FINALIZED")
    contact["is_duplicate"] = is_duplicate
    svc.touch(contact)
    return success(svc.ser_contact(contact), "object", 200)
