"""Shared helpers: serialization, request-body validation, path resolution,
state checks, and posture gating (PRD 2.6, 2.7, 2.8)."""
from datetime import datetime
from decimal import Decimal

from flask import request

from db import store, iso, parse_dt
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_ALLIANCE_NOT_FOUND,
    ERR_AWARD_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_EVENT_FROZEN,
    ERR_EVENT_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MATCH_NOT_FOUND,
    ERR_MILESTONE_NOT_FOUND,
    ERR_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_PERSON_NOT_FOUND,
    ERR_RECORD_NOT_FOUND,
    ERR_RESET_LOG_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_TEAM_NOT_FOUND,
    ERR_VIOLATION_NOT_FOUND,
)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize_value(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def public(row):
    """Public view of a stored row: internal keys (prefixed '_') are stripped."""
    return {k: serialize_value(v) for k, v in row.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------

def get_body():
    """Parse the JSON request body; absent body means {}. Non-object -> 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be a string" % name)
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a string" % name)
    return v


def req_int(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be an integer" % name)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be <= %s" % (name, maximum))
    return v


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body.get(name) is None:
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_num(body, name, minimum_exclusive=None, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be a number" % name)
    if minimum_exclusive is not None and not (v > minimum_exclusive):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be > %s" % (name, minimum_exclusive))
    if minimum is not None and not (v >= minimum):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be >= %s" % (name, minimum))
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be a boolean" % name)
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "Field '%s' must be one of %s" % (name, ", ".join(sorted(allowed))),
        )
    return v


def req_dt(body, name):
    v = body.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an ISO 8601 datetime" % name)
    return dt


# ---------------------------------------------------------------------------
# Path resolution (left-to-right, scoped to parents) — PRD 2.8
# ---------------------------------------------------------------------------

def resolve_event(event_id):
    e = store.events.get(event_id)
    if e is None:
        raise ApiError(ERR_EVENT_NOT_FOUND, 404, "Event %s not found" % event_id)
    return e


def resolve_team(event, team_id):
    t = store.teams.get(team_id)
    if t is None or t["event_id"] != event["id"]:
        raise ApiError(ERR_TEAM_NOT_FOUND, 404, "Team %s not found" % team_id)
    return t


def resolve_person(event, person_id):
    p = store.persons.get(person_id)
    if p is None or p.get("_event_id") != event["id"]:
        raise ApiError(ERR_PERSON_NOT_FOUND, 404, "Person %s not found" % person_id)
    return p


def resolve_record(person, record_id):
    r = store.screening_records.get(record_id)
    if r is None or r["person_id"] != person["id"]:
        raise ApiError(ERR_RECORD_NOT_FOUND, 404, "ScreeningRecord %s not found" % record_id)
    return r


def resolve_milestone(event, milestone_id):
    m = store.milestones.get(milestone_id)
    if m is None or m["event_id"] != event["id"]:
        raise ApiError(ERR_MILESTONE_NOT_FOUND, 404, "Milestone %s not found" % milestone_id)
    return m


def resolve_order(team, order_id):
    o = store.part_orders.get(order_id)
    if o is None or o["team_id"] != team["id"]:
        raise ApiError(ERR_ORDER_NOT_FOUND, 404, "PartOrder %s not found" % order_id)
    return o


def resolve_inspection(team, inspection_id):
    i = store.robot_inspections.get(inspection_id)
    if i is None or i["team_id"] != team["id"]:
        raise ApiError(ERR_INSPECTION_NOT_FOUND, 404, "RobotInspection %s not found" % inspection_id)
    return i


def resolve_violation(team, violation_id):
    v = store.violations.get(violation_id)
    if v is None or v["team_id"] != team["id"]:
        raise ApiError(ERR_VIOLATION_NOT_FOUND, 404, "ComplianceViolation %s not found" % violation_id)
    return v


def resolve_match(event, match_id):
    m = store.matches.get(match_id)
    if m is None or m["event_id"] != event["id"]:
        raise ApiError(ERR_MATCH_NOT_FOUND, 404, "Match %s not found" % match_id)
    return m


def resolve_breakdown(match, breakdown_id):
    b = store.breakdowns.get(breakdown_id)
    if b is None or b["match_id"] != match["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, "MatchScoreBreakdown %s not found" % breakdown_id)
    return b


def resolve_queue_slot(match, slot_id):
    s = store.queue_slots.get(slot_id)
    if s is None or s["match_id"] != match["id"]:
        raise ApiError(ERR_SLOT_NOT_FOUND, 404, "QueueSlot %s not found" % slot_id)
    return s


def resolve_reset_log(match, log_id):
    l = store.reset_logs.get(log_id)
    if l is None or l["match_id"] != match["id"]:
        raise ApiError(ERR_RESET_LOG_NOT_FOUND, 404, "FieldResetLog %s not found" % log_id)
    return l


def resolve_alliance(event, alliance_id):
    a = store.alliances.get(alliance_id)
    if a is None or a["event_id"] != event["id"]:
        raise ApiError(ERR_ALLIANCE_NOT_FOUND, 404, "Alliance %s not found" % alliance_id)
    return a


def resolve_round(event, round_id):
    r = store.rounds.get(round_id)
    if r is None or r["event_id"] != event["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, "AllianceSelectionRound %s not found" % round_id)
    return r


def resolve_award(event, award_id):
    a = store.awards.get(award_id)
    if a is None or a["event_id"] != event["id"]:
        raise ApiError(ERR_AWARD_NOT_FOUND, 404, "Award %s not found" % award_id)
    return a


def resolve_interview_slot(award, slot_id):
    s = store.interview_slots.get(slot_id)
    if s is None or s["award_id"] != award["id"]:
        raise ApiError(ERR_SLOT_NOT_FOUND, 404, "InterviewSlot %s not found" % slot_id)
    return s


def resolve_booking(team, booking_id):
    b = store.travel_bookings.get(booking_id)
    if b is None or b["team_id"] != team["id"]:
        raise ApiError(ERR_BOOKING_NOT_FOUND, 404, "TravelBooking %s not found" % booking_id)
    return b


# ---------------------------------------------------------------------------
# Posture gate and entity state checks — PRD 2.6 / 2.7
# ---------------------------------------------------------------------------

def gate_posture(event, require_open=False):
    """Write gate: FROZEN blocks every write; some operations require OPEN."""
    posture = event.get("posture", "OPEN")
    if posture == "FROZEN":
        raise ApiError(ERR_EVENT_FROZEN, 409, "Event posture is FROZEN")
    if require_open and posture != "OPEN":
        raise ApiError(ERR_EVENT_FROZEN, 409, "Operation requires OPEN posture (currently %s)" % posture)


def check_from_state(row, field, allowed_from, terminal_states, label):
    """Priority 6: target entity must be in a from-state for the transition."""
    current = row.get(field)
    if isinstance(allowed_from, str):
        allowed_from = {allowed_from}
    if current in allowed_from:
        return
    if current in terminal_states:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "%s is already in terminal state %s" % (label, current))
    raise ApiError(
        ERR_INVALID_STATE,
        409,
        "%s is in state %s; expected %s" % (label, current, " or ".join(sorted(allowed_from))),
    )


# Terminal states per entity state machine (PRD 2.7 rule 6)
TERMINAL = {
    "FrcEvent": {"CLOSED"},
    "Team": {"WITHDRAWN", "DISQUALIFIED"},
    "Person": {"REJECTED", "EXPIRED"},
    "PartOrder": {"RECEIVED", "REJECTED", "CANCELLED"},
    "RobotInspection": {"PASSED", "FAILED"},
    "ComplianceViolation": {"RESOLVED"},
    "Match": {"FINALIZED", "CANCELLED"},
    "QueueSlot": {"RELEASED", "NO_SHOW"},
    "FieldResetLog": {"COMPLETE", "ABORTED"},
    "Alliance": {"ELIMINATED", "CHAMPION"},
    "AllianceSelectionRound": {"COMPLETE"},
    "Award": {"PRESENTED"},
    "InterviewSlot": {"COMPLETED", "NO_SHOW", "CANCELLED"},
    "TravelBooking": {"PAID", "DENIED"},
    "BuildSeasonMilestone": {"PASSED", "CANCELLED"},
}
