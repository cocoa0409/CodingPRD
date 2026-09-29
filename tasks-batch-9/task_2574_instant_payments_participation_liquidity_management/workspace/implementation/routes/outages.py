"""Outage declaration and resolution."""

from datetime import datetime, timezone

from flask import Blueprint

from db import bump, db, new_record, now, order_key
from errors import ApiError
from middleware import authorize
from response import created, object_response
from timeutils import parse_instant, plus_minutes
from validation import opt_string, payload, req_enum, req_string
from services import liquidity, lookup, serializers
from services.constants import (
    OUTAGE_FALLBACK_RAILS,
    OUTAGE_SCOPES,
    OUTAGE_SEVERITIES,
    OUTAGE_STABILIZATION_BUFFER_MINUTES,
)

bp = Blueprint("outages", __name__)

FOREVER = datetime.max.replace(tzinfo=timezone.utc)


def _covered_participants(event):
    if event["scope"] == "NETWORK_WIDE":
        return sorted(db.participants.values(), key=order_key)
    participant = db.participants.get(event["participant_id"])
    return [participant] if participant is not None else []


def _scopes_conflict(new_scope, new_participant_id, other):
    if new_scope == "NETWORK_WIDE" or other["scope"] == "NETWORK_WIDE":
        return True
    return other["participant_id"] == new_participant_id


def _conflicts(new_scope, new_participant_id, started_at, ended_at):
    new_end = ended_at if ended_at is not None else FOREVER
    for other in db.outage_events.values():
        if not _scopes_conflict(new_scope, new_participant_id, other):
            continue
        other_start = other["started_at"]
        if other["status"] == "RESOLVED" and other["ended_at"] is not None:
            # The closed incident interval plus its half-open stabilization buffer.
            blocked_end = plus_minutes(other["ended_at"], OUTAGE_STABILIZATION_BUFFER_MINUTES)
            if started_at < blocked_end and other_start <= new_end:
                return True
            continue
        other_end = other["ended_at"] if other["ended_at"] is not None else FOREVER
        if started_at <= other_end and other_start <= new_end:
            return True
    return False


@bp.route("/outage-events", methods=["POST"])
def declare_outage():
    authorize(["NetworkOperator"])
    body = payload()

    raw_participant = body.get("participant_id")
    if isinstance(raw_participant, str) and raw_participant.strip():
        lookup.participant(raw_participant)

    scope = req_enum(body, "scope", OUTAGE_SCOPES)
    severity = req_enum(body, "severity", OUTAGE_SEVERITIES)
    fallback_rail = req_enum(body, "fallback_rail", OUTAGE_FALLBACK_RAILS)
    started_at = parse_instant(req_string(body, "started_at"))
    raw_ended = opt_string(body, "ended_at")
    ended_at = parse_instant(raw_ended) if raw_ended is not None else None
    participant_id = None
    if scope == "PARTICIPANT":
        participant_id = req_string(body, "participant_id")

    if ended_at is not None and ended_at <= started_at:
        raise ApiError("ERR_INVALID_INTERVAL", "ended_at must be later than started_at.")

    if _conflicts(scope, participant_id, started_at, ended_at):
        raise ApiError(
            "ERR_OUTAGE_WINDOW_CONFLICT",
            "The declared window conflicts with an existing outage event.",
        )

    event = new_record()
    event.update({
        "participant_id": participant_id,
        "scope": scope,
        "severity": severity,
        "fallback_rail": fallback_rail,
        "status": "DECLARED",
        "started_at": started_at,
        "ended_at": ended_at,
        "diverted_transfer_count": 0,
    })
    db.outage_events[event["id"]] = event

    parked = 0
    for participant in _covered_participants(event):
        parked += liquidity.rederive_posture(participant)
    event["diverted_transfer_count"] = parked
    return created(serializers.outage_event(event))


@bp.route("/outage-events/<event_id>/resolution", methods=["POST"])
def resolve_outage(event_id):
    authorize(["NetworkOperator"])
    event = lookup.outage_event(event_id)
    body = payload()
    ended_at = parse_instant(req_string(body, "ended_at"))
    if ended_at <= event["started_at"] or ended_at > now():
        raise ApiError(
            "ERR_INVALID_INTERVAL",
            "ended_at must be later than started_at and not later than the current clock.",
        )
    if event["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DECLARED outage may be resolved.")

    covered = _covered_participants(event)
    event["ended_at"] = ended_at
    event["status"] = "RESOLVED"
    bump(event)
    for participant in covered:
        liquidity.rederive_posture(participant)
    return object_response(serializers.outage_event(event))
