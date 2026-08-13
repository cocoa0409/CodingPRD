"""Volunteer, Shift, and ShiftSignup endpoints (PRD §3.8)."""

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, now, parse_dt, touch
from errors import (ApiError, ERR_BACKGROUND_CHECK_REQUIRED,
                    ERR_CROSS_EVENT_REFERENCE, ERR_SHIFT_FULL,
                    ERR_SHIFT_NOT_OPEN, ERR_SHIFT_TIME_INVALID,
                    ERR_SHIFT_WINDOW_OVERLAP, ERR_VALIDATION, already_terminal,
                    invalid_state, raise_err)
from listing import list_response
from middleware import (forbid, get_body, req_bool, req_enum, req_int, req_str,
                        require_any_authenticated, require_roles)
from response import ok

bp = Blueprint("volunteers", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Volunteers
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/volunteers")
def create_volunteer(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    name = req_str(data, "name")
    email = req_str(data, "email")
    v = base_entity()
    v.update({
        "event_id": e["id"],
        "name": name,
        "email": email,
        "background_check_cleared": False,
        "status": "APPLIED",
    })
    STORE.volunteers[v["id"]] = v
    return ok(svc.ser_volunteer(v), status=201)


@bp.get("/events/<id>/volunteers")
def list_volunteers(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.volunteers_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items.sort(key=lambda v: (v["created_at"], v["_seq"]))
    return list_response(items, svc.ser_volunteer)


@bp.get("/volunteers/<id>")
def get_volunteer(id):
    require_any_authenticated()
    v = svc.get_or_404(STORE.volunteers, id, "volunteer")
    return ok(svc.ser_volunteer(v))


@bp.patch("/volunteers/<id>")
def patch_volunteer(id):
    require_roles("CommissionAdmin")
    v = svc.get_or_404(STORE.volunteers, id, "volunteer")
    data = get_body()
    cleared = req_bool(data, "background_check_cleared")
    if v["status"] in svc.VOLUNTEER_TERMINAL:
        already_terminal("volunteer")
    v["background_check_cleared"] = cleared
    touch(v)
    return ok(svc.ser_volunteer(v))


@bp.post("/volunteers/<id>/transition")
def transition_volunteer(id):
    require_roles("CommissionAdmin")
    v = svc.get_or_404(STORE.volunteers, id, "volunteer")
    data = get_body()
    action = req_enum(data, "action", svc.VOLUNTEER_ACTIONS)
    if v["status"] in svc.VOLUNTEER_TERMINAL:
        already_terminal("volunteer")
    targets = {
        ("APPLIED", "APPROVE"): "APPROVED",
        ("APPLIED", "REJECT"): "REJECTED",
        ("APPROVED", "ACTIVATE"): "ACTIVE",
        ("ACTIVE", "DEACTIVATE"): "INACTIVE",
    }
    target = targets.get((v["status"], action))
    if target is None:
        invalid_state(f"Action {action} is not valid for a volunteer in {v['status']}.")
    if action == "APPROVE" and not v["background_check_cleared"]:
        raise_err(ERR_BACKGROUND_CHECK_REQUIRED,
                  "The volunteer's background check must be cleared before approval.")
    v["status"] = target
    if action == "DEACTIVATE":
        for g in svc.signups_of_volunteer(v["id"]):
            if g["status"] in ("SIGNED_UP", "CONFIRMED"):
                g["status"] = "CANCELLED"
                touch(g)
                shift = STORE.shifts.get(g["shift_id"])
                if shift is not None:
                    svc.shift_recompute_bubble(shift)
    touch(v)
    return ok(svc.ser_volunteer(v))


@bp.get("/volunteers/<id>/signups")
def list_volunteer_signups(id):
    require_any_authenticated()
    v = svc.get_or_404(STORE.volunteers, id, "volunteer")
    items = svc.signups_of_volunteer(v["id"])
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items.sort(key=lambda g: (g["created_at"], g["_seq"]))
    return list_response(items, svc.ser_signup)


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/shifts")
def create_shift(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    role_needed = req_enum(data, "role_needed", svc.SHIFT_ROLES)
    try:
        starts_at = parse_dt(data.get("starts_at"))
        ends_at = parse_dt(data.get("ends_at"))
    except Exception:
        raise ApiError(*ERR_VALIDATION, "starts_at and ends_at must be ISO 8601 datetimes.")
    capacity = req_int(data, "capacity", lo=1)
    if ends_at <= starts_at:
        raise_err(ERR_SHIFT_TIME_INVALID, "ends_at must be strictly after starts_at.")
    s = base_entity()
    s.update({
        "event_id": e["id"],
        "role_needed": role_needed,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "status": "OPEN",
    })
    STORE.shifts[s["id"]] = s
    return ok(svc.ser_shift(s), status=201)


@bp.get("/events/<id>/shifts")
def list_shifts(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.shifts_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    role_needed = request.args.get("role_needed")
    if role_needed is not None:
        items = [s for s in items if s["role_needed"] == role_needed]
    items.sort(key=lambda s: (s["starts_at"], s["created_at"], s["_seq"]))
    return list_response(items, svc.ser_shift)


@bp.get("/shifts/<id>")
def get_shift(id):
    require_any_authenticated()
    s = svc.get_or_404(STORE.shifts, id, "shift")
    return ok(svc.ser_shift(s))


@bp.post("/shifts/<id>/cancel")
def cancel_shift(id):
    require_roles("CommissionAdmin")
    s = svc.get_or_404(STORE.shifts, id, "shift")
    if s["status"] in svc.SHIFT_TERMINAL:
        already_terminal("shift")
    if s["status"] not in ("OPEN", "FILLED"):
        raise_err(ERR_SHIFT_NOT_OPEN, "Only an OPEN or FILLED shift can be cancelled.")
    for g in svc.signups_of_shift(s["id"]):
        if g["status"] in ("SIGNED_UP", "CONFIRMED"):
            g["status"] = "CANCELLED"
            touch(g)
    s["status"] = "CANCELLED"
    touch(s)
    return ok(svc.ser_shift(s))


@bp.post("/shifts/<id>/complete")
def complete_shift(id):
    require_roles("CommissionAdmin")
    s = svc.get_or_404(STORE.shifts, id, "shift")
    if s["status"] in svc.SHIFT_TERMINAL:
        already_terminal("shift")
    if s["status"] not in ("OPEN", "FILLED"):
        raise_err(ERR_SHIFT_NOT_OPEN, "Only an OPEN or FILLED shift can be completed.")
    if now() <= s["ends_at"]:
        raise_err(ERR_SHIFT_TIME_INVALID, "The shift window has not yet ended.")
    hours = svc.shift_duration_hours(s)
    for g in svc.signups_of_shift(s["id"]):
        if g["status"] == "CONFIRMED":
            g["status"] = "WORKED"
            g["credited_hours"] = hours
            touch(g)
        elif g["status"] == "SIGNED_UP":
            g["status"] = "CANCELLED"
            touch(g)
    s["status"] = "COMPLETED"
    touch(s)
    return ok(svc.ser_shift(s))


@bp.get("/shifts/<id>/signups")
def list_shift_signups(id):
    require_any_authenticated()
    s = svc.get_or_404(STORE.shifts, id, "shift")
    items = svc.signups_of_shift(s["id"])
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items.sort(key=lambda g: (g["created_at"], g["_seq"]))
    return list_response(items, svc.ser_signup)


# ---------------------------------------------------------------------------
# Shift signups
# ---------------------------------------------------------------------------

@bp.post("/shifts/<id>/signups")
def create_signup(id):
    uid, role = require_roles("CommissionAdmin", "Volunteer")
    data = get_body()
    volunteer_id = data.get("volunteer_id")
    if role == "Volunteer":
        forbid(volunteer_id != uid, "A volunteer may sign up only themselves.")
    volunteer_id = req_str(data, "volunteer_id")
    s = svc.get_or_404(STORE.shifts, id, "shift")
    v = svc.get_or_404(STORE.volunteers, volunteer_id, "volunteer")
    # State: volunteer ACTIVE.
    if v["status"] in svc.VOLUNTEER_TERMINAL:
        already_terminal("volunteer")
    if v["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE volunteer can be signed up.")
    # State: shift must be accepting (COMPLETED/CANCELLED -> not open).
    if s["status"] in svc.SHIFT_TERMINAL:
        raise_err(ERR_SHIFT_NOT_OPEN, "The shift is not open for signups.")
    # Temporal: volunteer's existing windows must not overlap.
    for g in svc.signups_of_volunteer(v["id"]):
        if g["status"] not in ("SIGNED_UP", "CONFIRMED"):
            continue
        other = STORE.shifts.get(g["shift_id"])
        if other is None:
            continue
        if svc._overlaps(s["starts_at"], s["ends_at"], other["starts_at"], other["ends_at"]):
            raise_err(ERR_SHIFT_WINDOW_OVERLAP,
                      "The volunteer already holds an overlapping shift signup.")
    # Cross-event: volunteer must belong to the shift's event.
    if v["event_id"] != s["event_id"]:
        raise_err(ERR_CROSS_EVENT_REFERENCE,
                  "The volunteer belongs to a different event.")
    # Fiscal: non-cancelled signup count below capacity (a FILLED shift lands here).
    non_cancelled = sum(1 for g in svc.signups_of_shift(s["id"])
                        if g["status"] != "CANCELLED")
    if non_cancelled >= s["capacity"]:
        raise_err(ERR_SHIFT_FULL, "The shift is at capacity.")
    g = base_entity()
    g.update({
        "shift_id": s["id"],
        "volunteer_id": v["id"],
        "status": "SIGNED_UP",
        "credited_hours": None,
    })
    STORE.signups[g["id"]] = g
    return ok(svc.ser_signup(g), status=201)


@bp.get("/shift-signups/<id>")
def get_signup(id):
    require_any_authenticated()
    g = svc.get_or_404(STORE.signups, id, "shift signup")
    return ok(svc.ser_signup(g))


@bp.post("/shift-signups/<id>/confirm")
def confirm_signup(id):
    require_roles("CommissionAdmin")
    g = svc.get_or_404(STORE.signups, id, "shift signup")
    if g["status"] in svc.SIGNUP_TERMINAL:
        already_terminal("shift signup")
    if g["status"] != "SIGNED_UP":
        invalid_state("Only a SIGNED_UP signup can be confirmed.")
    s = svc.get_or_404(STORE.shifts, g["shift_id"], "shift")
    if s["status"] not in ("OPEN", "FILLED"):
        raise_err(ERR_SHIFT_NOT_OPEN, "The shift is not open for confirmations.")
    confirmed = sum(1 for x in svc.signups_of_shift(s["id"]) if x["status"] in ("CONFIRMED", "WORKED"))
    if confirmed >= s["capacity"]:
        raise_err(ERR_SHIFT_FULL, "The shift is at capacity.")
    g["status"] = "CONFIRMED"
    touch(g)
    svc.shift_recompute_bubble(s)  # may bubble OPEN -> FILLED
    return ok(svc.ser_signup(g))


@bp.post("/shift-signups/<id>/cancel")
def cancel_signup(id):
    uid, role = require_roles("CommissionAdmin", "Volunteer")
    g = svc.get_or_404(STORE.signups, id, "shift signup")
    if role == "Volunteer":
        forbid(g["volunteer_id"] != uid, "A volunteer may cancel only their own signup.")
    if g["status"] in svc.SIGNUP_TERMINAL:
        already_terminal("shift signup")
    if g["status"] not in ("SIGNED_UP", "CONFIRMED"):
        invalid_state("Only a SIGNED_UP or CONFIRMED signup can be cancelled.")
    was_confirmed = g["status"] == "CONFIRMED"
    g["status"] = "CANCELLED"
    touch(g)
    if was_confirmed:
        s = STORE.shifts.get(g["shift_id"])
        if s is not None:
            svc.shift_recompute_bubble(s)  # may reopen FILLED -> OPEN
    return ok(svc.ser_signup(g))


@bp.post("/shift-signups/<id>/mark-no-show")
def no_show_signup(id):
    require_roles("CommissionAdmin")
    g = svc.get_or_404(STORE.signups, id, "shift signup")
    if g["status"] in svc.SIGNUP_TERMINAL:
        already_terminal("shift signup")
    if g["status"] != "CONFIRMED":
        invalid_state("Only a CONFIRMED signup can be marked NO_SHOW.")
    s = svc.get_or_404(STORE.shifts, g["shift_id"], "shift")
    if now() <= s["ends_at"]:
        raise_err(ERR_SHIFT_TIME_INVALID, "The shift window has not yet ended.")
    g["status"] = "NO_SHOW"
    touch(g)
    svc.shift_recompute_bubble(s)  # may reopen FILLED -> OPEN
    return ok(svc.ser_signup(g))
