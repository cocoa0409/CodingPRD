"""Match endpoints: scheduling, play, weather queue (PRD §3.5, §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, parse_dt, touch
from errors import (ApiError, ERR_CROSS_EVENT_REFERENCE, ERR_FIELD_BLACKED_OUT,
                    ERR_FIELD_NO_LIGHTS, ERR_FIELD_TIME_CONFLICT,
                    ERR_MATCH_NOT_RESCHEDULABLE, ERR_MATCH_NOT_SCHEDULABLE,
                    ERR_MATCH_OUTSIDE_EVENT_DATES, ERR_MATCH_TEAMS_INCOMPLETE,
                    ERR_RESCHEDULE_ORDER_VIOLATION, ERR_SCORE_INVALID,
                    ERR_TIE_NOT_ALLOWED, ERR_VALIDATION, already_terminal,
                    invalid_state, posture_forbids, raise_err)
from listing import list_response
from middleware import (get_body, opt_str, req_int, req_str,
                        require_any_authenticated, require_roles)
from response import ok

bp = Blueprint("matches", __name__, url_prefix="/api/v1")


@bp.get("/matches/<id>")
def get_match(id):
    require_any_authenticated()
    m = svc.get_or_404(STORE.matches, id, "match")
    return ok(svc.ser_match(m))


@bp.get("/matches")
def list_matches():
    require_any_authenticated()
    items = list(STORE.matches.values())
    for param in ("division_id", "field_id", "home_team_id", "away_team_id",
                  "winner_advances_to_match_id", "winner_team_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [m for m in items if m.get(param) == v]
    scheduled_on = request.args.get("scheduled_on")
    if scheduled_on is not None:
        items = [m for m in items
                 if m["scheduled_start"] is not None
                 and m["scheduled_start"].date().isoformat() == scheduled_on]
    # scheduled_start ASC nulls last, round_number ASC, created_at ASC
    items.sort(key=lambda m: (m["scheduled_start"] is None,
                              m["scheduled_start"] or m["created_at"],
                              m["round_number"],
                              m["created_at"], m["_seq"]))
    return list_response(items, svc.ser_match)


def _schedule_prechecks(m, field, start):
    """Shared scheduling/rescheduling gates after state checks (PRD §3.5).

    Order: teams -> temporal (conflict, lights, dates) -> cross-event ->
    field availability.
    """
    division = svc.get_or_404(STORE.divisions, m["division_id"], "division")
    event = svc.get_or_404(STORE.events, division["event_id"], "event")
    if m["home_team_id"] is None or m["away_team_id"] is None:
        raise_err(ERR_MATCH_TEAMS_INCOMPLETE,
                  "Both home and away teams must be assigned before scheduling.")
    end = start + timedelta(minutes=field["slot_minutes"])
    # Temporal: half-open window conflict on the field.
    if svc.field_window_conflicts(field["id"], start, end, exclude_match_id=m["id"]):
        raise_err(ERR_FIELD_TIME_CONFLICT,
                  "The match window overlaps another scheduled match on this field.")
    # Temporal: at/after 18:00 requires lights.
    if start.hour >= 18 and not field["has_lights"]:
        raise_err(ERR_FIELD_NO_LIGHTS,
                  "Matches starting at or after 18:00 require a field with lights.")
    # Temporal: scheduled date within [event.starts_on, event.ends_on].
    from db import parse_date as _pd
    sdate = start.date()
    if sdate < _pd(event["starts_on"]) or sdate > _pd(event["ends_on"]):
        raise_err(ERR_MATCH_OUTSIDE_EVENT_DATES,
                  "The scheduled date falls outside the event's date range.")
    # Cross-event: field's venue must be CONTRACTED and of the same event.
    venue = svc.get_or_404(STORE.venues, field["venue_id"], "venue")
    if venue["event_id"] != event["id"] or venue["status"] != "CONTRACTED":
        raise_err(ERR_CROSS_EVENT_REFERENCE,
                  "The field must belong to a CONTRACTED venue of the same event.")
    # Field availability.
    if field["status"] != "AVAILABLE":
        raise_err(ERR_FIELD_BLACKED_OUT, "The field is blacked out.")
    return division, event, end


@bp.post("/matches/<id>/schedule")
def schedule_match(id):
    require_roles("CommissionAdmin")
    m = svc.get_or_404(STORE.matches, id, "match")
    data = get_body()
    field_id = req_str(data, "field_id")
    try:
        start = parse_dt(data.get("scheduled_start"))
    except Exception:
        raise ApiError(*ERR_VALIDATION, "scheduled_start must be an ISO 8601 datetime.")
    field = svc.get_or_404(STORE.fields, field_id, "field")
    division = svc.get_or_404(STORE.divisions, m["division_id"], "division")
    event = svc.get_or_404(STORE.events, division["event_id"], "event")
    if event["posture"] not in ("COMPETITION_SETUP", "LIVE"):
        posture_forbids("Scheduling requires COMPETITION_SETUP or LIVE posture.")
    if m["status"] in svc.MATCH_TERMINAL:
        already_terminal("match")
    if m["status"] != "PENDING_TEAMS" or division["status"] != "BRACKET_PUBLISHED":
        raise_err(ERR_MATCH_NOT_SCHEDULABLE,
                  "Only a PENDING_TEAMS match of a BRACKET_PUBLISHED division can be scheduled.")
    _division, _event, end = _schedule_prechecks(m, field, start)
    m["field_id"] = field["id"]
    m["scheduled_start"] = start
    m["scheduled_end"] = end
    if m["original_scheduled_start"] is None:
        m["original_scheduled_start"] = start
    m["status"] = "SCHEDULED"
    touch(m)
    return ok(svc.ser_match(m))


@bp.post("/matches/<id>/reschedule")
def reschedule_match(id):
    require_roles("CommissionAdmin")
    m = svc.get_or_404(STORE.matches, id, "match")
    data = get_body()
    field_id = req_str(data, "field_id")
    try:
        start = parse_dt(data.get("scheduled_start"))
    except Exception:
        raise ApiError(*ERR_VALIDATION, "scheduled_start must be an ISO 8601 datetime.")
    field = svc.get_or_404(STORE.fields, field_id, "field")
    division = svc.get_or_404(STORE.divisions, m["division_id"], "division")
    event = svc.get_or_404(STORE.events, division["event_id"], "event")
    if event["posture"] not in ("COMPETITION_SETUP", "LIVE"):
        posture_forbids("Rescheduling requires COMPETITION_SETUP or LIVE posture.")
    if m["status"] in svc.MATCH_TERMINAL:
        already_terminal("match")
    if m["status"] != "RESCHEDULE_QUEUE":
        raise_err(ERR_MATCH_NOT_RESCHEDULABLE,
                  "Only a match in the reschedule queue can be rescheduled.")
    # Queue discipline: every earlier-sorting queued match must already be
    # SCHEDULED or terminal (i.e., this match must head the queue).
    if svc.reschedule_queue_predecessors(m):
        raise_err(ERR_RESCHEDULE_ORDER_VIOLATION,
                  "An earlier match in the division's reschedule queue is still queued.")
    _division, _event, end = _schedule_prechecks(m, field, start)
    m["field_id"] = field["id"]
    m["scheduled_start"] = start
    m["scheduled_end"] = end  # original_scheduled_start preserved
    m["status"] = "SCHEDULED"
    touch(m)
    return ok(svc.ser_match(m))


@bp.post("/matches/<id>/start")
def start_match(id):
    require_roles("CommissionAdmin")
    m = svc.get_or_404(STORE.matches, id, "match")
    division = svc.get_or_404(STORE.divisions, m["division_id"], "division")
    event = svc.get_or_404(STORE.events, division["event_id"], "event")
    if event["posture"] != "LIVE":
        posture_forbids("Starting a match requires LIVE posture.")
    if m["status"] in svc.MATCH_TERMINAL:
        already_terminal("match")
    if m["status"] != "SCHEDULED":
        raise_err(ERR_MATCH_NOT_SCHEDULABLE, "Only a SCHEDULED match can be started.")
    m["status"] = "IN_PROGRESS"
    touch(m)
    return ok(svc.ser_match(m))


@bp.post("/matches/<id>/finalize")
def finalize_match(id):
    require_roles("CommissionAdmin")
    m = svc.get_or_404(STORE.matches, id, "match")
    data = get_body()
    home_score = data.get("home_score")
    away_score = data.get("away_score")
    for label, v in (("home_score", home_score), ("away_score", away_score)):
        if not isinstance(v, int) or isinstance(v, bool):
            raise ApiError(*ERR_VALIDATION, f"{label} is required and must be an integer.")
    division = svc.get_or_404(STORE.divisions, m["division_id"], "division")
    event = svc.get_or_404(STORE.events, division["event_id"], "event")
    if event["posture"] != "LIVE":
        posture_forbids("Finalizing a match requires LIVE posture.")
    if m["status"] in svc.MATCH_TERMINAL:
        already_terminal("match")
    if m["status"] != "IN_PROGRESS":
        raise_err(ERR_MATCH_NOT_SCHEDULABLE, "Only an IN_PROGRESS match can be finalized.")
    if home_score < 0 or away_score < 0:
        raise_err(ERR_SCORE_INVALID, "Scores must be zero or greater.")
    if home_score == away_score:
        raise_err(ERR_TIE_NOT_ALLOWED, "A final score may not be tied.")
    m["home_score"] = home_score
    m["away_score"] = away_score
    m["status"] = "FINAL"
    touch(m)
    winner = m["home_team_id"] if home_score > away_score else m["away_team_id"]
    svc.apply_match_result(m, winner)
    return ok(svc.ser_match(m))


@bp.post("/matches/<id>/forfeit")
def forfeit_match(id):
    require_roles("CommissionAdmin")
    m = svc.get_or_404(STORE.matches, id, "match")
    data = get_body()
    forfeiting_team_id = req_str(data, "forfeiting_team_id")
    opt_str(data, "reason")
    if m["status"] in svc.MATCH_TERMINAL:
        already_terminal("match")
    if m["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise_err(ERR_MATCH_NOT_SCHEDULABLE,
                  "Only a SCHEDULED or IN_PROGRESS match can be forfeited.")
    if forfeiting_team_id not in (m["home_team_id"], m["away_team_id"]):
        raise ApiError(*ERR_VALIDATION,
                       "forfeiting_team_id must be one of the match's two teams.")
    winner = (m["away_team_id"] if m["home_team_id"] == forfeiting_team_id
              else m["home_team_id"])
    svc.release_match_assignments(m, "MATCH_CANCELLED")
    m["status"] = "FORFEITED"
    touch(m)
    svc.apply_match_result(m, winner)
    return ok(svc.ser_match(m))


@bp.get("/matches/<id>/official-assignments")
def list_match_assignments(id):
    require_any_authenticated()
    m = svc.get_or_404(STORE.matches, id, "match")
    items = svc.assignments_of_match(m["id"])
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return list_response(items, svc.ser_assignment)
