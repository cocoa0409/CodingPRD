"""Emergency-Alert & Notification API (Task 0759).

Python + Flask, in-memory store. Boots empty on every process start.
"""
import os
from datetime import timedelta

from flask import Flask, request, jsonify

import store
from store import (
    db,
    ROLES,
    LANGS,
    CHANNEL_TYPES,
    SEVERITIES,
    SEVERITY_FACTOR,
    RETRY_BASE_DELAY_SEC,
    RETRY_MAX_BACKOFF_SEC,
    RETRY_MAX_ATTEMPTS,
    DRILL_BUFFER_MINUTES,
    SMS_SEGMENT_SIZE,
    new_id,
    new_token,
    request_id,
    parse_iso,
    fmt_iso,
    stamp_new,
    touch,
    now,
    ceil_div,
    alert_pending_count,
    group_member_count,
    gateway_window_count,
    gateway_for_channel,
    contact_reliability,
    geo_distance_m,
)

app = Flask(__name__)


# ===========================================================================
# Error handling & response envelope
# ===========================================================================
class ApiError(Exception):
    def __init__(self, http_status, error_id, message=""):
        super().__init__(message)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message or error_id


def _meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": fmt_iso(now())}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _nf(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Unknown route"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _mna(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": str(e)},
    }
    return jsonify(body), 500


# ===========================================================================
# Auth
# ===========================================================================
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(401, "ERR_UNAUTHENTICATED", "Missing or unknown auth headers")
    return uid, role


def require(role, allowed):
    if role not in allowed:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Role not permitted for this operation")


# ===========================================================================
# Body / param helpers
# ===========================================================================
def json_body():
    raw = request.get_data()
    if raw and raw.strip():
        b = request.get_json(silent=True, force=True)
        if b is None or not isinstance(b, dict):
            raise ApiError(400, "ERR_VALIDATION", "Malformed JSON body")
        return b
    return {}


def bad(msg="Invalid request"):
    raise ApiError(400, "ERR_VALIDATION", msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        bad(f"'{key}' is required and must be a non-empty string")
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        bad(f"'{key}' must be a string")
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        bad(f"'{key}' must be one of {sorted(allowed)}")
    return v


def opt_enum(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str) or v not in allowed:
        bad(f"'{key}' must be one of {sorted(allowed)}")
    return v


def opt_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        bad(f"'{key}' must be a boolean")
    return v


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_number(body, key):
    v = body.get(key)
    if not _is_number(v):
        bad(f"'{key}' must be a number")
    return v


def opt_number(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not _is_number(v):
        bad(f"'{key}' must be a number")
    return v


def req_int(body, key):
    v = body.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        bad(f"'{key}' must be an integer")
    return v


def opt_int_range(body, key, lo, hi, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, int) or isinstance(v, bool) or v < lo or v > hi:
        bad(f"'{key}' must be an integer in [{lo}, {hi}]")
    return v


def req_datetime(body, key):
    v = body.get(key)
    try:
        return parse_iso(v)
    except Exception:
        bad(f"'{key}' must be an ISO-8601 datetime")


def opt_datetime(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    try:
        return parse_iso(body[key])
    except Exception:
        bad(f"'{key}' must be an ISO-8601 datetime")


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("'limit' must be an integer")
        if limit < 1 or limit > 100:
            bad("'limit' must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("'offset' must be an integer")
        if offset < 0:
            bad("'offset' must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    window = items[offset : offset + limit]
    return window, total


# ===========================================================================
# Existence helpers
# ===========================================================================
def get_or_404(coll, _id, err_id):
    e = coll.get(_id)
    if e is None:
        raise ApiError(404, err_id, "Resource not found")
    return e


# ===========================================================================
# Serializers
# ===========================================================================
def s_common(e, extra):
    out = dict(extra)
    out["id"] = e["id"]
    out["created_at"] = fmt_iso(e["created_at"])
    out["updated_at"] = fmt_iso(e["updated_at"])
    out["version"] = e["version"]
    return out


def s_contact(e, mode="optimistic"):
    return s_common(
        e,
        {
            "full_name": e["full_name"],
            "primary_language": e["primary_language"],
            "tty_required": e["tty_required"],
            "default_lat": e["default_lat"],
            "default_lon": e["default_lon"],
            "quiet_start_min": e["quiet_start_min"],
            "quiet_end_min": e["quiet_end_min"],
            "status": e["status"],
            "reliability_score": contact_reliability(e["id"], mode),
        },
    )


def s_channel(e):
    return s_common(
        e,
        {
            "contact_id": e["contact_id"],
            "channel_type": e["channel_type"],
            "address": e["address"],
            "tty_capable": e["tty_capable"],
            "opt_in_status": e["opt_in_status"],
            "confirmation_token": e["confirmation_token"],
        },
    )


def s_group(e):
    return s_common(
        e,
        {
            "name": e["name"],
            "status": e["status"],
            "member_count": group_member_count(e["id"]),
        },
    )


def s_subscription(e):
    return s_common(
        e,
        {
            "contact_id": e["contact_id"],
            "subscription_type": e["subscription_type"],
            "group_id": e["group_id"],
            "center_lat": e["center_lat"],
            "center_lon": e["center_lon"],
            "radius_m": e["radius_m"],
            "status": e["status"],
        },
    )


def s_template(e):
    return s_common(
        e,
        {
            "name": e["name"],
            "default_severity": e["default_severity"],
            "body_by_language": e["body_by_language"],
            "status": e["status"],
        },
    )


def s_alert(e):
    return s_common(
        e,
        {
            "title": e["title"],
            "severity": e["severity"],
            "channels": e["channels"],
            "template_id": e["template_id"],
            "target_type": e["target_type"],
            "target_group_id": e["target_group_id"],
            "center_lat": e["center_lat"],
            "center_lon": e["center_lon"],
            "radius_m": e["radius_m"],
            "effective_from": fmt_iso(e["effective_from"]),
            "effective_until": fmt_iso(e["effective_until"]),
            "author_user_id": e["author_user_id"],
            "status": e["status"],
            "revision_count": e["revision_count"],
            "pending_count": alert_pending_count(e["id"]),
            "estimated_reach": e["estimated_reach"],
            "delivered_reach": e["delivered_reach"],
            "sms_billable_segments": e["sms_billable_segments"],
            "source_incident_ref": e["source_incident_ref"],
        },
    )


def s_localization(e):
    return s_common(
        e,
        {
            "alert_id": e["alert_id"],
            "language": e["language"],
            "message_text": e["message_text"],
            "segment_count": e["segment_count"],
        },
    )


def s_notification(e):
    return s_common(
        e,
        {
            "alert_id": e["alert_id"],
            "contact_id": e["contact_id"],
            "channel_id": e["channel_id"],
            "channel_type": e["channel_type"],
            "language": e["language"],
            "delivery_status": e["delivery_status"],
            "receipt_status": e["receipt_status"],
            "attempt_count": e["attempt_count"],
            "next_retry_at": fmt_iso(e["next_retry_at"]),
        },
    )


def s_gateway(e):
    return s_common(
        e,
        {
            "name": e["name"],
            "channel_type": e["channel_type"],
            "capacity_per_window": e["capacity_per_window"],
            "status": e["status"],
            "window_count": gateway_window_count(e),
        },
    )


def s_maint(e):
    return s_common(
        e,
        {
            "gateway_id": e["gateway_id"],
            "start_at": fmt_iso(e["start_at"]),
            "end_at": fmt_iso(e["end_at"]),
        },
    )


def s_drill(e):
    return s_common(
        e,
        {
            "group_id": e["group_id"],
            "scheduled_start": fmt_iso(e["scheduled_start"]),
            "scheduled_end": fmt_iso(e["scheduled_end"]),
            "status": e["status"],
        },
    )


# ===========================================================================
# Shared business helpers
# ===========================================================================
def contact_channels(contact_id):
    return [c for c in db.channels.values() if c["contact_id"] == contact_id]


def alert_localizations(alert_id):
    return [l for l in db.localizations.values() if l["alert_id"] == alert_id]


def alert_notifications(alert_id):
    return [n for n in db.notifications.values() if n["alert_id"] == alert_id]


def localization_for(alert_id, language):
    for l in db.localizations.values():
        if l["alert_id"] == alert_id and l["language"] == language:
            return l
    return None


def matched_contact_ids(alert):
    """Contacts matched by the alert's targeting (before eligibility filters)."""
    res = set()
    if alert["target_type"] == "GROUP":
        gid = alert["target_group_id"]
        for s in db.subscriptions.values():
            if (
                s["status"] == "ACTIVE"
                and s["subscription_type"] == "GROUP"
                and s["group_id"] == gid
            ):
                res.add(s["contact_id"])
    else:  # GEO
        for s in db.subscriptions.values():
            if s["status"] == "ACTIVE" and s["subscription_type"] == "GEO":
                if s["center_lat"] is None or s["center_lon"] is None:
                    continue
                dist = geo_distance_m(
                    s["center_lat"], s["center_lon"], alert["center_lat"], alert["center_lon"]
                )
                if dist <= alert["radius_m"]:
                    res.add(s["contact_id"])
    return res


def confirmed_requested_channels(contact_id, requested):
    return [
        c
        for c in db.channels.values()
        if c["contact_id"] == contact_id
        and c["opt_in_status"] == "CONFIRMED"
        and c["channel_type"] in requested
    ]


def resolve_recipients(alert):
    """Return (matched_active_ids, eligible_ids, plan).

    plan is a list of (contact, channel) pairs that would produce notifications.
    """
    requested = set(alert["channels"])
    matched = matched_contact_ids(alert)
    matched_active = set()
    eligible = []
    plan = []
    for cid in matched:
        contact = db.contacts.get(cid)
        if contact is None or contact["status"] != "ACTIVE":
            continue
        matched_active.add(cid)
        chans = confirmed_requested_channels(cid, requested)
        if chans:
            eligible.append(cid)
            for ch in chans:
                plan.append((contact, ch))
    return matched_active, eligible, plan


def language_for(alert, contact):
    lang = contact["primary_language"]
    if localization_for(alert["id"], lang) is not None:
        return lang
    return "EN"


def compute_sms_segments(alert_id):
    total = 0
    for n in db.notifications.values():
        if n["alert_id"] != alert_id or n["channel_type"] != "SMS":
            continue
        loc = localization_for(alert_id, n["language"])
        if loc is None:
            continue
        text = loc["message_text"] or ""
        total += ceil_div(len(text), SMS_SEGMENT_SIZE) if len(text) > 0 else 0
    return total


def delivered_reach(alert_id):
    return len(
        {
            n["contact_id"]
            for n in db.notifications.values()
            if n["alert_id"] == alert_id and n["delivery_status"] == "DELIVERED"
        }
    )


def close_alert(alert):
    alert["status"] = "CLOSED"
    alert["delivered_reach"] = delivered_reach(alert["id"])
    touch(alert)


def suppress_notification(n):
    n["delivery_status"] = "SUPPRESSED"
    touch(n)


# ===========================================================================
# Infra / test-driving endpoints
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = auth()
    require(role, {"Integrator"})
    body = json_body()
    try:
        target = parse_iso(body.get("to_iso8601"))
    except Exception:
        bad("'to_iso8601' must be an ISO-8601 datetime")
    db.clock = target
    return ok({"current_utc": fmt_iso(db.clock)})


@app.route("/_tick/run", methods=["POST"])
def tick_run():
    uid, role = auth()
    require(role, {"Integrator"})

    sent_count = 0
    retried_count = 0
    exhausted_count = 0
    affected_alerts = set()

    # Snapshot statuses so each notification advances at most one step per tick.
    snapshot = list(db.notifications.values())
    for n in snapshot:
        st = n["delivery_status"]
        if st == "QUEUED":
            alert = db.alerts.get(n["alert_id"])
            contact = db.contacts.get(n["contact_id"])
            gw = gateway_for_channel(n["channel_type"])
            if (
                alert is not None
                and alert["status"] == "DISPATCHING"
                and contact is not None
                and contact["status"] == "ACTIVE"
                and gw is not None
                and gw["status"] == "ONLINE"
            ):
                n["delivery_status"] = "SENT"
                n["attempt_count"] = 1
                touch(n)
                sent_count += 1
        elif st == "RETRYING":
            if n["next_retry_at"] is not None and n["next_retry_at"] <= db.clock:
                n["delivery_status"] = "SENT"
                n["attempt_count"] += 1
                n["next_retry_at"] = None
                touch(n)
                sent_count += 1
        elif st == "FAILED":
            alert = db.alerts.get(n["alert_id"])
            if n["attempt_count"] < RETRY_MAX_ATTEMPTS:
                sev = alert["severity"] if alert else "INFO"
                factor = SEVERITY_FACTOR.get(sev, 1)
                raw = RETRY_BASE_DELAY_SEC * (2 ** (n["attempt_count"] - 1)) * factor
                delay = min(RETRY_MAX_BACKOFF_SEC, raw)
                n["delivery_status"] = "RETRYING"
                n["next_retry_at"] = db.clock + timedelta(seconds=delay)
                touch(n)
                retried_count += 1
            else:
                n["delivery_status"] = "EXHAUSTED"
                touch(n)
                exhausted_count += 1
                affected_alerts.add(n["alert_id"])

    # DISPATCHING -> SENT when no QUEUED remain.
    for alert in db.alerts.values():
        if alert["status"] == "DISPATCHING":
            has_queued = any(
                n["delivery_status"] == "QUEUED"
                for n in db.notifications.values()
                if n["alert_id"] == alert["id"]
            )
            if not has_queued:
                alert["status"] = "SENT"
                touch(alert)

    # pending recompute bump for alerts touched by exhaust
    for aid in affected_alerts:
        alert = db.alerts.get(aid)
        if alert is not None:
            touch(alert)

    # Auto-close SENT alerts with zero pending.
    closed_alerts = 0
    for alert in db.alerts.values():
        if alert["status"] == "SENT" and alert_pending_count(alert["id"]) == 0:
            close_alert(alert)
            closed_alerts += 1

    # Complete due drills.
    completed_drills = 0
    for d in db.drills.values():
        if d["status"] == "SCHEDULED" and d["scheduled_end"] <= db.clock:
            d["status"] = "COMPLETED"
            touch(d)
            completed_drills += 1

    return ok(
        {
            "sent_count": sent_count,
            "retried_count": retried_count,
            "exhausted_count": exhausted_count,
            "completed_drills": completed_drills,
            "closed_alerts": closed_alerts,
        }
    )


@app.route("/_integration/ingest_incident", methods=["POST"])
def ingest_incident():
    uid, role = auth()
    require(role, {"Integrator"})
    body = json_body()
    source = req_str(body, "source")
    external_ref = req_str(body, "external_ref")
    severity = req_enum(body, "severity", SEVERITIES)
    center_lat = req_number(body, "center_lat")
    center_lon = req_number(body, "center_lon")
    radius_m = req_int(body, "radius_m")
    channels = req_channels(body)

    alert = stamp_new(
        {
            "title": opt_str(body, "title", external_ref),
            "severity": severity,
            "channels": channels,
            "template_id": None,
            "target_type": "GEO",
            "target_group_id": None,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "radius_m": radius_m,
            "effective_from": opt_datetime(body, "effective_from"),
            "effective_until": opt_datetime(body, "effective_until"),
            "author_user_id": uid,
            "status": "DRAFT",
            "revision_count": 0,
            "estimated_reach": None,
            "delivered_reach": None,
            "sms_billable_segments": None,
            "source_incident_ref": external_ref,
        }
    )
    db.alerts[alert["id"]] = alert
    return ok(s_alert(alert), 201)


def req_channels(body):
    v = body.get("channels")
    if not isinstance(v, list) or len(v) == 0:
        bad("'channels' must be a non-empty array")
    for c in v:
        if c not in CHANNEL_TYPES:
            bad("'channels' must be a subset of SMS/VOICE/EMAIL/IPAWS")
    # de-dup preserving order
    seen = []
    for c in v:
        if c not in seen:
            seen.append(c)
    return seen


# ===========================================================================
# Contacts
# ===========================================================================
@app.route("/contacts", methods=["POST"])
def create_contact():
    uid, role = auth()
    require(role, {"ContactAdmin"})
    body = json_body()
    full_name = req_str(body, "full_name")
    primary_language = opt_enum(body, "primary_language", LANGS, "EN")
    tty_required = opt_bool(body, "tty_required", False)
    default_lat = opt_number(body, "default_lat", None)
    default_lon = opt_number(body, "default_lon", None)
    quiet_start = opt_int_range(body, "quiet_start_min", 0, 1439, None)
    quiet_end = opt_int_range(body, "quiet_end_min", 0, 1439, None)

    contact = stamp_new(
        {
            "full_name": full_name,
            "primary_language": primary_language,
            "tty_required": tty_required,
            "default_lat": default_lat,
            "default_lon": default_lon,
            "quiet_start_min": quiet_start,
            "quiet_end_min": quiet_end,
            "status": "ACTIVE",
        }
    )
    db.contacts[contact["id"]] = contact
    return ok(s_contact(contact), 201)


@app.route("/contacts/<cid>", methods=["GET"])
def get_contact(cid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Approver", "Contact"})
    if role == "Contact" and uid != cid:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Contacts may only read their own record")
    contact = get_or_404(db.contacts, cid, "ERR_CONTACT_NOT_FOUND")
    mode = request.args.get("mode")
    mode = "strict" if mode == "strict" else "optimistic"
    return ok(s_contact(contact, mode))


@app.route("/contacts/<cid>/channels", methods=["POST"])
def add_channel(cid):
    uid, role = auth()
    require(role, {"ContactAdmin"})
    contact = get_or_404(db.contacts, cid, "ERR_CONTACT_NOT_FOUND")
    body = json_body()
    channel_type = req_enum(body, "channel_type", CHANNEL_TYPES)
    address = req_str(body, "address")
    tty_capable = opt_bool(body, "tty_capable", False)

    channel = stamp_new(
        {
            "contact_id": contact["id"],
            "channel_type": channel_type,
            "address": address,
            "tty_capable": tty_capable,
            "opt_in_status": "PENDING",
            "confirmation_token": new_token(),
        }
    )
    db.channels[channel["id"]] = channel
    return ok(s_channel(channel), 201)


@app.route("/contacts/<cid>/channels", methods=["GET"])
def list_channels(cid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Contact"})
    if role == "Contact" and uid != cid:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Contacts may only read their own channels")
    get_or_404(db.contacts, cid, "ERR_CONTACT_NOT_FOUND")
    limit, offset = pagination()
    items = contact_channels(cid)
    opt = request.args.get("opt_in_status")
    if opt is not None:
        items = [c for c in items if c["opt_in_status"] == opt]
    window, total = paginate(items, limit, offset)
    return ok_list([s_channel(c) for c in window], limit, offset, total)


@app.route("/channels/<chid>/confirm", methods=["POST"])
def confirm_channel(chid):
    uid, role = auth()
    require(role, {"Contact"})
    channel = get_or_404(db.channels, chid, "ERR_CHANNEL_NOT_FOUND")
    if uid != channel["contact_id"]:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Not the owning contact")
    body = json_body()
    token = req_str(body, "confirmation_token")
    if channel["opt_in_status"] != "PENDING":
        raise ApiError(409, "ERR_INVALID_STATE", "Channel not PENDING")
    if token != channel["confirmation_token"]:
        raise ApiError(422, "ERR_INVALID_TOKEN", "Confirmation token mismatch")
    channel["opt_in_status"] = "CONFIRMED"
    touch(channel)
    return ok(s_channel(channel))


@app.route("/channels/<chid>/opt-out", methods=["POST"])
def opt_out_channel(chid):
    uid, role = auth()
    require(role, {"Contact"})
    channel = get_or_404(db.channels, chid, "ERR_CHANNEL_NOT_FOUND")
    if uid != channel["contact_id"]:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Not the owning contact")
    if channel["opt_in_status"] == "OPTED_OUT":
        raise ApiError(409, "ERR_INVALID_STATE", "Channel already opted out")
    channel["opt_in_status"] = "OPTED_OUT"
    touch(channel)

    # Cascade: suppress in-flight notifications on this channel.
    affected_alerts = set()
    for n in db.notifications.values():
        if n["channel_id"] == chid and n["delivery_status"] in store.PENDING_STATES:
            suppress_notification(n)
            affected_alerts.add(n["alert_id"])

    for aid in affected_alerts:
        alert = db.alerts.get(aid)
        if alert is None:
            continue
        touch(alert)  # pending_count recompute = mutation
        if alert["status"] in {"DISPATCHING", "SENT"} and alert_pending_count(aid) == 0:
            close_alert(alert)

    return ok(s_channel(channel))


# ===========================================================================
# Groups
# ===========================================================================
@app.route("/groups", methods=["POST"])
def create_group():
    uid, role = auth()
    require(role, {"ContactAdmin"})
    body = json_body()
    name = req_str(body, "name")
    group = stamp_new({"name": name, "status": "OPEN"})
    db.groups[group["id"]] = group
    return ok(s_group(group), 201)


@app.route("/groups/<gid>", methods=["GET"])
def get_group(gid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Approver"})
    group = get_or_404(db.groups, gid, "ERR_GROUP_NOT_FOUND")
    return ok(s_group(group))


@app.route("/groups/<gid>/close", methods=["POST"])
def close_group(gid):
    uid, role = auth()
    require(role, {"ContactAdmin"})
    group = get_or_404(db.groups, gid, "ERR_GROUP_NOT_FOUND")
    if group["status"] != "OPEN":
        raise ApiError(409, "ERR_INVALID_STATE", "Group not OPEN")
    group["status"] = "CLOSED"
    touch(group)
    return ok(s_group(group))


# ===========================================================================
# Subscriptions
# ===========================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = auth()
    require(role, {"ContactAdmin", "Contact"})
    body = json_body()
    contact_id = req_str(body, "contact_id")
    sub_type = req_enum(body, "subscription_type", {"GROUP", "GEO"})

    group_id = None
    center_lat = center_lon = radius_m = None
    if sub_type == "GROUP":
        group_id = req_str(body, "group_id")
    else:
        center_lat = req_number(body, "center_lat")
        center_lon = req_number(body, "center_lon")
        radius_m = req_int(body, "radius_m")

    if role == "Contact" and uid != contact_id:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Contacts may only subscribe themselves")

    get_or_404(db.contacts, contact_id, "ERR_CONTACT_NOT_FOUND")

    group = None
    if sub_type == "GROUP":
        group = get_or_404(db.groups, group_id, "ERR_GROUP_NOT_FOUND")
        if group["status"] != "OPEN":
            raise ApiError(409, "ERR_GROUP_NOT_OPEN", "Group is not OPEN")

    # Duplicate ACTIVE subscription check.
    for s in db.subscriptions.values():
        if s["status"] != "ACTIVE" or s["contact_id"] != contact_id:
            continue
        if s["subscription_type"] != sub_type:
            continue
        if sub_type == "GROUP" and s["group_id"] == group_id:
            raise ApiError(409, "ERR_DUPLICATE_SUBSCRIPTION", "Duplicate active subscription")
        if (
            sub_type == "GEO"
            and s["center_lat"] == center_lat
            and s["center_lon"] == center_lon
        ):
            raise ApiError(409, "ERR_DUPLICATE_SUBSCRIPTION", "Duplicate active subscription")

    sub = stamp_new(
        {
            "contact_id": contact_id,
            "subscription_type": sub_type,
            "group_id": group_id,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "radius_m": radius_m,
            "status": "ACTIVE",
        }
    )
    db.subscriptions[sub["id"]] = sub
    if sub_type == "GROUP" and group is not None:
        touch(group)  # member_count recompute = mutation
    return ok(s_subscription(sub), 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Contact"})
    sub = get_or_404(db.subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if role == "Contact" and uid != sub["contact_id"]:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Not the owning contact")
    return ok(s_subscription(sub))


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Contact"})
    limit, offset = pagination()
    items = list(db.subscriptions.values())
    cid = request.args.get("contact_id")
    gid = request.args.get("group_id")
    stype = request.args.get("subscription_type")
    if cid is not None:
        items = [s for s in items if s["contact_id"] == cid]
    if gid is not None:
        items = [s for s in items if s["group_id"] == gid]
    if stype is not None:
        items = [s for s in items if s["subscription_type"] == stype]
    if role == "Contact":
        items = [s for s in items if s["contact_id"] == uid]
    window, total = paginate(items, limit, offset)
    return ok_list([s_subscription(s) for s in window], limit, offset, total)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Contact"})
    sub = get_or_404(db.subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if role == "Contact" and uid != sub["contact_id"]:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Not the owning contact")
    if sub["status"] != "ACTIVE":
        raise ApiError(409, "ERR_INVALID_STATE", "Subscription not ACTIVE")
    sub["status"] = "CANCELLED"
    touch(sub)
    if sub["subscription_type"] == "GROUP":
        group = db.groups.get(sub["group_id"])
        if group is not None:
            touch(group)  # member_count recompute
    return ok(s_subscription(sub))


# ===========================================================================
# Templates
# ===========================================================================
@app.route("/templates", methods=["POST"])
def create_template():
    uid, role = auth()
    require(role, {"ContactAdmin"})
    body = json_body()
    name = req_str(body, "name")
    default_severity = req_enum(body, "default_severity", SEVERITIES)
    bbl = body.get("body_by_language")
    if not isinstance(bbl, dict):
        bad("'body_by_language' must be an object")
    for k, v in bbl.items():
        if k not in LANGS or not isinstance(v, str):
            bad("'body_by_language' keys must be languages mapping to strings")
    tpl = stamp_new(
        {
            "name": name,
            "default_severity": default_severity,
            "body_by_language": bbl,
            "status": "DRAFT",
        }
    )
    db.templates[tpl["id"]] = tpl
    return ok(s_template(tpl), 201)


@app.route("/templates/<tid>", methods=["GET"])
def get_template(tid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher"})
    tpl = get_or_404(db.templates, tid, "ERR_TEMPLATE_NOT_FOUND")
    return ok(s_template(tpl))


@app.route("/templates/<tid>/publish", methods=["POST"])
def publish_template(tid):
    uid, role = auth()
    require(role, {"ContactAdmin"})
    tpl = get_or_404(db.templates, tid, "ERR_TEMPLATE_NOT_FOUND")
    if tpl["status"] != "DRAFT":
        raise ApiError(409, "ERR_INVALID_STATE", "Template not DRAFT")
    tpl["status"] = "PUBLISHED"
    touch(tpl)
    return ok(s_template(tpl))


# ===========================================================================
# Alerts
# ===========================================================================
@app.route("/alerts", methods=["POST"])
def create_alert():
    uid, role = auth()
    require(role, {"Dispatcher"})
    body = json_body()
    title = req_str(body, "title")
    severity = req_enum(body, "severity", SEVERITIES)
    channels = req_channels(body)
    target_type = req_enum(body, "target_type", {"GROUP", "GEO"})
    effective_from = req_datetime(body, "effective_from")
    effective_until = req_datetime(body, "effective_until")
    template_id = opt_str(body, "template_id", None)
    target_group_id = opt_str(body, "target_group_id", None)
    center_lat = opt_number(body, "center_lat", None)
    center_lon = opt_number(body, "center_lon", None)
    radius_m = None
    if "radius_m" in body and body["radius_m"] is not None:
        radius_m = req_int(body, "radius_m")

    alert = stamp_new(
        {
            "title": title,
            "severity": severity,
            "channels": channels,
            "template_id": template_id,
            "target_type": target_type,
            "target_group_id": target_group_id,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "radius_m": radius_m,
            "effective_from": effective_from,
            "effective_until": effective_until,
            "author_user_id": uid,
            "status": "DRAFT",
            "revision_count": 0,
            "estimated_reach": None,
            "delivered_reach": None,
            "sms_billable_segments": None,
            "source_incident_ref": None,
        }
    )
    db.alerts[alert["id"]] = alert
    return ok(s_alert(alert), 201)


@app.route("/alerts/<aid>", methods=["GET"])
def get_alert(aid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Approver", "Integrator"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    return ok(s_alert(alert))


@app.route("/alerts", methods=["GET"])
def list_alerts():
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Approver"})
    limit, offset = pagination()
    items = list(db.alerts.values())
    status = request.args.get("status")
    template_id = request.args.get("template_id")
    target_group_id = request.args.get("target_group_id")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if template_id is not None:
        items = [a for a in items if a["template_id"] == template_id]
    if target_group_id is not None:
        items = [a for a in items if a["target_group_id"] == target_group_id]
    window, total = paginate(items, limit, offset)
    return ok_list([s_alert(a) for a in window], limit, offset, total)


@app.route("/alerts/<aid>/localizations", methods=["POST"])
def add_localization(aid):
    uid, role = auth()
    require(role, {"Dispatcher"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    body = json_body()
    language = req_enum(body, "language", LANGS)
    message_text = req_str(body, "message_text")
    seg = ceil_div(len(message_text), SMS_SEGMENT_SIZE) if len(message_text) > 0 else 0
    loc = stamp_new(
        {
            "alert_id": alert["id"],
            "language": language,
            "message_text": message_text,
            "segment_count": seg,
        }
    )
    db.localizations[loc["id"]] = loc
    return ok(s_localization(loc), 201)


@app.route("/alerts/<aid>/localizations", methods=["GET"])
def list_localizations(aid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Approver"})
    get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    limit, offset = pagination()
    items = alert_localizations(aid)
    window, total = paginate(items, limit, offset)
    return ok_list([s_localization(l) for l in window], limit, offset, total)


@app.route("/alerts/<aid>/submit", methods=["POST"])
def submit_alert(aid):
    uid, role = auth()
    require(role, {"Dispatcher"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    if alert["status"] != "DRAFT":
        raise ApiError(409, "ERR_INVALID_STATE", "Alert not DRAFT")

    # Targeting completeness.
    if alert["target_type"] == "GROUP":
        if not alert["target_group_id"]:
            raise ApiError(422, "ERR_TARGET_REQUIRED", "target_group_id required")
    else:
        if alert["center_lat"] is None or alert["center_lon"] is None or alert["radius_m"] is None:
            raise ApiError(422, "ERR_TARGET_REQUIRED", "GEO target fields required")

    # Backing template must be published.
    if alert["template_id"] is not None:
        tpl = db.templates.get(alert["template_id"])
        if tpl is None or tpl["status"] != "PUBLISHED":
            raise ApiError(422, "ERR_TEMPLATE_NOT_PUBLISHED", "Template not published")

    # Effective window well-ordered.
    ef, eu = alert["effective_from"], alert["effective_until"]
    if ef is None or eu is None or not (ef < eu):
        raise ApiError(409, "ERR_INVALID_WINDOW", "effective_from must precede effective_until")

    # At least one localization.
    if not alert_localizations(aid):
        raise ApiError(400, "ERR_VALIDATION", "At least one localization required")

    alert["status"] = "PENDING_APPROVAL"
    touch(alert)
    return ok(s_alert(alert))


@app.route("/alerts/<aid>/approve", methods=["POST"])
def approve_alert(aid):
    uid, role = auth()
    require(role, {"Approver"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    if alert["status"] != "PENDING_APPROVAL":
        raise ApiError(409, "ERR_INVALID_STATE", "Alert not PENDING_APPROVAL")
    if uid == alert["author_user_id"]:
        raise ApiError(409, "ERR_SEGREGATION_OF_DUTIES", "Approver must differ from author")
    alert["status"] = "APPROVED"
    touch(alert)
    return ok(s_alert(alert))


@app.route("/alerts/<aid>/reject", methods=["POST"])
def reject_alert(aid):
    uid, role = auth()
    require(role, {"Approver"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    if alert["status"] != "PENDING_APPROVAL":
        raise ApiError(409, "ERR_INVALID_STATE", "Alert not PENDING_APPROVAL")
    if uid == alert["author_user_id"]:
        raise ApiError(409, "ERR_SEGREGATION_OF_DUTIES", "Rejecter must differ from author")
    json_body()  # optional reason ignored
    alert["status"] = "DRAFT"
    alert["revision_count"] += 1
    touch(alert)
    return ok(s_alert(alert))


@app.route("/alerts/<aid>/preview", methods=["POST"])
def preview_alert(aid):
    uid, role = auth()
    require(role, {"Dispatcher", "Approver"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    matched_active, eligible, plan = resolve_recipients(alert)

    throttled = set()
    if alert["severity"] != "CRITICAL":
        # per-channel new sends
        new_sends = {}
        for contact, ch in plan:
            new_sends[ch["channel_type"]] = new_sends.get(ch["channel_type"], 0) + 1
        over = set()
        for ct in set(alert["channels"]):
            gw = gateway_for_channel(ct)
            if gw is not None:
                projected = gateway_window_count(gw) + new_sends.get(ct, 0)
                if projected > gw["capacity_per_window"]:
                    over.add(ct)
        if over:
            for cid in eligible:
                chans = confirmed_requested_channels(cid, set(alert["channels"]))
                if chans and all(c["channel_type"] in over for c in chans):
                    throttled.add(cid)

    reachable = [c for c in eligible if c not in throttled]
    return ok(
        {
            "estimated_reach": len(reachable),
            "matched_contact_ids": sorted(eligible),
            "throttled_contact_ids": sorted(throttled),
        }
    )


@app.route("/alerts/<aid>/dispatch", methods=["POST"])
def dispatch_alert(aid):
    uid, role = auth()
    require(role, {"Dispatcher"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    body = json_body()
    expected = body.get("expected_alert_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        bad("'expected_alert_version' is required and must be an integer")

    # State validity.
    if alert["status"] != "APPROVED":
        raise ApiError(409, "ERR_INVALID_STATE", "Alert not APPROVED")

    # OCC.
    if expected != alert["version"]:
        raise ApiError(412, "ERR_STALE_VERSION", "expected_alert_version mismatch")

    requested = set(alert["channels"])
    matched_active, eligible, plan = resolve_recipients(alert)

    # Accessibility: every matched-active tty_required contact needs a CONFIRMED
    # tty_capable channel among the requested channel types.
    for cid in matched_active:
        contact = db.contacts[cid]
        if not contact["tty_required"]:
            continue
        has_access = any(
            c["opt_in_status"] == "CONFIRMED"
            and c["tty_capable"]
            and c["channel_type"] in requested
            for c in db.channels.values()
            if c["contact_id"] == cid
        )
        if not has_access:
            raise ApiError(422, "ERR_ACCESSIBILITY_UNMET", "TTY accessibility unmet")

    # Effective window: clock in [effective_from, effective_until).
    ef, eu = alert["effective_from"], alert["effective_until"]
    if ef is None or eu is None or not (ef <= db.clock < eu):
        raise ApiError(422, "ERR_WINDOW_EXPIRED", "Outside effective window")

    # Throttle per requested channel type (bypassed for CRITICAL).
    if alert["severity"] != "CRITICAL":
        new_sends = {}
        for contact, ch in plan:
            new_sends[ch["channel_type"]] = new_sends.get(ch["channel_type"], 0) + 1
        for ct in requested:
            gw = gateway_for_channel(ct)
            if gw is not None:
                projected = gateway_window_count(gw) + new_sends.get(ct, 0)
                if projected > gw["capacity_per_window"]:
                    raise ApiError(409, "ERR_THROTTLE_EXCEEDED", "Throttle capacity exceeded")

    # Non-empty recipient set.
    if not eligible:
        raise ApiError(422, "ERR_NO_RECIPIENTS", "No recipients resolved")

    # Commit.
    alert["status"] = "DISPATCHING"
    reached_contacts = set()
    for contact, ch in plan:
        lang = language_for(alert, contact)
        n = stamp_new(
            {
                "alert_id": alert["id"],
                "contact_id": contact["id"],
                "channel_id": ch["id"],
                "channel_type": ch["channel_type"],
                "language": lang,
                "delivery_status": "QUEUED",
                "receipt_status": "NONE",
                "attempt_count": 0,
                "next_retry_at": None,
            }
        )
        db.notifications[n["id"]] = n
        reached_contacts.add(contact["id"])

    alert["estimated_reach"] = len(reached_contacts)
    alert["sms_billable_segments"] = compute_sms_segments(alert["id"])
    touch(alert)  # single mutation: status + version + derived recompute
    return ok(s_alert(alert))


@app.route("/alerts/<aid>/cancel", methods=["POST"])
def cancel_alert(aid):
    uid, role = auth()
    require(role, {"Dispatcher"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    if alert["status"] not in {"DRAFT", "PENDING_APPROVAL", "APPROVED", "DISPATCHING", "SENT"}:
        raise ApiError(409, "ERR_INVALID_STATE", "Alert cannot be cancelled")
    for n in db.notifications.values():
        if n["alert_id"] == aid and n["delivery_status"] in store.PENDING_STATES:
            suppress_notification(n)
    alert["status"] = "CANCELLED"
    touch(alert)
    return ok(s_alert(alert))


@app.route("/alerts/<aid>/close", methods=["POST"])
def close_alert_endpoint(aid):
    uid, role = auth()
    require(role, {"Dispatcher"})
    alert = get_or_404(db.alerts, aid, "ERR_ALERT_NOT_FOUND")
    if alert["status"] != "SENT":
        raise ApiError(409, "ERR_INVALID_STATE", "Alert not SENT")
    close_alert(alert)
    return ok(s_alert(alert))


# ===========================================================================
# Notifications
# ===========================================================================
@app.route("/notifications/<nid>", methods=["GET"])
def get_notification(nid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Integrator", "Contact"})
    n = get_or_404(db.notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    if role == "Contact" and uid != n["contact_id"]:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Not the owning contact")
    return ok(s_notification(n))


@app.route("/notifications", methods=["GET"])
def list_notifications():
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Integrator", "Contact"})
    limit, offset = pagination()
    items = list(db.notifications.values())
    a = request.args.get("alert_id")
    c = request.args.get("contact_id")
    ch = request.args.get("channel_id")
    ds = request.args.get("delivery_status")
    if a is not None:
        items = [n for n in items if n["alert_id"] == a]
    if c is not None:
        items = [n for n in items if n["contact_id"] == c]
    if ch is not None:
        items = [n for n in items if n["channel_id"] == ch]
    if ds is not None:
        items = [n for n in items if n["delivery_status"] == ds]
    if role == "Contact":
        items = [n for n in items if n["contact_id"] == uid]
    window, total = paginate(items, limit, offset)
    return ok_list([s_notification(n) for n in window], limit, offset, total)


@app.route("/notifications/<nid>/delivery-report", methods=["POST"])
def delivery_report(nid):
    uid, role = auth()
    require(role, {"Integrator"})
    n = get_or_404(db.notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    body = json_body()
    outcome = req_enum(body, "outcome", {"DELIVERED", "FAILED"})
    if n["delivery_status"] != "SENT":
        raise ApiError(409, "ERR_INVALID_STATE", "Notification not SENT")
    alert = db.alerts.get(n["alert_id"])
    if outcome == "DELIVERED":
        n["delivery_status"] = "DELIVERED"
        touch(n)
        if alert is not None:
            touch(alert)  # pending_count recompute
            if alert["status"] == "SENT" and alert_pending_count(alert["id"]) == 0:
                close_alert(alert)
    else:
        n["delivery_status"] = "FAILED"
        touch(n)
    return ok(s_notification(n))


@app.route("/notifications/<nid>/acknowledge", methods=["POST"])
def acknowledge(nid):
    uid, role = auth()
    require(role, {"Contact"})
    n = get_or_404(db.notifications, nid, "ERR_NOTIFICATION_NOT_FOUND")
    if uid != n["contact_id"]:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Not the owning contact")
    if n["receipt_status"] != "NONE" or n["delivery_status"] not in {"SENT", "DELIVERED", "RETRYING"}:
        raise ApiError(409, "ERR_INVALID_STATE", "Notification cannot be acknowledged")
    was_sent = n["delivery_status"] == "SENT"
    n["receipt_status"] = "ACKNOWLEDGED"
    if was_sent:
        n["delivery_status"] = "DELIVERED"
    touch(n)
    if was_sent:
        alert = db.alerts.get(n["alert_id"])
        if alert is not None:
            touch(alert)
            if alert["status"] == "SENT" and alert_pending_count(alert["id"]) == 0:
                close_alert(alert)
    return ok(s_notification(n))


# ===========================================================================
# Gateways
# ===========================================================================
@app.route("/gateways", methods=["POST"])
def create_gateway():
    uid, role = auth()
    require(role, {"ContactAdmin"})
    body = json_body()
    name = req_str(body, "name")
    channel_type = req_enum(body, "channel_type", CHANNEL_TYPES)
    capacity = req_int(body, "capacity_per_window")
    if capacity < 0:
        bad("'capacity_per_window' must be >= 0")
    gw = stamp_new(
        {
            "name": name,
            "channel_type": channel_type,
            "capacity_per_window": capacity,
            "status": "ONLINE",
        }
    )
    db.gateways[gw["id"]] = gw
    return ok(s_gateway(gw), 201)


@app.route("/gateways/<gid>", methods=["GET"])
def get_gateway(gid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Integrator"})
    gw = get_or_404(db.gateways, gid, "ERR_GATEWAY_NOT_FOUND")
    return ok(s_gateway(gw))


@app.route("/gateways/<gid>/toggle", methods=["POST"])
def toggle_gateway(gid):
    uid, role = auth()
    require(role, {"ContactAdmin"})
    gw = get_or_404(db.gateways, gid, "ERR_GATEWAY_NOT_FOUND")
    body = json_body()
    status = req_enum(body, "status", {"ONLINE", "OFFLINE"})
    gw["status"] = status
    touch(gw)
    return ok(s_gateway(gw))


@app.route("/gateways/<gid>/maintenance-windows", methods=["POST"])
def create_maintenance(gid):
    uid, role = auth()
    require(role, {"ContactAdmin"})
    gw = get_or_404(db.gateways, gid, "ERR_GATEWAY_NOT_FOUND")
    body = json_body()
    start_at = req_datetime(body, "start_at")
    end_at = req_datetime(body, "end_at")
    if not (start_at < end_at):
        bad("start_at must precede end_at")
    # Half-open [start, end): overlap if start < existing.end and existing.start < end.
    for w in db.maintenance_windows.values():
        if w["gateway_id"] != gid:
            continue
        if start_at < w["end_at"] and w["start_at"] < end_at:
            raise ApiError(422, "ERR_WINDOW_OVERLAP", "Maintenance window overlaps an existing one")
    w = stamp_new({"gateway_id": gid, "start_at": start_at, "end_at": end_at})
    db.maintenance_windows[w["id"]] = w
    return ok(s_maint(w), 201)


@app.route("/gateways/<gid>/maintenance-windows", methods=["GET"])
def list_maintenance(gid):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher", "Integrator"})
    get_or_404(db.gateways, gid, "ERR_GATEWAY_NOT_FOUND")
    limit, offset = pagination()
    items = [w for w in db.maintenance_windows.values() if w["gateway_id"] == gid]
    window, total = paginate(items, limit, offset)
    return ok_list([s_maint(w) for w in window], limit, offset, total)


# ===========================================================================
# Drills
# ===========================================================================
@app.route("/drills", methods=["POST"])
def create_drill():
    uid, role = auth()
    require(role, {"ContactAdmin"})
    body = json_body()
    group_id = req_str(body, "group_id")
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    get_or_404(db.groups, group_id, "ERR_GROUP_NOT_FOUND")
    if not (scheduled_start < scheduled_end):
        bad("scheduled_start must precede scheduled_end")
    buffer = timedelta(minutes=DRILL_BUFFER_MINUTES)
    for d in db.drills.values():
        if d["group_id"] != group_id or d["status"] != "SCHEDULED":
            continue
        # Require >= 30 min gap between the two closed intervals.
        gap_ok = (scheduled_start - d["scheduled_end"] >= buffer) or (
            d["scheduled_start"] - scheduled_end >= buffer
        )
        if not gap_ok:
            raise ApiError(422, "ERR_WINDOW_OVERLAP", "Drill violates group buffer gap")
    drill = stamp_new(
        {
            "group_id": group_id,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "status": "SCHEDULED",
        }
    )
    db.drills[drill["id"]] = drill
    return ok(s_drill(drill), 201)


@app.route("/drills/<did>", methods=["GET"])
def get_drill(did):
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher"})
    drill = get_or_404(db.drills, did, "ERR_DRILL_NOT_FOUND")
    return ok(s_drill(drill))


@app.route("/drills", methods=["GET"])
def list_drills():
    uid, role = auth()
    require(role, {"ContactAdmin", "Dispatcher"})
    limit, offset = pagination()
    items = list(db.drills.values())
    gid = request.args.get("group_id")
    status = request.args.get("status")
    if gid is not None:
        items = [d for d in items if d["group_id"] == gid]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    window, total = paginate(items, limit, offset)
    return ok_list([s_drill(d) for d in window], limit, offset, total)


@app.route("/drills/<did>/cancel", methods=["POST"])
def cancel_drill(did):
    uid, role = auth()
    require(role, {"ContactAdmin"})
    drill = get_or_404(db.drills, did, "ERR_DRILL_NOT_FOUND")
    if drill["status"] != "SCHEDULED":
        raise ApiError(409, "ERR_INVALID_STATE", "Drill not SCHEDULED")
    drill["status"] = "CANCELLED"
    touch(drill)
    return ok(s_drill(drill))


# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
