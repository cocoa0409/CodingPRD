"""Channel lifecycle, ops-run checkpoint, and the test-driving clock."""

from db import store, new_id, next_seq, now, now_str, today, touch, set_clock
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_CHANNEL_POSTURE_FROZEN,
)
from middleware import caller, require_roles, body, ROLE_PLATFORM_ADMIN, ALL_ROLES
from response import created, ok, paginate
from serializers import ser_channel
from services.core import (
    get_or_404,
    recompute_posture,
    content_reevaluate,
)
from util import req_str, opt_int, req_datetime
from flask import Blueprint

bp = Blueprint("channels", __name__)


def _create_record(fields):
    ts = now_str()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


@bp.route("/v1/channels", methods=["POST"])
def create_channel():
    _, role = caller()
    b = body()
    name = req_str(b, "name")
    genre = req_str(b, "genre")
    timezone = req_str(b, "timezone")
    loop_duration = opt_int(b, "loop_duration_seconds")
    if loop_duration is None:
        loop_duration = 86400
    elif loop_duration <= 0:
        raise_err(ERR_INVALID_REQUEST, "loop_duration_seconds must be > 0")
    cadence = opt_int(b, "refresh_cadence_days")
    if cadence is None:
        cadence = 7
    elif cadence <= 0:
        raise_err(ERR_INVALID_REQUEST, "refresh_cadence_days must be > 0")
    sep = opt_int(b, "ad_separation_window_seconds")
    if sep is None:
        sep = 600
    elif sep < 0:
        raise_err(ERR_INVALID_REQUEST, "ad_separation_window_seconds must be >= 0")
    avg_imps = opt_int(b, "avg_slot_impressions")
    if avg_imps is None:
        avg_imps = 1000
    elif avg_imps <= 0:
        raise_err(ERR_INVALID_REQUEST, "avg_slot_impressions must be > 0")
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    rec = _create_record(
        {
            "name": name,
            "genre": genre,
            "timezone": timezone,
            "loop_duration_seconds": loop_duration,
            "refresh_cadence_days": cadence,
            "ad_separation_window_seconds": sep,
            "avg_slot_impressions": avg_imps,
            "channel_status": "DRAFT",
            "channel_posture": "ACTIVE",
            "ops_run_index": 0,
            "last_published_on": None,
            "_last_published_date": None,
        }
    )
    store.channels[rec["id"]] = rec
    return created(ser_channel(rec))


@bp.route("/v1/channels", methods=["GET"])
def list_channels():
    caller()
    recs = list(store.channels.values())
    fs = _filter_args("channel_status")
    fp = _filter_args("channel_posture")
    if fs is not None:
        recs = [r for r in recs if r["channel_status"] == fs]
    if fp is not None:
        recs = [r for r in recs if r["channel_posture"] == fp]
    return paginate(recs, ser_channel)


def _filter_args(name):
    from flask import request

    return request.args.get(name)


@bp.route("/v1/channels/<channel_id>", methods=["GET"])
def get_channel(channel_id):
    caller()
    rec = get_or_404(store.channels, channel_id, "Channel")
    return ok(ser_channel(rec))


def _transition(channel_id, from_states, to_state, extra=None):
    _, role = caller()
    body()  # tolerated; no required payload
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    ch = get_or_404(store.channels, channel_id, "Channel")
    if ch["channel_status"] not in from_states:
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Channel in %s cannot perform this transition" % ch["channel_status"],
        )
    if extra:
        extra(ch)
    ch["channel_status"] = to_state
    touch(ch)
    return ok(ser_channel(ch))


@bp.route("/v1/channels/<channel_id>/go-live", methods=["POST"])
def go_live(channel_id):
    def pre(ch):
        for loop in store.playlist_loops.values():
            if (
                loop["channel_id"] == ch["id"]
                and loop["loop_status"] in ("LOCKED", "PUBLISHED")
                and loop["_broadcast_date"] >= today()
            ):
                return
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Go-live requires a LOCKED or PUBLISHED loop with broadcast_date >= current date",
        )

    return _transition(channel_id, ("DRAFT",), "LIVE", pre)


@bp.route("/v1/channels/<channel_id>/suspend", methods=["POST"])
def suspend(channel_id):
    return _transition(channel_id, ("LIVE",), "SUSPENDED")


@bp.route("/v1/channels/<channel_id>/resume", methods=["POST"])
def resume(channel_id):
    def pre(ch):
        if ch["channel_posture"] == "FROZEN":
            raise_err(ERR_CHANNEL_POSTURE_FROZEN, "Cannot resume while posture is FROZEN")

    return _transition(channel_id, ("SUSPENDED",), "LIVE", pre)


@bp.route("/v1/channels/<channel_id>/take-offline", methods=["POST"])
def take_offline(channel_id):
    # Posture is held as-is while OFFLINE (no recompute).
    return _transition(channel_id, ("LIVE", "SUSPENDED"), "OFFLINE")


@bp.route("/v1/channels/<channel_id>/archive", methods=["POST"])
def archive(channel_id):
    def pre(ch):
        for loop in store.playlist_loops.values():
            if (
                loop["channel_id"] == ch["id"]
                and loop["loop_status"] == "PUBLISHED"
                and loop["_broadcast_date"] >= today()
            ):
                raise_err(
                    ERR_INVALID_STATE_TRANSITION,
                    "Cannot archive with a PUBLISHED loop dated on or after today",
                )

    return _transition(channel_id, ("OFFLINE",), "ARCHIVED", pre)


@bp.route("/v1/channels/<channel_id>/run-ops", methods=["POST"])
def run_ops(channel_id):
    _, role = caller()
    body()
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    ch = get_or_404(store.channels, channel_id, "Channel")
    current = now()
    affected_channel_ids = set()
    # Expire every rights grant whose window_end_utc is at or before the
    # current logical time (PENDING and ACTIVE alike), with the content
    # re-evaluation cascade for each.
    for g in list(store.rights_grants.values()):
        if g["grant_status"] in ("PENDING", "ACTIVE") and current >= g["_wend"]:
            g["grant_status"] = "EXPIRED"
            touch(g)
            affected_channel_ids.add(g["channel_id"])
            content = store.content_assets.get(g["content_id"])
            if content is not None:
                content_reevaluate(content)
    for cid in affected_channel_ids:
        other = store.channels.get(cid)
        if other is not None:
            recompute_posture(other)
    recompute_posture(ch)
    ch["ops_run_index"] += 1
    touch(ch)
    return ok(ser_channel(ch))


@bp.route("/v1/_clock/set-current-utc", methods=["POST"])
def set_current_utc():
    _, role = caller()
    b = body()
    to_dt = req_datetime(b, "to_iso8601")
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    if to_dt < now():
        raise_err(ERR_INVALID_REQUEST, "The logical clock never moves backward")
    set_clock(to_dt)
    return ok({})
