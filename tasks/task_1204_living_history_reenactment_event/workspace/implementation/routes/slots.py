"""Program slot endpoints: propose, list, confirm, cancel."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import authenticate, get_area, get_event, get_slot
from response import success
from services import derived
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from util import body, opt_bool, opt_int, opt_str, req_dt, req_str

bp = Blueprint("slots", __name__)

SLOT_ROLES = ["EventOrganizer", "SafetyOfficer"]


@bp.post("/events/<event_id>/program-slots")
def create_slot(event_id):
    authenticate(["EventOrganizer"], creation=True)
    ev = get_event(event_id)
    data = body(request)
    # Existence (priority 3): the body-referenced area (within this event).
    area = None
    if data.get("site_area_id") is not None:
        area = db.areas.get(data["site_area_id"])
        if area is None or area["event_id"] != ev["id"]:
            fail("ERR_AREA_NOT_FOUND", f"site area {data['site_area_id']} not found")
    # State (priority 5): posture, then area active.
    if ev["event_posture"] not in ("PUBLISHED", "EVENT_OPEN"):
        fail("ERR_INVALID_EVENT_POSTURE", "program slots require PUBLISHED or EVENT_OPEN")
    if area is not None and area["status"] != "ACTIVE":
        fail("ERR_AREA_NOT_ACTIVE", "the site area is not ACTIVE")
    # Body shape (priority 7).
    title = req_str(data, "title")
    if area is None:
        fail("ERR_VALIDATION", "missing required field: site_area_id")
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    open_flame = opt_bool(data, "open_flame", False)
    required_combatants = opt_int(data, "required_combatants", 0, minimum=0)
    # Overlap (priority 7): half-open; touching endpoints allowed.
    for s in db.slots.values():
        if s["site_area_id"] != area["id"] or s["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        if starts_at < s["ends_at"] and s["starts_at"] < ends_at:
            fail("ERR_SLOT_OVERLAP", "program slot window overlaps an existing slot")
    # Area-kind fitness (priority 7): DEMO only.
    if area["area_kind"] != "DEMO":
        fail("ERR_AREA_KIND_MISMATCH", "program slots require a DEMO area")
    # Temporal (priority 8).
    if starts_at >= ends_at:
        fail("ERR_INVALID_TIME_RANGE", "starts_at must be strictly before ends_at")
    if starts_at < ev["event_starts_at"] or ends_at > ev["event_ends_at"]:
        fail("ERR_OUTSIDE_EVENT_WINDOW", "slot window must lie within the event window")
    rec = new_record()
    rec.update(
        event_id=ev["id"],
        site_area_id=area["id"],
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        open_flame=open_flame,
        required_combatants=required_combatants,
        status="PROPOSED",
        cancel_reason=None,
    )
    db.slots[rec["id"]] = rec
    return success(serializers.program_slot(rec), 201)


@bp.get("/events/<event_id>/program-slots")
def list_event_slots(event_id):
    authenticate(SLOT_ROLES)
    ev = get_event(event_id)
    items = sorted_all(s for s in db.slots.values() if s["event_id"] == ev["id"])
    page, meta = paginate(items)
    return success([serializers.program_slot(s) for s in page], 200, pagination=meta)


@bp.get("/site-areas/<area_id>/program-slots")
def list_area_slots(area_id):
    authenticate(SLOT_ROLES)
    area = get_area(area_id)
    items = sorted_all(s for s in db.slots.values() if s["site_area_id"] == area["id"])
    page, meta = paginate(items)
    return success([serializers.program_slot(s) for s in page], 200, pagination=meta)


@bp.post("/program-slots/<slot_id>/confirm")
def confirm_slot(slot_id):
    authenticate(["EventOrganizer"])
    s = get_slot(slot_id)
    ev = db.events[s["event_id"]]
    area = db.areas[s["site_area_id"]]
    # Category order per §2.9: state/posture (incl. from-state, area) ->
    # business safety (flame) -> body/business constraint (combatants).
    if ev["event_posture"] not in ("PUBLISHED", "EVENT_OPEN"):
        fail("ERR_INVALID_EVENT_POSTURE", "confirmation requires PUBLISHED or EVENT_OPEN")
    if s["status"] != "PROPOSED":
        fail("ERR_INVALID_SLOT_STATUS", "only a PROPOSED slot can be confirmed")
    if area["status"] != "ACTIVE":
        fail("ERR_AREA_NOT_ACTIVE", "the site area is not ACTIVE")
    if s["open_flame"] and derived.restriction_level(ev) != "GREEN":
        fail("ERR_OPEN_FLAME_RESTRICTED", "open-flame programs require restriction_level GREEN")
    if s["required_combatants"] > derived.event_approved_combatant_count(ev):
        fail("ERR_VALIDATION", "required_combatants exceeds the approved combatant count")
    s["status"] = "CONFIRMED"
    touch(s)
    return success(serializers.program_slot(s), 200)


@bp.post("/program-slots/<slot_id>/cancel")
def cancel_slot(slot_id):
    authenticate(SLOT_ROLES)
    s = get_slot(slot_id)
    if s["status"] not in ("PROPOSED", "CONFIRMED"):
        fail("ERR_INVALID_SLOT_STATUS", f"slot in {s['status']} cannot be cancelled")
    reason = opt_str(body(request), "reason")
    s["status"] = "CANCELLED"
    s["cancel_reason"] = reason
    touch(s)
    return success(serializers.program_slot(s), 200)
