"""Clock setter + Event endpoints (create/list/get/posture/summary)."""

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, iso, now, parse_date, parse_dt, touch
from errors import (ApiError, ERR_STALE_VERSION, ERR_VALIDATION,
                    already_terminal, invalid_state, posture_forbids,
                    raise_err, validation)
from listing import list_response
from middleware import (get_body, req_enum, req_int, req_str, require_any_authenticated,
                        require_roles)
from response import ok

bp = Blueprint("ops", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Logical clock (test-driving; PRD §2.4)
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("CommissionAdmin")
    data = get_body()
    raw = data.get("to_iso8601")
    try:
        target = parse_dt(raw)
    except Exception:
        raise ApiError(*ERR_VALIDATION, "to_iso8601 must be an ISO 8601 datetime string.")
    if target < STORE.clock:
        raise ApiError(*ERR_VALIDATION, "The logical clock is monotonic; cannot move it backward.")
    STORE.clock = target
    return ok({"current_utc": iso(STORE.clock)})


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bp.post("/events")
def create_event():
    require_roles("CommissionAdmin")
    data = get_body()
    name = req_str(data, "name")
    sanctioning_body = req_str(data, "sanctioning_body")
    host_city = req_str(data, "host_city")
    starts_on = data.get("starts_on")
    ends_on = data.get("ends_on")
    try:
        d_start = parse_date(starts_on)
        d_end = parse_date(ends_on)
    except Exception:
        raise ApiError(*ERR_VALIDATION, "starts_on and ends_on must be ISO dates (YYYY-MM-DD).")
    if d_end < d_start:
        raise ApiError(*ERR_VALIDATION, "ends_on must be on or after starts_on.")
    e = base_entity()
    e.update({
        "name": name,
        "sanctioning_body": sanctioning_body,
        "host_city": host_city,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "posture": "BIDDING",
        "active_bid_id": None,
    })
    STORE.events[e["id"]] = e
    return ok(svc.ser_event(e), status=201)


@bp.get("/events")
def list_events():
    require_any_authenticated()
    items = list(STORE.events.values())
    posture = request.args.get("posture")
    if posture is not None:
        items = [e for e in items if e["posture"] == posture]
    active_bid_id = request.args.get("active_bid_id")
    if active_bid_id is not None:
        items = [e for e in items if e["active_bid_id"] == active_bid_id]
    # Default sort: created_at DESC (newest first).
    items.sort(key=lambda e: (e["created_at"], e["_seq"]), reverse=True)
    return list_response(items, svc.ser_event, sort_key=None)


@bp.get("/events/<id>")
def get_event(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    return ok(svc.ser_event(e))


@bp.get("/events/<id>/summary")
def event_summary(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "summary")
    ser = svc.ser_event(e)
    blocks = svc.blocks_of_event(e["id"])
    total_final_rebate = sum(b["final_rebate_cents"] or 0 for b in blocks)
    picked_total = sum(svc.picked_up_room_nights(b, svc.PICKUP_FORWARD) for b in blocks)
    return ok({
        "posture": ser["posture"],
        "registered_team_count": ser["registered_team_count"],
        "finalized_match_count": ser["finalized_match_count"],
        "active_bid_id": ser["active_bid_id"],
        "total_final_rebate_cents": total_final_rebate,
        "picked_up_room_nights_total": picked_total,
    })


# ---------------------------------------------------------------------------
# Posture advance (OCC on event version; PRD §2.5, §2.8)
# ---------------------------------------------------------------------------

_MANUAL_TARGETS = {
    "AWARDED": {"PLANNING", "CANCELLED"},
    "PLANNING": {"REGISTRATION_OPEN", "CANCELLED"},
    "REGISTRATION_OPEN": {"COMPETITION_SETUP", "CANCELLED"},
    "COMPETITION_SETUP": {"LIVE", "CANCELLED"},
    "LIVE": {"COMPLETED"},
    "BIDDING": {"CANCELLED"},
}


@bp.post("/events/<id>/posture")
def advance_posture(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    to_posture = req_enum(data, "to_posture", svc.POSTURES)
    expected = req_int(data, "expected_event_version")
    if expected != e["version"]:
        raise_err(ERR_STALE_VERSION, "expected_event_version does not match the event's current version.")
    if e["posture"] == "CANCELLED":
        already_terminal("event")
    allowed = _MANUAL_TARGETS.get(e["posture"], set())
    if to_posture not in allowed:
        invalid_state(f"Posture {e['posture']} cannot advance to {to_posture}.")

    if to_posture == "CANCELLED":
        svc.cancel_event_cascade(e, e["posture"])
        e["posture"] = "CANCELLED"
        touch(e)
        return ok(svc.ser_event(e))

    # Readiness preconditions per rung.
    if e["posture"] == "AWARDED" and to_posture == "PLANNING":
        if not any(v["status"] == "CONTRACTED" for v in svc.venues_of_event(e["id"])):
            invalid_state("At least one venue must be CONTRACTED before advancing to PLANNING.")
        if not any(b["status"] == "CONTRACTED" for b in svc.blocks_of_event(e["id"])):
            invalid_state("At least one hotel block must be CONTRACTED before advancing to PLANNING.")
    elif e["posture"] == "PLANNING" and to_posture == "REGISTRATION_OPEN":
        if not svc.divisions_of_event(e["id"]):
            invalid_state("At least one division must exist before opening registration.")
    elif e["posture"] == "REGISTRATION_OPEN" and to_posture == "COMPETITION_SETUP":
        for d in svc.divisions_of_event(e["id"]):
            if d["status"] in svc.DIVISION_TERMINAL:
                continue
            if svc.division_eligible_count(d) >= d["min_teams"]:
                if d["status"] not in ("SEEDING_LOCKED", "BRACKET_PUBLISHED", "COMPLETED"):
                    invalid_state(
                        f"Division {d['id']} meets its minimum but is not seeding-locked.")
        # Cascade: divisions below minimum are cancelled; their teams withdraw.
        for d in svc.divisions_of_event(e["id"]):
            if d["status"] == "OPEN" and svc.division_eligible_count(d) < d["min_teams"]:
                d["status"] = "CANCELLED"
                touch(d)
                for t in svc.teams_of_division(d["id"]):
                    if t["status"] in ("ENTERED", "WAITLISTED", "ROSTER_SUBMITTED", "ELIGIBLE"):
                        t["status"] = "WITHDRAWN"
                        touch(t)
    elif e["posture"] == "COMPETITION_SETUP" and to_posture == "LIVE":
        for d in svc.divisions_of_event(e["id"]):
            if d["status"] not in ("BRACKET_PUBLISHED", "COMPLETED", "CANCELLED"):
                invalid_state(f"Division {d['id']} is not bracket-published, completed, or cancelled.")
    elif e["posture"] == "LIVE" and to_posture == "COMPLETED":
        active = {"PENDING_TEAMS", "SCHEDULED", "WEATHER_DELAYED", "RESCHEDULE_QUEUE", "IN_PROGRESS"}
        if any(m["status"] in active for m in svc.matches_of_event(e["id"])):
            invalid_state("Matches remain in progress or unplayed.")

    e["posture"] = to_posture
    touch(e)
    return ok(svc.ser_event(e))
