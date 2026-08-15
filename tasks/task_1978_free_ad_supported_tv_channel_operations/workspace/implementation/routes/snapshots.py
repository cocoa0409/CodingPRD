"""Channel-day snapshots."""

from db import store, new_id, next_seq, now_str, touch
from middleware import (
    caller,
    require_roles,
    body,
    ROLE_PLATFORM_ADMIN,
    ROLE_CHANNEL_PROGRAMMER,
)
from response import created, ok, paginate
from serializers import ser_snapshot
from services.core import get_or_404
from services.selector import compute_snapshot_fields
from util import req_date
from flask import Blueprint, request

bp = Blueprint("snapshots", __name__)


@bp.route("/v1/channels/<channel_id>/snapshot-computations", methods=["POST"])
def compute_snapshot(channel_id):
    _, role = caller()
    b = body()
    snapshot_date = req_date(b, "snapshot_date")
    require_roles(role, [ROLE_PLATFORM_ADMIN, ROLE_CHANNEL_PROGRAMMER])
    channel = get_or_404(store.channels, channel_id, "Channel")
    # Upsert: one snapshot per (channel, snapshot_date).
    existing = None
    for s in store.channel_day_snapshots.values():
        if s["channel_id"] == channel_id and s["snapshot_date"] == snapshot_date.isoformat():
            existing = s
            break
    if existing is None:
        ts = now_str()
        existing = {
            "id": new_id(),
            "channel_id": channel_id,
            "snapshot_date": snapshot_date.isoformat(),
            "watch_seconds": 0,
            "peak_concurrent_viewers": 0,
            "ad_impressions": 0,
            "direct_sold_impressions": 0,
            "capacity_seconds": 0,
            "direct_seconds": 0,
            "house_seconds": 0,
            "direct_fill_rate": None,
            "effective_fill_rate": None,
            "direct_revenue_cents": 0,
            "ecpm_cents": 0,
            "performance_score": 0,
            "computed_at": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": next_seq(),
        }
        store.channel_day_snapshots[existing["id"]] = existing
    compute_snapshot_fields(existing, channel, snapshot_date)
    existing["computed_at"] = now_str()
    # First compute leaves version at 1; recomputation upserts the same record
    # and increments its version.
    if existing.get("_computed_once"):
        touch(existing)
    else:
        existing["updated_at"] = now_str()
    existing["_computed_once"] = True
    return created(ser_snapshot(existing))


@bp.route("/v1/channel-day-snapshots", methods=["GET"])
def list_snapshots():
    caller()
    recs = list(store.channel_day_snapshots.values())
    fc = request.args.get("channel_id")
    fs = request.args.get("snapshot_date")
    if fc is not None:
        recs = [r for r in recs if r["channel_id"] == fc]
    if fs is not None:
        recs = [r for r in recs if r["snapshot_date"] == fs]
    return paginate(recs, ser_snapshot)


@bp.route("/v1/channel-day-snapshots/<snapshot_id>", methods=["GET"])
def get_snapshot(snapshot_id):
    caller()
    rec = get_or_404(store.channel_day_snapshots, snapshot_id, "ChannelDaySnapshot")
    return ok(ser_snapshot(rec))
