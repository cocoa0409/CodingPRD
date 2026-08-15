"""Event lifecycle endpoints: create/get, advance, start, finalize, cancel, run-ops."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_EVENT_POSTURE,
                    ERR_SEGMENT_NOT_COVERED, ERR_NO_OPEN_WAVE, ERR_AID_STATION_NOT_READY,
                    ERR_SWIM_DECISION_PENDING, ERR_PENALTIES_UNRESOLVED, ERR_APPEALS_OUTSTANDING,
                    not_found)
from middleware import require_roles
from response import success_object
from services.core import (refresh_wave, recompute_readiness, refresh_water_pool,
                           recompute_ranks, recompute_totals, replay_result,
                           penalty_seconds_total, confirm_penalty, withdraw_registration,
                           waitlist_sweep, promote_waitlist)
from util import (stamp_common, touch, require_fields, require_bool, require_int,
                  parse_dt, clock_dt)

bp = Blueprint("events", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise not_found("event not found")
    return ev


@bp.post("/events")
def create_event():
    require_roles("RaceDirector")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "start_date", "has_swim", "water_pool_units"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise ApiError(ERR_VALIDATION, "name must be a non-empty string", 400)
    parse_dt(body["start_date"])
    has_swim = require_bool(body["has_swim"], "has_swim")
    water_pool_units = require_int(body["water_pool_units"], "water_pool_units")
    appeal_window = body.get("appeal_window_minutes", 60)
    if appeal_window is not None:
        appeal_window = require_int(appeal_window, "appeal_window_minutes")
    else:
        appeal_window = 60

    ev = stamp_common({
        "name": body["name"],
        "start_date": body["start_date"],
        "has_swim": has_swim,
        "water_pool_units": water_pool_units,
        "water_pool_remaining": water_pool_units,
        "appeal_window_minutes": appeal_window,
        "posture": "DRAFT",
        "swim_status": "PENDING_DECISION" if has_swim else "NO_SWIM",
        "ops_run_index": 0,
    })
    db.events[ev["id"]] = ev
    return success_object(ev, status=201)


@bp.get("/events/<event_id>")
def get_event(event_id):
    require_roles(*ALL)
    return success_object(get_event_or_404(event_id))


@bp.post("/events/<event_id>/advance")
def advance_event(event_id):
    require_roles("RaceDirector")
    ev = get_event_or_404(event_id)

    if ev["posture"] == "DRAFT":
        segments = [s for s in db.road_segments.values() if s["event_id"] == ev["id"]]
        if not segments:
            raise ApiError(ERR_SEGMENT_NOT_COVERED, "no road segments exist", 409)
        for seg in segments:
            covered = False
            for p in db.course_permits.values():
                if p["road_segment_id"] != seg["id"] or p["status"] != "APPROVED":
                    continue
                if (parse_dt(p["requested_start"]) <= parse_dt(seg["closure_start"])
                        and parse_dt(p["requested_end"]) >= parse_dt(seg["closure_end"])):
                    covered = True
                    break
            if not covered:
                raise ApiError(ERR_SEGMENT_NOT_COVERED,
                               f"segment {seg['id']} lacks covering approved permit", 409)
        ev["posture"] = "PERMITTED"
    elif ev["posture"] == "PERMITTED":
        open_wave = any(w["event_id"] == ev["id"] and w["status"] == "OPEN"
                       for w in db.waves.values())
        if not open_wave:
            raise ApiError(ERR_NO_OPEN_WAVE, "no wave with status OPEN", 409)
        for station in db.aid_stations.values():
            if station["event_id"] == ev["id"]:
                recompute_readiness(station)
                if station["readiness_status"] != "READY":
                    raise ApiError(ERR_AID_STATION_NOT_READY,
                                   f"aid station {station['id']} not READY", 409)
        ev["posture"] = "PUBLISHED"
    else:
        raise ApiError(ERR_INVALID_STATE, f"cannot advance from {ev['posture']}", 409)

    touch(ev)
    return success_object(ev)


@bp.post("/events/<event_id>/start")
def start_event(event_id):
    require_roles("RaceDirector")
    ev = get_event_or_404(event_id)
    if ev["posture"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, f"cannot start from {ev['posture']}", 409)
    if ev["has_swim"] and ev["swim_status"] not in ("SWIM_ON", "SWIM_CANCELLED"):
        raise ApiError(ERR_SWIM_DECISION_PENDING, "swim decision pending", 409)

    now = db.get_clock()
    for wave in db.waves.values():
        if wave["event_id"] == ev["id"]:
            wave["actual_start_time"] = now
            touch(wave)
    for reg in db.registrations.values():
        if reg["event_id"] == ev["id"] and reg["status"] == "RACKED":
            reg["status"] = "RACING"
            touch(reg)
    ev["posture"] = "LIVE"
    touch(ev)
    return success_object(ev)


@bp.post("/events/<event_id>/finalize")
def finalize_event(event_id):
    require_roles("RaceDirector")
    ev = get_event_or_404(event_id)
    if ev["posture"] != "LIVE":
        raise ApiError(ERR_INVALID_STATE, f"cannot finalize from {ev['posture']}", 409)

    reg_ids = {r["id"] for r in db.registrations.values() if r["event_id"] == ev["id"]}
    if any(p["registration_id"] in reg_ids and p["status"] == "ASSESSED"
           for p in db.penalties.values()):
        raise ApiError(ERR_PENALTIES_UNRESOLVED, "penalties still ASSESSED", 409)
    penalty_ids = {p["id"] for p in db.penalties.values() if p["registration_id"] in reg_ids}
    if any(a["penalty_id"] in penalty_ids and a["status"] in ("FILED", "UNDER_REVIEW")
           for a in db.appeals.values()):
        raise ApiError(ERR_APPEALS_OUTSTANDING, "appeals still open", 409)

    for res in db.results.values():
        if res["registration_id"] in reg_ids:
            res["status"] = "OFFICIAL"
            recompute_totals(res)
            touch(res)
    recompute_ranks(ev["id"])
    ev["posture"] = "FINALIZED"
    touch(ev)
    return success_object(ev)


@bp.post("/events/<event_id>/cancel")
def cancel_event(event_id):
    require_roles("RaceDirector")
    ev = get_event_or_404(event_id)
    if ev["posture"] not in ("PERMITTED", "PUBLISHED", "LIVE"):
        raise ApiError(ERR_INVALID_STATE, f"cannot cancel from {ev['posture']}", 409)

    for reg in list(db.registrations.values()):
        if reg["event_id"] != ev["id"]:
            continue
        if reg["status"] in ("ENTERED", "PAID", "CONFIRMED", "WAITLISTED", "RACKED"):
            withdraw_registration(reg, full_refund=True)
        elif reg["status"] == "RACING" and ev["posture"] == "LIVE":
            reg["status"] = "DNF"
            touch(reg)
    ev["posture"] = "CANCELLED"
    touch(ev)
    return success_object(ev)


@bp.post("/events/<event_id>/run-ops")
def run_ops(event_id):
    require_roles("RaceDirector")
    ev = get_event_or_404(event_id)
    clock = clock_dt()

    ev["ops_run_index"] = ev.get("ops_run_index", 0) + 1

    # 1. PAID registrations past confirm deadline -> EXPIRED
    deadline = parse_dt(ev["start_date"]) - timedelta(hours=24)
    for reg in db.registrations.values():
        if reg["event_id"] == ev["id"] and reg["status"] == "PAID" and clock > deadline:
            reg["status"] = "EXPIRED"
            touch(reg)

    # 2. Settle withdrawals: refund_final_cents at processing-date tier
    for reg in db.registrations.values():
        if (reg["event_id"] == ev["id"] and reg["status"] == "WITHDRAWN"
                and reg.get("refund_final_cents") is None
                and reg.get("refund_estimate_cents") is not None):
            from services.core import refund_tier, days_until
            reg["refund_final_cents"] = refund_tier(reg["entry_fee_cents"], days_until(ev, clock))
            touch(reg)

    # 3. Auto-confirm ASSESSED penalties past appeal window with no open appeal
    reg_ids = {r["id"] for r in db.registrations.values() if r["event_id"] == ev["id"]}
    for p in list(db.penalties.values()):
        if p["registration_id"] not in reg_ids or p["status"] != "ASSESSED":
            continue
        if parse_dt(p["appeal_window_expires_at"]) <= clock:
            open_appeal = any(a["penalty_id"] == p["id"] and a["status"] in ("FILED", "UNDER_REVIEW")
                              for a in db.appeals.values())
            if not open_appeal:
                confirm_penalty(p)

    # 4. Waitlist promotion sweep
    waitlist_sweep(ev)

    touch(ev)
    return success_object(ev)


@bp.post("/events/<event_id>/allocate-water")
def allocate_water(event_id):
    require_roles("RaceDirector")
    ev = get_event_or_404(event_id)
    stations = [s for s in db.aid_stations.values() if s["event_id"] == ev["id"]]
    stations.sort(key=lambda s: (s["location_km"], s["created_at"]))
    remaining = ev["water_pool_units"] - sum(s["allocated_water_units"] for s in stations)
    for s in stations:
        grant = min(s["required_water_units"] - s["allocated_water_units"], remaining)
        grant = max(grant, 0)
        if grant:
            s["allocated_water_units"] += grant
            remaining -= grant
        recompute_readiness(s)
        touch(s)
    refresh_water_pool(ev)
    touch(ev)
    return success_object(ev)
