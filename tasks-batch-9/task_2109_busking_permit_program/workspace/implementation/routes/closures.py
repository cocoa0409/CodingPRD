"""Street closures, displacement and relocation (PRD section 3.9)."""
from flask import Blueprint, request

import db
from body import Body
from errors import invalid_request, invalid_state, raise_err
from gates import (P_BODY, P_BODY_FK, P_CLOSURE_CAPACITY, P_PATH, P_STATE,
                   resolve, resolve_body_fk, run_gates)
from listing import listing
from middleware import PERFORMER, PERMIT_OFFICER, require_roles
from response import ok_object
from services import calc, domain
from services.serializers import serialize
from utils import new_entity, sort_created, touch

bp = Blueprint("closures", __name__, url_prefix="/busking")

REASONS = {"SPECIAL_EVENT", "CONSTRUCTION", "EMERGENCY", "PARADE"}


def covers_pitch(closure, pitch):
    if closure["zone_id"] != pitch["zone_id"]:
        return False
    return closure["pitch_id"] is None or closure["pitch_id"] == pitch["id"]


def scope_pitches(closure):
    if closure["pitch_id"] is not None:
        pitch = db.get("pitches", closure["pitch_id"])
        return [pitch] if pitch is not None else []
    return sort_created([p for p in db.all_of("pitches") if p["zone_id"] == closure["zone_id"]])


@bp.post("/closure-orders")
def create_closure():
    require_roles([PERMIT_OFFICER])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        # Input-list order: zone_id, reason, starts_at, ends_at, pitch_id.
        ctx["zone"] = resolve_body_fk("zones", raw, "zone_id")
        ctx["pitch"] = resolve_body_fk("pitches", raw, "pitch_id")

    def check_body():
        starts_at = body.req_dt("starts_at")
        ends_at = body.req_dt("ends_at")
        if not ends_at > starts_at:
            invalid_request("ends_at must be strictly after starts_at")
        ctx["fields"] = {
            "zone_id": body.req_id("zone_id"),
            "pitch_id": body.opt_id("pitch_id"),
            "reason": body.req_enum("reason", REASONS),
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": "DRAFT",
            "affected_booking_count": 0,
            "relocated_booking_count": 0,
            "cancelled_booking_count": 0,
        }

    run_gates([(P_BODY_FK, check_fks), (P_BODY, check_body)])
    return ok_object(serialize(new_entity("closures", ctx["fields"])), status=201)


@bp.get("/closure-orders/<closure_id>")
def read_closure(closure_id):
    require_roles([PERMIT_OFFICER, PERFORMER])
    ctx = {}
    run_gates([(P_PATH, lambda: ctx.update(closure=resolve("closures", closure_id)))])
    return ok_object(serialize(ctx["closure"]))


@bp.get("/closure-orders")
def list_closures():
    require_roles([PERMIT_OFFICER, PERFORMER])
    return listing("closures", ["zone_id", "pitch_id", "status"], request.args)


@bp.post("/closure-orders/<closure_id>/activate")
def activate_closure(closure_id):
    require_roles([PERMIT_OFFICER])
    ctx = {}

    def check_state():
        if ctx["closure"]["status"] != "DRAFT":
            invalid_state("Only a DRAFT closure order can be activated")

    def check_capacity():
        closure = ctx["closure"]
        zone = db.get("zones", closure["zone_id"])
        ctx["zone"] = zone
        overlapping = 0
        for other in db.all_of("closures"):
            if (other["id"] == closure["id"] or other["zone_id"] != closure["zone_id"]
                    or other["status"] != "ACTIVE"):
                continue
            if calc.closures_intersect(closure["starts_at"], closure["ends_at"],
                                       other["starts_at"], other["ends_at"]):
                overlapping += 1
        if overlapping >= zone["max_concurrent_closures"]:
            raise_err("ERR_CLOSURE_WINDOW_CONFLICT",
                      "The district's concurrent-closure ceiling is already reached")

    run_gates([
        (P_PATH, lambda: ctx.update(closure=resolve("closures", closure_id))),
        (P_STATE, check_state),
        (P_CLOSURE_CAPACITY, check_capacity),
    ])

    closure = ctx["closure"]
    zone = ctx["zone"]

    # CASCADE L1: the order comes into force and the district's counter follows.
    closure["status"] = "ACTIVE"
    zone["active_closure_count"] = sum(
        1 for row in db.all_of("closures")
        if row["zone_id"] == zone["id"] and row["status"] == "ACTIVE")
    touch(zone)

    # CASCADE L2: every pitch in scope closes.
    pitches = scope_pitches(closure)
    for pitch in pitches:
        if pitch["availability_status"] != "CLOSED":
            pitch["availability_status"] = "CLOSED"
            touch(pitch)

    # CASCADE L3/L4: displaced sessions relocate or are cancelled outright.
    relocated = 0
    cancelled = 0
    for pitch in pitches:
        displaced = [b for b in sort_created(db.all_of("bookings"))
                     if b["pitch_id"] == pitch["id"]
                     and b["status"] in ("RESERVED", "RELOCATED")
                     and calc.closure_covers_booking(
                         closure["starts_at"], closure["ends_at"],
                         b["start_at"], b["end_at"])]
        for booking in displaced:
            fallback = db.get("pitches", pitch["fallback_pitch_id"])
            usable = (fallback is not None
                      and fallback["availability_status"] == "OPEN"
                      and not domain.has_slot_conflict(
                          fallback["id"], booking["start_at"], booking["end_at"],
                          exclude_booking_id=booking["id"]))
            if usable:
                booking["relocated_from_pitch_id"] = booking["pitch_id"]
                booking["pitch_id"] = fallback["id"]
                booking["status"] = "RELOCATED"
                booking["effective_noise_cap_db"] = domain.recompute_booking_cap(booking)
                touch(booking)
                relocated += 1
            else:
                permit = db.get("permits", booking["permit_id"])
                booking["status"] = "CANCELLED_BY_CLOSURE"
                touch(booking)
                domain.release_minutes(permit, booking["duration_minutes"])
                permit["closure_credit_minutes"] += booking["duration_minutes"]
                touch(permit)
                cancelled += 1

    closure["relocated_booking_count"] = relocated
    closure["cancelled_booking_count"] = cancelled
    closure["affected_booking_count"] = relocated + cancelled
    touch(closure)
    return ok_object(serialize(closure))
