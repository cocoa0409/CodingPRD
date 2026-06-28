"""CommunicationAttempt endpoints with FDCPA guardrails."""
from flask import Blueprint, request

from clock import clock, parse_iso8601, format_iso8601, add_days
from db import db, stamp_create, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_CEASE_COMMUNICATION,
    ERR_VALIDATION_HOLD, ERR_OUTSIDE_CALL_WINDOW, ERR_POST_CONVERSATION_COOLDOWN,
    ERR_CADENCE_EXCEEDED,
)
from middleware import require_roles
from response import object_response, array_response
from serializers import serialize_communication_attempt
from pagination import paginate
from validation import get_body, require_str, require_enum, invalid
from services.accounts import cadence_window_count, recompute_last_conversation_at

bp = Blueprint("communication", __name__)

CHANNELS = {"PHONE", "LETTER", "EMAIL"}
OUTCOMES = {"LOGGED", "CONVERSATION", "CANCELLED"}


def _counts_toward_cadence(channel, outcome):
    # true for PHONE LOGGED/CONVERSATION; false for LETTER/EMAIL and CANCELLED.
    return channel == "PHONE" and outcome in ("LOGGED", "CONVERSATION")


@bp.route("/communication-attempts", methods=["POST"])
@require_roles("Collector")
def create_attempt():
    body = get_body()
    account_id = require_str(body, "account_id")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    channel = require_enum(body, "channel", CHANNELS)
    attempted_raw = require_str(body, "attempted_at")
    attempted_at = parse_iso8601(attempted_raw)
    if attempted_at is None:
        invalid("attempted_at must be a valid ISO 8601 timestamp")
    outcome = require_enum(body, "outcome", OUTCOMES)
    # attempted_at must be <= clock.
    if attempted_at > clock.now:
        invalid("attempted_at must be at or before the current clock")

    counts = _counts_toward_cadence(channel, outcome)

    if counts:
        # Guardrails in PRD-stated order: cease, validation-hold, call-window,
        # cooldown, cadence cap.
        if account["contact_status"] == "CEASED":
            raise ApiError(*ERR_CEASE_COMMUNICATION, message="Account communication ceased")
        if account["contact_status"] == "VALIDATION_HELD":
            raise ApiError(*ERR_VALIDATION_HOLD, message="Account under validation hold")
        if channel == "PHONE":
            _check_call_window(account, attempted_at)
        _check_cooldown(account, attempted_at)
        _check_cadence(account, attempted_at)

    attempt = stamp_create({
        "account_id": account_id,
        "channel": channel,
        "attempted_at": format_iso8601(attempted_at),
        "outcome": outcome,
        "counts_toward_cadence": counts,
    })
    db.communication_attempts[attempt["id"]] = attempt
    # Recompute account derived fields touched by this attempt.
    if outcome == "CONVERSATION":
        recompute_last_conversation_at(account)
    touch(account)
    return object_response(serialize_communication_attempt(attempt), status=201)


def _check_call_window(account, attempted_at):
    consumer = db.consumers.get(account["consumer_id"])
    tz = consumer.get("timezone_offset_minutes", 0) if consumer else 0
    from datetime import timedelta
    local = attempted_at + timedelta(minutes=tz)
    # Seconds-of-day in consumer local time. Window [08:00:00, 21:00:00):
    # at-or-after 08:00:00 and strictly before 21:00:00.
    sod = local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1_000_000.0
    start = 8 * 3600       # 28800
    end = 21 * 3600        # 75600
    if sod < start or sod >= end:
        raise ApiError(*ERR_OUTSIDE_CALL_WINDOW, message="Call outside [08:00:00, 21:00:00) local time")


def _check_cooldown(account, attempted_at):
    lca = account.get("last_conversation_at")
    if not lca:
        return
    last = parse_iso8601(lca)
    end = add_days(last, 7)
    # [last_conversation_at, last_conversation_at + 7 days) is rejected.
    if last <= attempted_at < end:
        raise ApiError(*ERR_POST_CONVERSATION_COOLDOWN, message="Within post-conversation cooldown")


def _check_cadence(account, attempted_at):
    # Count existing counting attempts in the trailing 7-day window ending at
    # attempted_at; the new attempt would be the (count+1)th. 7th allowed, 8th rejected.
    existing = cadence_window_count(account["id"], at=attempted_at)
    if existing + 1 > 7:
        raise ApiError(*ERR_CADENCE_EXCEEDED, message="Cadence cap of 7 in trailing 7 days exceeded")


@bp.route("/communication-attempts/<cid>", methods=["GET"])
@require_roles("Collector", "ComplianceOfficer", "System")
def get_attempt(cid):
    a = db.communication_attempts.get(cid)
    if a is None:
        raise ApiError(*ERR_NOT_FOUND, message="CommunicationAttempt not found")
    return object_response(serialize_communication_attempt(a), status=200)


@bp.route("/communication-attempts", methods=["GET"])
@require_roles("Collector", "ComplianceOfficer", "System")
def list_attempts():
    items = list(db.communication_attempts.values())
    account_id = request.args.get("account_id")
    if account_id:
        items = [a for a in items if a["account_id"] == account_id]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_communication_attempt(a) for a in page], limit, offset, total)
