"""Content assets and rights grants."""

from db import store, new_id, next_seq, now, now_str, today, touch
from db import fmt_dt
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REFERENCE_NOT_FOUND,
    ERR_CONTENT_NOT_AVAILABLE,
    ERR_INVALID_WINDOW,
    ERR_GRANT_WINDOW_OVERLAP,
)
from middleware import caller, require_roles, body, ROLE_CONTENT_LICENSING
from response import created, ok, paginate
from serializers import ser_content, ser_grant
from services.core import get_or_404, content_reevaluate, loop_revert, recompute_posture
from util import req_str, req_enum, req_int, req_datetime
from flask import Blueprint, request

bp = Blueprint("content", __name__)

CONTENT_TYPES = ("MOVIE", "EPISODE", "SHORT")
RATINGS = ("G", "PG", "PG13", "R", "TVMA")


def _create_record(fields):
    ts = now_str()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}
    rec.update(fields)
    return rec


# ---------------------------------------------------------------------------
# Content assets
# ---------------------------------------------------------------------------

@bp.route("/v1/content-assets", methods=["POST"])
def create_content():
    _, role = caller()
    b = body()
    title = req_str(b, "title")
    content_type = req_enum(b, "content_type", CONTENT_TYPES)
    runtime = req_int(b, "runtime_seconds")
    if runtime <= 0:
        raise_err(ERR_INVALID_REQUEST, "runtime_seconds must be > 0")
    rating = req_enum(b, "rating", RATINGS)
    genre = req_str(b, "genre")
    require_roles(role, [ROLE_CONTENT_LICENSING])
    rec = _create_record(
        {
            "title": title,
            "content_type": content_type,
            "runtime_seconds": runtime,
            "rating": rating,
            "genre": genre,
            "content_status": "INGESTING",
        }
    )
    store.content_assets[rec["id"]] = rec
    return created(ser_content(rec))


@bp.route("/v1/content-assets", methods=["GET"])
def list_content():
    caller()
    recs = list(store.content_assets.values())
    fs = request.args.get("content_status")
    fg = request.args.get("genre")
    if fs is not None:
        recs = [r for r in recs if r["content_status"] == fs]
    if fg is not None:
        recs = [r for r in recs if r["genre"] == fg]
    return paginate(recs, ser_content)


@bp.route("/v1/content-assets/<content_id>", methods=["GET"])
def get_content(content_id):
    caller()
    rec = get_or_404(store.content_assets, content_id, "ContentAsset")
    return ok(ser_content(rec))


def _content_transition(content_id, from_states, to_state, pre=None, cascade=None):
    _, role = caller()
    body()
    require_roles(role, [ROLE_CONTENT_LICENSING])
    rec = get_or_404(store.content_assets, content_id, "ContentAsset")
    if rec["content_status"] not in from_states:
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Content asset in %s cannot perform this transition" % rec["content_status"],
        )
    if pre:
        pre(rec)
    rec["content_status"] = to_state
    touch(rec)
    if cascade:
        cascade(rec)
    return ok(ser_content(rec))


@bp.route("/v1/content-assets/<content_id>/mark-available", methods=["POST"])
def mark_available(content_id):
    def pre(rec):
        if rec["runtime_seconds"] <= 0:
            raise_err(ERR_INVALID_STATE_TRANSITION, "runtime_seconds must be > 0")

    return _content_transition(content_id, ("INGESTING",), "AVAILABLE", pre)


def _loop_revert_cascade(rec):
    loops_with_content = {
        e["loop_id"]
        for e in store.playlist_entries.values()
        if e["content_id"] == rec["id"]
    }
    for loop_id in loops_with_content:
        loop = store.playlist_loops.get(loop_id)
        if loop is not None and loop["loop_status"] in ("VALIDATED", "LOCKED"):
            loop_revert(loop)


@bp.route("/v1/content-assets/<content_id>/pull", methods=["POST"])
def pull_content(content_id):
    return _content_transition(
        content_id, ("AVAILABLE",), "PULLED", cascade=_loop_revert_cascade
    )


@bp.route("/v1/content-assets/<content_id>/reinstate", methods=["POST"])
def reinstate_content(content_id):
    def pre(rec):
        for g in store.rights_grants.values():
            if g["content_id"] == rec["id"] and g["grant_status"] in ("PENDING", "ACTIVE"):
                return
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Reinstate requires at least one PENDING or ACTIVE rights grant",
        )

    return _content_transition(content_id, ("PULLED",), "AVAILABLE", pre)


@bp.route("/v1/content-assets/<content_id>/archive", methods=["POST"])
def archive_content(content_id):
    def pre(rec):
        for g in store.rights_grants.values():
            if g["content_id"] == rec["id"] and g["grant_status"] in ("PENDING", "ACTIVE"):
                raise_err(
                    ERR_INVALID_STATE_TRANSITION,
                    "Archive requires no PENDING or ACTIVE rights grants",
                )

    return _content_transition(content_id, ("PULLED",), "ARCHIVED", pre)


# ---------------------------------------------------------------------------
# Rights grants
# ---------------------------------------------------------------------------

@bp.route("/v1/rights-grants", methods=["POST"])
def create_grant():
    _, role = caller()
    b = body()
    channel_id = req_str(b, "channel_id")
    content_id = req_str(b, "content_id")
    wstart = req_datetime(b, "window_start_utc")
    wend = req_datetime(b, "window_end_utc")
    max_plays = req_int(b, "max_plays")
    if max_plays <= 0:
        raise_err(ERR_INVALID_REQUEST, "max_plays must be > 0")
    require_roles(role, [ROLE_CONTENT_LICENSING])
    # Body FK targets (tier 4)
    if channel_id not in store.channels:
        raise_err(ERR_REFERENCE_NOT_FOUND, "channel_id does not reference an existing channel")
    if content_id not in store.content_assets:
        raise_err(ERR_REFERENCE_NOT_FOUND, "content_id does not reference an existing content asset")
    # Temporal checks (tier 11)
    if wend <= wstart:
        raise_err(ERR_INVALID_WINDOW, "window_end_utc must be after window_start_utc")
    for g in store.rights_grants.values():
        if (
            g["content_id"] == content_id
            and g["channel_id"] == channel_id
            and g["grant_status"] in ("PENDING", "ACTIVE")
            and g["_wstart"] < wend
            and wstart < g["_wend"]
        ):
            raise_err(
                ERR_GRANT_WINDOW_OVERLAP,
                "Window overlaps a PENDING/ACTIVE grant for the same (content, channel)",
            )
    rec = _create_record(
        {
            "channel_id": channel_id,
            "content_id": content_id,
            "window_start_utc": fmt_dt(wstart),
            "window_end_utc": fmt_dt(wend),
            "max_plays": max_plays,
            "plays_used": 0,
            "grant_status": "PENDING",
            "_wstart": wstart,
            "_wend": wend,
        }
    )
    store.rights_grants[rec["id"]] = rec
    return created(ser_grant(rec))


@bp.route("/v1/rights-grants", methods=["GET"])
def list_grants():
    caller()
    recs = list(store.rights_grants.values())
    fc = request.args.get("channel_id")
    fct = request.args.get("content_id")
    fs = request.args.get("grant_status")
    if fc is not None:
        recs = [r for r in recs if r["channel_id"] == fc]
    if fct is not None:
        recs = [r for r in recs if r["content_id"] == fct]
    if fs is not None:
        recs = [r for r in recs if r["grant_status"] == fs]
    return paginate(recs, ser_grant)


@bp.route("/v1/rights-grants/<grant_id>", methods=["GET"])
def get_grant(grant_id):
    caller()
    rec = get_or_404(store.rights_grants, grant_id, "RightsGrant")
    return ok(ser_grant(rec))


@bp.route("/v1/rights-grants/<grant_id>/activate", methods=["POST"])
def activate_grant(grant_id):
    _, role = caller()
    body()
    require_roles(role, [ROLE_CONTENT_LICENSING])
    rec = get_or_404(store.rights_grants, grant_id, "RightsGrant")
    if rec["grant_status"] != "PENDING":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Grant in %s cannot be activated" % rec["grant_status"],
        )
    current = now()
    if not (rec["_wstart"] <= current < rec["_wend"]):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Grant window does not contain the current logical time",
        )
    channel = store.channels.get(rec["channel_id"])
    if channel is not None and channel["channel_status"] == "ARCHIVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Channel is ARCHIVED")
    content = store.content_assets.get(rec["content_id"])
    if content is None or content["content_status"] != "AVAILABLE":
        raise_err(ERR_CONTENT_NOT_AVAILABLE, "Content asset is not AVAILABLE")
    rec["grant_status"] = "ACTIVE"
    touch(rec)
    return ok(ser_grant(rec))


@bp.route("/v1/rights-grants/<grant_id>/revoke", methods=["POST"])
def revoke_grant(grant_id):
    _, role = caller()
    body()
    require_roles(role, [ROLE_CONTENT_LICENSING])
    rec = get_or_404(store.rights_grants, grant_id, "RightsGrant")
    if rec["grant_status"] not in ("PENDING", "ACTIVE"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Grant in %s cannot be revoked" % rec["grant_status"],
        )
    rec["grant_status"] = "REVOKED"
    touch(rec)
    # Channel FROZEN evaluation for the grant's channel.
    channel = store.channels.get(rec["channel_id"])
    if channel is not None:
        recompute_posture(channel)
    # Content re-evaluation (possible WINDOW_EXPIRED + loop-revert cascade).
    content = store.content_assets.get(rec["content_id"])
    if content is not None:
        content_reevaluate(content)
    return ok(ser_grant(rec))
