"""Data licensees, feed sessions, metered usage and settlement (PRD §3.8)."""

from flask import Blueprint

import db
from auth import authenticate
from calc import (DELIVERY_MODES, LICENSEE_CLASSES, SCOPE_MEMBERS,
                  SLA_BREACH_SUSPEND_THRESHOLD, TIER_ALLOWED_SCOPES,
                  TIER_RATE_CENTS_PER_UNIT, TIERS, exact_duration_minutes,
                  latency_multiplier, record_units_charged, reserved_forward,
                  sla_credit_cents)
from db import audit_new, audit_new_immutable, new_id, store, touch
from errors import ApiError
from lookups import (require_feed_session, require_game, require_licensee,
                     require_rights_window)
from response import array_response, object_response
from services.billing import ordered_usage_records, settle_and_terminate
from util import F, num, parse_dt, serialize, serialize_many, sorted_rows
from validation import (bool_filter, field, no_body, paginate, pagination,
                        string_filter, validate_body)

bp = Blueprint("feeds", __name__)

LICENSEE_SPEC = {
    "name": field("string"),
    "licensee_class": field("enum", values=LICENSEE_CLASSES),
    "tier": field("enum", values=TIERS),
    "granted_units": field("integer", minimum=0),
    "biometric_entitled": field("boolean", required=False, default=False),
}

SESSION_SPEC = {
    "game_id": field("string"),
    "rights_window_id": field("string"),
    "delivery_mode": field("enum", values=DELIVERY_MODES),
    "bandwidth_mbps": field("number", exclusive_minimum=0),
    "window_start_utc": field("datetime"),
    "window_end_utc": field("datetime"),
    "requested_latency_ms": field("integer", minimum=1),
    "scope": field("array", min_items=1, item=field("enum", values=SCOPE_MEMBERS)),
}

USAGE_SPEC = {
    "sampled_at_utc": field("datetime"),
    "bandwidth_mbps": field("number", exclusive_minimum=0),
    "duration_seconds": field("integer", minimum=1),
    "latency_p95_ms": field("integer", minimum=1),
}


# --------------------------------------------------------------------------
# Licensees
# --------------------------------------------------------------------------

@bp.post("/licensees")
def create_licensee():
    authenticate("LeagueDataOps")
    body = validate_body(LICENSEE_SPEC)
    licensee = {
        "id": new_id(),
        "name": body["name"],
        "licensee_class": body["licensee_class"],
        "tier": body["tier"],
        "granted_units": body["granted_units"],
        "biometric_entitled": body["biometric_entitled"],
        "available_units": body["granted_units"],
        "reserved_units": 0,
        "consumed_units": 0,
        "settled_charge_cents": 0,
        "sla_credit_cents": 0,
        "audit_flag_count": 0,
    }
    audit_new(licensee)
    store.licensees[licensee["id"]] = licensee
    return object_response(serialize(licensee), 201)


@bp.get("/licensees/<licensee_id>")
def get_licensee(licensee_id):
    authenticate("LeagueDataOps", "Licensee")
    licensee = require_licensee(licensee_id)
    return object_response(serialize(licensee))


@bp.get("/licensees/<licensee_id>/usage-records")
def list_licensee_usage_records(licensee_id):
    authenticate("LeagueDataOps", "Licensee")
    require_licensee(licensee_id)
    limit, offset = pagination()
    feed_session_id = string_filter("feed_session_id")
    sla_breach = bool_filter("sla_breach")
    rows = db.usage_records_of_licensee(licensee_id)
    if feed_session_id is not None:
        rows = [r for r in rows if r["feed_session_id"] == feed_session_id]
    if sla_breach is not None:
        rows = [r for r in rows if r["sla_breach"] == sla_breach]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


# --------------------------------------------------------------------------
# Feed sessions
# --------------------------------------------------------------------------

def _venue_transport_admits(venue, candidate_start, candidate_end,
                            candidate_bandwidth):
    """PRD §3.8: at every instant inside the candidate's half-open occupation
    interval the venue's egress capacity must hold.  Sessions that merely touch
    are adjacent rather than overlapping and do not contend, so it is enough to
    test the candidate's start plus every overlapping session's start.
    """
    if venue is None:
        return True
    capacity = F(venue["transport_capacity_mbps"])

    occupants = []
    for session in store.feed_sessions.values():
        if session["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        game = store.games.get(session["game_id"])
        if game is None or game["venue_id"] != venue["id"]:
            continue
        start = parse_dt(session["window_start_utc"])
        end = parse_dt(session["window_end_utc"])
        if start is None or end is None:
            continue
        if start < candidate_end and candidate_start < end:
            occupants.append((start, end, F(session["bandwidth_mbps"])))

    boundaries = [candidate_start]
    for start, _end, _bw in occupants:
        if candidate_start < start < candidate_end:
            boundaries.append(start)

    for instant in boundaries:
        total = F(candidate_bandwidth)
        for start, end, bandwidth in occupants:
            if start <= instant < end:
                total += bandwidth
        if total > capacity:
            return False
    return True


@bp.post("/feed-sessions")
def create_feed_session():
    principal = authenticate("Licensee")
    body = validate_body(SESSION_SPEC)

    # rank 5: game then rights window, then the acting licensee itself — a
    # Licensee never supplies its own identifier in the body.
    game = require_game(body["game_id"])
    window = require_rights_window(body["rights_window_id"])
    licensee = require_licensee(principal.user_id)

    # rank 11 / rank 12: the delivery mode picks the game gate
    if body["delivery_mode"] == "REALTIME":
        if game["collection_status"] != "LIVE":
            raise ApiError("ERR_GAME_NOT_COLLECTING",
                           "A REALTIME session requires a LIVE game.")
    else:
        if game["collection_status"] not in ("COLLECTED", "ARCHIVED"):
            raise ApiError("ERR_GAME_NOT_COLLECTED",
                           "A POST_GAME session requires a COLLECTED or "
                           "ARCHIVED game.")

    # rank 18
    if window["status"] != "ACTIVE":
        raise ApiError("ERR_RIGHTS_WINDOW_REVOKED",
                       "The rights window is revoked.")

    # rank 23
    if "BIOMETRIC" in body["scope"] and not licensee["biometric_entitled"]:
        raise ApiError("ERR_BIOMETRIC_SCOPE_NOT_LICENSED",
                       "The licence paperwork does not permit BIOMETRIC scope.")

    start = parse_dt(body["window_start_utc"])
    end = parse_dt(body["window_end_utc"])

    # rank 25
    if not (end > start):
        raise ApiError("ERR_INVALID_WINDOW_BOUNDS",
                       "window_end_utc must be strictly after window_start_utc.")

    # rank 27: the half-open session interval sits inside the closed window
    window_start = parse_dt(window["window_start_utc"])
    window_end = parse_dt(window["window_end_utc"])
    if start < window_start or end > window_end:
        raise ApiError("ERR_SESSION_WINDOW_OUTSIDE_RIGHTS",
                       "The session's occupation interval reaches outside the "
                       "rights window.")

    # rank 30
    permitted = TIER_ALLOWED_SCOPES[licensee["tier"]]
    for member in body["scope"]:
        if member not in permitted:
            raise ApiError("ERR_SCOPE_NOT_IN_TIER",
                           "Scope %s is not permitted at tier %s."
                           % (member, licensee["tier"]))

    # rank 31
    for member in body["scope"]:
        if member not in window["allowed_scopes"]:
            raise ApiError("ERR_SCOPE_NOT_IN_RIGHTS_WINDOW",
                           "Scope %s is not sold by this rights window." % member)

    venue = store.venues.get(game["venue_id"])

    # rank 32
    if venue is not None and body["requested_latency_ms"] < venue["min_achievable_latency_ms"]:
        raise ApiError("ERR_LATENCY_BELOW_VENUE_FLOOR",
                       "requested_latency_ms is below the venue's physical floor.")

    # rank 33
    if body["requested_latency_ms"] > window["max_latency_ms"]:
        raise ApiError("ERR_LATENCY_SLA_UNSATISFIABLE",
                       "requested_latency_ms is tighter than the rights window "
                       "sells.")

    # rank 34
    if not _venue_transport_admits(venue, start, end, body["bandwidth_mbps"]):
        raise ApiError("ERR_VENUE_TRANSPORT_CAPACITY_EXCEEDED",
                       "The candidate session over-subscribes the venue's egress "
                       "capacity.")

    # rank 39
    if window["game_id"] != game["id"]:
        raise ApiError("ERR_RIGHTS_WINDOW_GAME_MISMATCH",
                       "The rights window belongs to a different game.")

    duration = exact_duration_minutes(start, end)
    multiplier = latency_multiplier(body["requested_latency_ms"])
    tier_rate = TIER_RATE_CENTS_PER_UNIT[licensee["tier"]]
    reserved_units, reserved_charge = reserved_forward(
        body["bandwidth_mbps"], duration, multiplier, tier_rate)

    # rank 43
    if reserved_units > licensee["available_units"]:
        raise ApiError("ERR_LICENSEE_QUOTA_EXHAUSTED",
                       "The reservation of %d unit(s) exceeds the licensee's "
                       "available quota." % reserved_units)

    session = {
        "id": new_id(),
        "game_id": game["id"],
        "licensee_id": licensee["id"],
        "rights_window_id": window["id"],
        "delivery_mode": body["delivery_mode"],
        "bandwidth_mbps": body["bandwidth_mbps"],
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "requested_latency_ms": body["requested_latency_ms"],
        "scope": body["scope"],
        "status": "ACTIVE",
        "halt_reason": None,
        "duration_minutes": num(duration),
        "latency_multiplier": num(multiplier),
        "reserved_units": reserved_units,
        "reserved_charge_cents": reserved_charge,
        "metered_units": 0,
        "settled_charge_cents": 0,
        "refunded_units": 0,
        "usage_record_count": 0,
        "sla_breach_count": 0,
    }
    audit_new(session)
    store.feed_sessions[session["id"]] = session

    # The grand total never moves, only its distribution.
    licensee["available_units"] = licensee["available_units"] - reserved_units
    licensee["reserved_units"] = licensee["reserved_units"] + reserved_units
    touch(licensee)

    window["active_feed_session_count"] = window["active_feed_session_count"] + 1
    touch(window)

    return object_response(serialize(session), 201)


@bp.get("/feed-sessions/<session_id>")
def get_feed_session(session_id):
    authenticate("LeagueDataOps", "Licensee")
    session = require_feed_session(session_id)
    return object_response(serialize(session))


@bp.get("/feed-sessions")
def list_feed_sessions():
    authenticate("LeagueDataOps", "Licensee")
    limit, offset = pagination()
    game_id = string_filter("game_id")
    licensee_id = string_filter("licensee_id")
    rights_window_id = string_filter("rights_window_id")
    status = string_filter("status")

    rows = list(store.feed_sessions.values())
    if game_id is not None:
        rows = [r for r in rows if r["game_id"] == game_id]
    if licensee_id is not None:
        rows = [r for r in rows if r["licensee_id"] == licensee_id]
    if rights_window_id is not None:
        rows = [r for r in rows if r["rights_window_id"] == rights_window_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


# --------------------------------------------------------------------------
# Usage records
# --------------------------------------------------------------------------

@bp.post("/feed-sessions/<session_id>/usage-records")
def create_usage_record(session_id):
    principal = authenticate("Licensee")
    session = require_feed_session(session_id)
    body = validate_body(USAGE_SPEC)

    # rank 6
    if principal.user_id != session["licensee_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the owning licensee may report usage on this "
                       "session.")

    # rank 19
    if session["status"] != "ACTIVE":
        raise ApiError("ERR_SESSION_NOT_ACTIVE",
                       "Usage may only be reported against an ACTIVE session.")

    units = record_units_charged(body["bandwidth_mbps"], body["duration_seconds"],
                                F(session["latency_multiplier"]))

    # rank 44: this is why the refund at settlement can never be negative.
    if session["metered_units"] + units > session["reserved_units"]:
        raise ApiError("ERR_SESSION_RESERVATION_EXCEEDED",
                       "The record's %d unit(s) exceed the session's remaining "
                       "reservation." % units)

    licensee = store.licensees.get(session["licensee_id"])
    window = store.rights_windows.get(session["rights_window_id"])
    breach = bool(window is not None
                  and body["latency_p95_ms"] > window["max_latency_ms"])

    record = {
        "id": new_id(),
        "licensee_id": session["licensee_id"],
        "feed_session_id": session["id"],
        "sampled_at_utc": body["sampled_at_utc"],
        "bandwidth_mbps": body["bandwidth_mbps"],
        "duration_seconds": body["duration_seconds"],
        "latency_p95_ms": body["latency_p95_ms"],
        "units_charged": units,
        "sla_breach": breach,
    }
    audit_new_immutable(record)
    store.usage_records[record["id"]] = record

    session["metered_units"] = session["metered_units"] + units
    session["usage_record_count"] = session["usage_record_count"] + 1
    if breach:
        session["sla_breach_count"] = session["sla_breach_count"] + 1
        if licensee is not None:
            tier_rate = TIER_RATE_CENTS_PER_UNIT[licensee["tier"]]
            licensee["audit_flag_count"] = licensee["audit_flag_count"] + 1
            licensee["sla_credit_cents"] = (licensee["sla_credit_cents"]
                                            + sla_credit_cents(units, tier_rate))
            touch(licensee)
        # The circuit breaker trips on the third breach of a single session.
        if session["sla_breach_count"] >= SLA_BREACH_SUSPEND_THRESHOLD:
            session["status"] = "SUSPENDED"
            session["halt_reason"] = "SLA_BREACH_THRESHOLD"
    touch(session)

    return object_response(serialize(record), 201)


@bp.get("/feed-sessions/<session_id>/usage-records")
def list_usage_records(session_id):
    authenticate("LeagueDataOps", "Licensee")
    require_feed_session(session_id)
    limit, offset = pagination()
    rows = ordered_usage_records(session_id)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


@bp.post("/feed-sessions/<session_id>/terminate")
def terminate_feed_session(session_id):
    principal = authenticate("Licensee")
    session = require_feed_session(session_id)
    no_body()

    # rank 6
    if principal.user_id != session["licensee_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the owning licensee may terminate this session.")

    # rank 19
    if session["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_SESSION_NOT_ACTIVE",
                       "Only an ACTIVE or SUSPENDED session may be terminated.")

    settle_and_terminate(session)
    return object_response(serialize(session))
