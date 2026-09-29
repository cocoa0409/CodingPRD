"""Shoot sessions: booking the floor, freezing the call sheet, the on-set colour
check, capture window and wrap."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from core import (
    COLOR_CONSISTENCY_DRIFT_MAX, SESSION_STATES, USAGE_SCOPES, actor_id,
    authorize, by_created, created, db, fail, get_body, new_row, now, ok,
    ok_list, page_params, paginate, qdate, qenum, qstr, touch, varray, vdt,
    venum, vint, vnum, vstr, whole_minutes,
)
from cascade import cascade_session_cancelled, cascade_session_wrapped
from logic import color_baseline, color_composite, find, session_items
from serialize import session_out

bp = Blueprint("sessions", __name__)

OCCUPYING_STATES = ("BOOKED", "LOCKED", "SHOOTING", "WRAPPED")


def photographer_gate(session):
    """PRD 3.7 / validations priority 8: the acting X-User-ID must hold a
    CONFIRMED PHOTOGRAPHER booking on this very session."""
    uid = actor_id()
    for booking in db.bookings.values():
        if (booking["session_id"] == session["id"]
                and booking["talent_id"] == uid
                and booking["role_on_set"] == "PHOTOGRAPHER"
                and booking["booking_state"] == "CONFIRMED"):
            return booking
    fail("ERR_NOT_BOOKED_ON_SESSION")


@bp.post("/shoot-sessions")
def create_session():
    authorize("Producer")
    body = get_body()
    station_id = vstr(body, "station_id", minlen=1)
    provider_id = vstr(body, "provider_id", minlen=1)
    scheduled_start = vdt(body, "scheduled_start")
    scheduled_end = vdt(body, "scheduled_end")
    required_usage_scope = venum(body, "required_usage_scope", USAGE_SCOPES)
    budget_cap_cents = vint(body, "budget_cap_cents", minimum=0)
    session_label = vstr(body, "session_label", required=False, default=None, maxlen=200)
    color_chart_code = vstr(body, "color_chart_code", required=False,
                            default="XRITE_CC24", minlen=1, maxlen=64)
    color_tolerance_delta_e = vnum(body, "color_tolerance_delta_e", required=False,
                                   default="2.00", minimum="0.10", maximum="10.00")

    station = find(db.stations, station_id, "ERR_REFERENCE_NOT_FOUND")
    provider = find(db.providers, provider_id, "ERR_REFERENCE_NOT_FOUND")

    # Interval sanity.
    if scheduled_end <= scheduled_start:
        fail("ERR_INVALID_TIME_WINDOW",
             "scheduled_end must be strictly after scheduled_start.")
    if scheduled_start.date() != scheduled_end.date():
        fail("ERR_INVALID_TIME_WINDOW", "A session may not straddle midnight UTC.")

    planned_minutes = whole_minutes(scheduled_start, scheduled_end)
    buffer_delta = timedelta(minutes=station["buffer_minutes"])

    # Buffer-extended occupation geometry against the concurrency ceiling.
    cand_start = scheduled_start
    cand_end = scheduled_end + buffer_delta
    intersections = 0
    for other in db.sessions.values():
        if other["station_id"] != station["id"]:
            continue
        if other["session_state"] not in OCCUPYING_STATES:
            continue
        other_start = other["scheduled_start"]
        other_end = other["scheduled_end"] + buffer_delta
        if cand_start < other_end and other_start < cand_end:
            intersections += 1
    if intersections >= station["max_concurrent_sessions"]:
        fail("ERR_STATION_OVERLAP")

    # Daily capacity against the candidate's own UTC date.
    candidate_date = scheduled_start.date()
    committed = sum(s["planned_minutes"] for s in db.sessions.values()
                    if s["station_id"] == station["id"]
                    and s["session_state"] != "CANCELLED"
                    and s["scheduled_start"].date() == candidate_date)
    if committed + planned_minutes > station["daily_capacity_minutes"]:
        fail("ERR_STATION_CAPACITY_EXCEEDED")

    row = new_row({
        "station_id": station["id"],
        "provider_id": provider["id"],
        "session_label": session_label,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "planned_minutes": planned_minutes,
        "required_usage_scope": required_usage_scope,
        "budget_cap_cents": budget_cap_cents,
        "session_state": "BOOKED",
        "started_at": None,
        "wrapped_at": None,
        "actual_minutes": None,
        "color_chart_code": color_chart_code,
        "color_tolerance_delta_e": color_tolerance_delta_e,
        "color_patch_deltas": [],
        "color_composite_delta_e": None,
        "color_check_state": "NOT_MEASURED",
        "color_measured_at": None,
        "color_measured_by_talent_id": None,
    })
    db.sessions[row["id"]] = row
    return created(session_out(row))


@bp.post("/shoot-sessions/<session_id>/lock")
def lock_session(session_id):
    authorize("Producer")
    session = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    if session["session_state"] != "BOOKED":
        fail("ERR_SESSION_NOT_BOOKED")

    required_assigned = [i for i in session_items(session_id)
                         if i["required"] and i["item_state"] == "ASSIGNED"]

    # The physical goods must be in the building for every style on the sheet.
    for style_id in dict.fromkeys(i["style_id"] for i in required_assigned):
        present = any(s.get("matched_style_id") == style_id
                      and s["match_state"] == "MATCHED"
                      and s["custody_state"] in ("IN_STUDIO", "ON_SET")
                      for s in db.samples.values())
        if not present:
            fail("ERR_SAMPLE_NOT_IN_STUDIO")

    if not required_assigned:
        fail("ERR_SHOT_LIST_EMPTY")

    session["session_state"] = "LOCKED"
    touch(session)
    return ok(session_out(session))


@bp.post("/shoot-sessions/<session_id>/unlock")
def unlock_session(session_id):
    authorize("Producer")
    session = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    if session["session_state"] != "LOCKED":
        fail("ERR_SESSION_NOT_LOCKED")
    session["session_state"] = "BOOKED"
    touch(session)
    return ok(session_out(session))


@bp.post("/shoot-sessions/<session_id>/cancel")
def cancel_session(session_id):
    authorize("Producer")
    body = get_body()
    vstr(body, "reason", required=False, default=None, maxlen=2000)
    session = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    if session["session_state"] not in ("BOOKED", "LOCKED"):
        fail("ERR_SESSION_TERMINAL")
    cascade_session_cancelled(session)
    return ok(session_out(session))


@bp.post("/shoot-sessions/<session_id>/start")
def start_session(session_id):
    authorize("Photographer")
    session = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    photographer_gate(session)
    if session["session_state"] != "LOCKED":
        fail("ERR_SESSION_NOT_LOCKED")
    session["session_state"] = "SHOOTING"
    session["started_at"] = now()
    touch(session)
    return ok(session_out(session))


@bp.post("/shoot-sessions/<session_id>/color-measurement")
def measure_color(session_id):
    authorize("Photographer")
    body = get_body()
    patch_deltas = varray(body, "patch_deltas", non_empty=True, numeric=True)

    session = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    photographer_gate(session)
    if session["session_state"] != "SHOOTING":
        fail("ERR_SESSION_NOT_SHOOTING")
    if session["color_check_state"] != "NOT_MEASURED":
        fail("ERR_COLOR_ALREADY_MEASURED")

    station = db.stations.get(session["station_id"])
    composite = color_composite(station, patch_deltas)

    # Cross-session consistency: nothing at all is persisted when it fails.
    baseline = color_baseline(session)
    if baseline is not None and baseline["color_composite_delta_e"] is not None:
        drift = abs(composite - Decimal(str(baseline["color_composite_delta_e"])))
        if drift > COLOR_CONSISTENCY_DRIFT_MAX:
            fail("ERR_COLOR_CONSISTENCY_DRIFT")

    session["color_patch_deltas"] = list(patch_deltas)
    session["color_composite_delta_e"] = composite
    session["color_check_state"] = (
        "PASS" if composite <= session["color_tolerance_delta_e"] else "FAIL")
    session["color_measured_at"] = now()
    session["color_measured_by_talent_id"] = actor_id()
    touch(session)
    return ok(session_out(session))


@bp.post("/shoot-sessions/<session_id>/wrap")
def wrap_session(session_id):
    authorize("Photographer")
    session = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    photographer_gate(session)
    if session["session_state"] != "SHOOTING":
        fail("ERR_SESSION_NOT_SHOOTING")
    cascade_session_wrapped(session)
    return ok(session_out(session))


@bp.get("/shoot-sessions/<session_id>")
def read_session(session_id):
    authorize("StudioAdmin", "Producer", "Photographer")
    row = find(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    return ok(session_out(row))


@bp.get("/shoot-sessions")
def list_sessions():
    authorize("StudioAdmin", "Producer", "Photographer")
    limit, offset = page_params()
    station_id = qstr("station_id")
    provider_id = qstr("provider_id")
    measured_by = qstr("color_measured_by_talent_id")
    session_state = qenum("session_state", SESSION_STATES)
    scheduled_date = qdate("scheduled_date")

    rows = list(db.sessions.values())
    if station_id is not None:
        rows = [r for r in rows if r["station_id"] == station_id]
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if measured_by is not None:
        rows = [r for r in rows if r.get("color_measured_by_talent_id") == measured_by]
    if session_state is not None:
        rows = [r for r in rows if r["session_state"] == session_state]
    if scheduled_date is not None:
        rows = [r for r in rows if r["scheduled_start"].date() == scheduled_date]

    page, total = paginate(by_created(rows), limit, offset)
    return ok_list([session_out(r) for r in page], limit, offset, total)
