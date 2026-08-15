"""Stream scheduling (half-open windows) and simulcast rights (§3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import domain
from core import (ApiError, auth, body, err_invalid_request, err_invalid_state,
                  err_not_found, err_ownership, ok_obj, opt_bool, paginate,
                  pagination, req_dt, req_enum, req_int, req_str, require_role)

bp = Blueprint("streams", __name__)

STREAM_READ_ROLES = ("PlatformAdmin", "Creator", "Sponsor", "Moderator")
GRANT_READ_ROLES = ("PlatformAdmin", "Creator")
GRANT_PLATFORMS = ("TWITCH", "YOUTUBE", "KICK")
START_GRACE_MINUTES = 30
BUFFER_HOURS = 24


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------
@bp.post("/api/channels/<channel_id>/streams")
def create_stream(channel_id):
    uid, role = auth()
    b = body()
    title = req_str(b, "title")
    scheduled_start = req_dt(b, "scheduled_start")
    scheduled_end = req_dt(b, "scheduled_end")
    simulcast = opt_bool(b, "simulcast", False)
    if scheduled_end <= scheduled_start:
        raise err_invalid_request("scheduled_end must be strictly after scheduled_start")
    require_role(role, ("Creator",))
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    if uid != channel_id:
        raise err_ownership()
    # Half-open overlap (12): no sibling in SCHEDULED/LIVE whose [start, end)
    # intersects the new one; adjacency (start == other.end) is allowed.
    for s in db.store.streams.values():
        if s["channel_id"] != channel_id or s["stream_status"] not in ("SCHEDULED", "LIVE"):
            continue
        if scheduled_start < s["scheduled_end"] and s["scheduled_start"] < scheduled_end:
            raise ApiError("ERR_STREAM_WINDOW_CONFLICT", 409,
                           "Half-open overlap with a non-terminal sibling stream")
    st = db.new_entity(
        channel_id=channel_id,
        title=title,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        simulcast=simulcast,
        stream_status="SCHEDULED",
        actual_start=None,
        actual_end=None,
        peak_viewers=None,
        avg_viewers=None,
        punctuality_minutes_late=None,
    )
    db.store.streams[st["id"]] = st
    return ok_obj(domain.stream_json(st), status=201)


@bp.get("/api/streams/<stream_id>")
def get_stream(stream_id):
    uid, role = auth()
    require_role(role, STREAM_READ_ROLES)
    st = db.store.streams.get(stream_id)
    if st is None:
        raise err_not_found("Stream not found")
    return ok_obj(domain.stream_json(st))


@bp.get("/api/channels/<channel_id>/streams")
def list_streams(channel_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, STREAM_READ_ROLES)
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    streams = [s for s in db.store.streams.values() if s["channel_id"] == channel_id]
    status = request.args.get("stream_status")
    if status is not None:
        streams = [s for s in streams if s["stream_status"] == status]
    return paginate(streams, limit, offset, domain.stream_json)


@bp.post("/api/streams/<stream_id>/transition")
def transition_stream(stream_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", ("START", "END", "CANCEL"))
    if action == "END":
        peak_viewers = req_int(b, "peak_viewers", lo=0)
        avg_viewers = req_int(b, "avg_viewers", lo=0)
    require_role(role, ("Creator",))
    st = db.store.streams.get(stream_id)
    if st is None:
        raise err_not_found("Stream not found")
    if uid != st["channel_id"]:
        raise err_ownership()

    if action == "START":
        if st["stream_status"] != "SCHEDULED":
            raise err_invalid_state("Only a SCHEDULED stream can start")
        # Thirty-minute grace: starting later is NO_SHOW-eligible territory.
        if db.now() > st["scheduled_start"] + timedelta(minutes=START_GRACE_MINUTES):
            raise err_invalid_state("START attempted after the 30-minute grace window")
        if st["simulcast"]:
            # Requires an APPROVED grant fully covering the scheduled window.
            covered = any(
                g["channel_id"] == st["channel_id"] and g["grant_status"] == "APPROVED"
                and g["window_start"] <= st["scheduled_start"]
                and g["window_end"] >= st["scheduled_end"]
                for g in db.store.grants.values())
            if not covered:
                raise ApiError("ERR_SIMULCAST_GRANT_MISSING", 409,
                               "No APPROVED simulcast grant fully covers the scheduled window")
        st["stream_status"] = "LIVE"
        st["actual_start"] = db.now()
        late_seconds = (db.now() - st["scheduled_start"]).total_seconds()
        st["punctuality_minutes_late"] = max(0, int(late_seconds // 60))

    elif action == "END":
        if st["stream_status"] != "LIVE":
            raise err_invalid_state("Only a LIVE stream can end")
        st["stream_status"] = "ENDED"
        st["actual_end"] = db.now()
        st["peak_viewers"] = peak_viewers
        st["avg_viewers"] = avg_viewers
        # consistency_score_bps derives on read over the trailing 28-day window.

    else:  # CANCEL — the cancelled slot stays in the scheduled set for scoring.
        if st["stream_status"] != "SCHEDULED":
            raise err_invalid_state("Only a SCHEDULED stream can be cancelled")
        st["stream_status"] = "CANCELLED"

    db.touch(st)
    return ok_obj(domain.stream_json(st))


# ---------------------------------------------------------------------------
# Simulcast grants
# ---------------------------------------------------------------------------
@bp.post("/api/channels/<channel_id>/simulcast-grants")
def request_grant(channel_id):
    uid, role = auth()
    b = body()
    platform = req_enum(b, "platform", GRANT_PLATFORMS)
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    exclusive = opt_bool(b, "exclusive", False)
    if window_end <= window_start:
        raise err_invalid_request("window_end must be strictly after window_start")
    require_role(role, ("Creator",))
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    if uid != channel_id:
        raise err_ownership()
    g = db.new_entity(
        channel_id=channel_id,
        platform=platform,
        window_start=window_start,
        window_end=window_end,
        exclusive=exclusive,
        grant_status="REQUESTED",
    )
    db.store.grants[g["id"]] = g
    return ok_obj(domain.grant_json(g), status=201)


@bp.get("/api/channels/<channel_id>/simulcast-grants")
def list_grants(channel_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, GRANT_READ_ROLES)
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    grants = [g for g in db.store.grants.values() if g["channel_id"] == channel_id]
    for name in ("grant_status", "platform"):
        v = request.args.get(name)
        if v is not None:
            grants = [g for g in grants if g[name] == v]
    return paginate(grants, limit, offset, domain.grant_json)


@bp.post("/api/simulcast-grants/<simulcast_grant_id>/transition")
def transition_grant(simulcast_grant_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", ("APPROVE", "DENY", "REVOKE"))
    require_role(role, ("PlatformAdmin",))
    g = db.store.grants.get(simulcast_grant_id)
    if g is None:
        raise err_not_found("Simulcast grant not found")

    if action == "APPROVE":
        if g["grant_status"] != "REQUESTED":
            raise err_invalid_state("Only a REQUESTED grant can be approved")
        ch = domain.get_channel(g["channel_id"])
        if domain.monetization_posture(ch) == "SUSPENDED":
            raise ApiError("ERR_CHANNEL_SUSPENDED", 409,
                           "Channel monetization_posture is SUSPENDED")
        # Buffer rule (13): every other APPROVED grant on the same
        # channel+platform must be separated by >= 24h in both directions.
        buf = timedelta(hours=BUFFER_HOURS)
        for other in db.store.grants.values():
            if other["id"] == g["id"] or other["channel_id"] != g["channel_id"]:
                continue
            if other["platform"] != g["platform"] or other["grant_status"] != "APPROVED":
                continue
            separated = (g["window_start"] >= other["window_end"] + buf) or \
                        (other["window_start"] >= g["window_end"] + buf)
            if not separated:
                raise ApiError("ERR_SIMULCAST_BUFFER_CONFLICT", 409,
                               "Approval would leave < 24h gap versus another APPROVED grant")
        g["grant_status"] = "APPROVED"
    elif action == "DENY":
        if g["grant_status"] != "REQUESTED":
            raise err_invalid_state("Only a REQUESTED grant can be denied")
        g["grant_status"] = "DENIED"
    else:  # REVOKE
        if g["grant_status"] != "APPROVED":
            raise err_invalid_state("Only an APPROVED grant can be revoked")
        g["grant_status"] = "REVOKED"

    db.touch(g)
    return ok_obj(domain.grant_json(g))
