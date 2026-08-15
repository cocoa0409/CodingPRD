"""Playlist loops, entries, ad breaks, and the loop lifecycle."""

from db import store, new_id, next_seq, now_str, today, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REFERENCE_NOT_FOUND,
    ERR_CONTENT_NOT_AVAILABLE,
    ERR_RIGHTS_WINDOW_VIOLATION,
    ERR_PLAYS_EXHAUSTED,
    ERR_BROADCAST_DATE_IN_PAST,
    ERR_DUPLICATE_LOOP_DATE,
    ERR_LOOP_NOT_TILED,
    ERR_LOOP_OVERFLOW,
    ERR_BREAK_DURATION_INVALID,
    ERR_AD_CAPACITY_EXCEEDED,
    ERR_CHANNEL_NOT_LIVE,
    ERR_STALE_CHANNEL_VERSION,
)
from middleware import caller, require_roles, body, ROLE_CHANNEL_PROGRAMMER
from response import created, ok, no_content, paginate
from serializers import ser_loop, ser_entry, ser_break
from services.core import (
    SLOT_SECONDS,
    AD_CAPACITY_PCT,
    get_or_404,
    loop_entries,
    loop_breaks,
    break_decisions,
    recompute_walk,
    covering_grant,
    recompute_posture,
    content_reevaluate,
    ensure_loop_ops_allowed,
    ensure_posture_not_frozen,
    maybe_exhaust_campaign,
    maybe_revive_campaign,
    void_decision,
    loop_revert,
)
from util import req_str, req_date, req_int, is_int
from flask import Blueprint, request

bp = Blueprint("loops", __name__)

CP = [ROLE_CHANNEL_PROGRAMMER]


def _create_record(fields):
    ts = now_str()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}
    rec.update(fields)
    return rec


def _rights_check(loop, statuses):
    """Every entry's air window must be covered by a grant in `statuses`, and
    each covering grant must have enough remaining plays for all entries of
    that content it covers in this loop (equality allowed)."""
    entries = loop_entries(loop["id"])
    per_grant_needed = {}
    for e in entries:
        g = covering_grant(loop, e, statuses)
        if g is None:
            raise_err(
                ERR_RIGHTS_WINDOW_VIOLATION,
                "Entry air window is not contained in any covering grant window",
            )
        per_grant_needed[g["id"]] = per_grant_needed.get(g["id"], 0) + 1
    for gid, needed in per_grant_needed.items():
        g = store.rights_grants[gid]
        if g["plays_used"] + needed > g["max_plays"]:
            raise_err(
                ERR_PLAYS_EXHAUSTED,
                "Aggregate plays needed by the loop exceed the covering grant's remaining plays",
            )
    return per_grant_needed


# ---------------------------------------------------------------------------
# Loops
# ---------------------------------------------------------------------------

@bp.route("/v1/playlist-loops", methods=["POST"])
def create_loop():
    _, role = caller()
    b = body()
    channel_id = req_str(b, "channel_id")
    broadcast_date = req_date(b, "broadcast_date")
    require_roles(role, CP)
    if channel_id not in store.channels:
        raise_err(ERR_REFERENCE_NOT_FOUND, "channel_id does not reference an existing channel")
    # Tier 11 (temporal) runs before tier 12 (uniqueness).
    if broadcast_date < today():
        raise_err(ERR_BROADCAST_DATE_IN_PAST, "broadcast_date is earlier than the current logical date")
    for loop in store.playlist_loops.values():
        if (
            loop["channel_id"] == channel_id
            and loop["broadcast_date"] == broadcast_date.isoformat()
            and loop["loop_status"] in ("DRAFT", "VALIDATED", "LOCKED")
        ):
            raise_err(ERR_DUPLICATE_LOOP_DATE, "A loop already exists for (channel, broadcast_date)")
    rec = _create_record(
        {
            "channel_id": channel_id,
            "broadcast_date": broadcast_date.isoformat(),
            "loop_status": "DRAFT",
            "used_seconds": 0,
            "validated_at": None,
            "published_at": None,
            "supersedes_loop_id": None,
            "_broadcast_date": broadcast_date,
        }
    )
    store.playlist_loops[rec["id"]] = rec
    return created(ser_loop(rec))


@bp.route("/v1/playlist-loops", methods=["GET"])
def list_loops():
    caller()
    recs = list(store.playlist_loops.values())
    fc = request.args.get("channel_id")
    fs = request.args.get("loop_status")
    fb = request.args.get("broadcast_date")
    fsup = request.args.get("supersedes_loop_id")
    if fc is not None:
        recs = [r for r in recs if r["channel_id"] == fc]
    if fs is not None:
        recs = [r for r in recs if r["loop_status"] == fs]
    if fb is not None:
        recs = [r for r in recs if r["broadcast_date"] == fb]
    if fsup is not None:
        recs = [r for r in recs if r["supersedes_loop_id"] == fsup]
    return paginate(recs, ser_loop)


@bp.route("/v1/playlist-loops/<loop_id>", methods=["GET"])
def get_loop(loop_id):
    caller()
    rec = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    return ok(ser_loop(rec))


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

@bp.route("/v1/playlist-loops/<loop_id>/entries", methods=["POST"])
def add_entry(loop_id):
    _, role = caller()
    b = body()
    content_id = req_str(b, "content_id")
    require_roles(role, CP)
    loop = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    if content_id not in store.content_assets:
        raise_err(ERR_REFERENCE_NOT_FOUND, "content_id does not reference an existing content asset")
    if loop["loop_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Entries may only be added while the loop is DRAFT")
    channel = store.channels[loop["channel_id"]]
    ensure_loop_ops_allowed(channel)
    content = store.content_assets[content_id]
    if content["content_status"] != "AVAILABLE":
        raise_err(ERR_CONTENT_NOT_AVAILABLE, "Entry content is not AVAILABLE")
    if loop["used_seconds"] + content["runtime_seconds"] > channel["loop_duration_seconds"]:
        raise_err(ERR_LOOP_OVERFLOW, "Adding the entry would push used_seconds beyond the loop duration")
    rec = _create_record(
        {
            "loop_id": loop["id"],
            "content_id": content_id,
            "sequence_index": len(loop_entries(loop["id"])),
            "start_offset_seconds": 0,
            "end_offset_seconds": 0,
        }
    )
    store.playlist_entries[rec["id"]] = rec
    recompute_walk(loop)
    touch(loop)
    return created(ser_entry(rec))


@bp.route("/v1/playlist-entries", methods=["GET"])
def list_entries():
    caller()
    recs = list(store.playlist_entries.values())
    fl = request.args.get("loop_id")
    fc = request.args.get("content_id")
    if fl is not None:
        recs = [r for r in recs if r["loop_id"] == fl]
    if fc is not None:
        recs = [r for r in recs if r["content_id"] == fc]
    return paginate(recs, ser_entry)


@bp.route("/v1/playlist-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    caller()
    rec = get_or_404(store.playlist_entries, entry_id, "PlaylistEntry")
    return ok(ser_entry(rec))


@bp.route("/v1/playlist-entries/<entry_id>", methods=["DELETE"])
def delete_entry(entry_id):
    _, role = caller()
    require_roles(role, CP)
    rec = get_or_404(store.playlist_entries, entry_id, "PlaylistEntry")
    loop = store.playlist_loops[rec["loop_id"]]
    if loop["loop_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Entries may only be removed while the loop is DRAFT")
    ensure_loop_ops_allowed(store.channels[loop["channel_id"]])
    del store.playlist_entries[entry_id]
    # Compact sequence_index of remaining entries.
    remaining = loop_entries(loop["id"])
    for k, e in enumerate(remaining):
        if e["sequence_index"] != k:
            e["sequence_index"] = k
            touch(e)
    # Clamp every break's after_entry_index to [0, remaining entry count].
    n = len(remaining)
    for br in loop_breaks(loop["id"]):
        clamped = max(0, min(br["after_entry_index"], n))
        if br["after_entry_index"] != clamped:
            br["after_entry_index"] = clamped
            touch(br)
    recompute_walk(loop)
    touch(loop)
    return no_content()


# ---------------------------------------------------------------------------
# Ad breaks
# ---------------------------------------------------------------------------

@bp.route("/v1/playlist-loops/<loop_id>/ad-breaks", methods=["POST"])
def mark_break(loop_id):
    _, role = caller()
    b = body()
    duration = req_int(b, "duration_seconds")
    require_roles(role, CP)
    loop = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    if loop["loop_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Breaks may only be marked while the loop is DRAFT")
    channel = store.channels[loop["channel_id"]]
    ensure_loop_ops_allowed(channel)
    if duration % SLOT_SECONDS != 0 or duration < 30 or duration > 240:
        raise_err(ERR_BREAK_DURATION_INVALID, "Break duration must be a multiple of 30 within [30, 240]")
    if loop["used_seconds"] + duration > channel["loop_duration_seconds"]:
        raise_err(ERR_LOOP_OVERFLOW, "Marking the break would push used_seconds beyond the loop duration")
    current_break_seconds = sum(x["duration_seconds"] for x in loop_breaks(loop["id"]))
    capacity = (channel["loop_duration_seconds"] * AD_CAPACITY_PCT) // 100
    if current_break_seconds + duration > capacity:
        raise_err(ERR_AD_CAPACITY_EXCEEDED, "Total break seconds would exceed 25% of the loop duration")
    entries = loop_entries(loop["id"])
    rec = _create_record(
        {
            "loop_id": loop["id"],
            "duration_seconds": duration,
            "after_entry_index": len(entries),
            "sequence_index": len(loop_breaks(loop["id"])),
            "start_offset_seconds": 0,
            "break_status": "MARKED",
            "slots": duration // SLOT_SECONDS,
            "direct_seconds": 0,
            "house_seconds": 0,
            "slate_seconds": duration,
        }
    )
    store.ad_breaks[rec["id"]] = rec
    recompute_walk(loop)
    touch(loop)
    return created(ser_break(rec))


@bp.route("/v1/ad-breaks", methods=["GET"])
def list_breaks():
    caller()
    recs = list(store.ad_breaks.values())
    fl = request.args.get("loop_id")
    fs = request.args.get("break_status")
    if fl is not None:
        recs = [r for r in recs if r["loop_id"] == fl]
    if fs is not None:
        recs = [r for r in recs if r["break_status"] == fs]
    return paginate(recs, ser_break)


@bp.route("/v1/ad-breaks/<break_id>", methods=["GET"])
def get_break(break_id):
    caller()
    rec = get_or_404(store.ad_breaks, break_id, "AdBreak")
    return ok(ser_break(rec))


@bp.route("/v1/ad-breaks/<break_id>", methods=["DELETE"])
def delete_break(break_id):
    _, role = caller()
    require_roles(role, CP)
    rec = get_or_404(store.ad_breaks, break_id, "AdBreak")
    loop = store.playlist_loops[rec["loop_id"]]
    if loop["loop_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Breaks may only be removed while the loop is DRAFT")
    ensure_loop_ops_allowed(store.channels[loop["channel_id"]])
    del store.ad_breaks[break_id]
    remaining = loop_breaks(loop["id"])
    for k, br in enumerate(remaining):
        if br["sequence_index"] != k:
            br["sequence_index"] = k
            touch(br)
    recompute_walk(loop)
    touch(loop)
    return no_content()


# ---------------------------------------------------------------------------
# Loop lifecycle
# ---------------------------------------------------------------------------

@bp.route("/v1/playlist-loops/<loop_id>/validate", methods=["POST"])
def validate_loop(loop_id):
    _, role = caller()
    body()
    require_roles(role, CP)
    loop = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    if loop["loop_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT loop can be validated")
    channel = store.channels[loop["channel_id"]]
    ensure_posture_not_frozen(channel)
    ensure_loop_ops_allowed(channel)
    # Tier 9: every entry's content AVAILABLE.
    for e in loop_entries(loop["id"]):
        content = store.content_assets.get(e["content_id"])
        if content is None or content["content_status"] != "AVAILABLE":
            raise_err(ERR_CONTENT_NOT_AVAILABLE, "Entry content is not AVAILABLE")
    # Tier 10: rights coverage with PENDING or ACTIVE grants, aggregate plays.
    _rights_check(loop, ("PENDING", "ACTIVE"))
    # Tier 12: exact tiling and ad capacity.
    if loop["used_seconds"] != channel["loop_duration_seconds"]:
        raise_err(ERR_LOOP_NOT_TILED, "used_seconds must equal loop_duration_seconds exactly")
    break_seconds = sum(x["duration_seconds"] for x in loop_breaks(loop["id"]))
    capacity = (channel["loop_duration_seconds"] * AD_CAPACITY_PCT) // 100
    if break_seconds > capacity:
        raise_err(ERR_AD_CAPACITY_EXCEEDED, "Total break seconds exceed 25% of the loop duration")
    loop["loop_status"] = "VALIDATED"
    loop["validated_at"] = now_str()
    touch(loop)
    return ok(ser_loop(loop))


@bp.route("/v1/playlist-loops/<loop_id>/revert-to-draft", methods=["POST"])
def revert_to_draft(loop_id):
    _, role = caller()
    body()
    require_roles(role, CP)
    loop = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    if loop["loop_status"] != "VALIDATED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a VALIDATED loop can be reverted to DRAFT")
    ensure_loop_ops_allowed(store.channels[loop["channel_id"]])
    loop_revert(loop)
    return ok(ser_loop(loop))


@bp.route("/v1/playlist-loops/<loop_id>/lock", methods=["POST"])
def lock_loop(loop_id):
    _, role = caller()
    body()
    require_roles(role, CP)
    loop = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    if loop["loop_status"] != "VALIDATED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a VALIDATED loop can be locked")
    channel = store.channels[loop["channel_id"]]
    ensure_posture_not_frozen(channel)
    ensure_loop_ops_allowed(channel)
    for br in loop_breaks(loop["id"]):
        if br["break_status"] != "DECIDED":
            raise_err(ERR_INVALID_STATE_TRANSITION, "Every ad break must be DECIDED before lock")
    # Commit PROVISIONAL decisions in (break sequence_index, slot_index) order.
    pending = []
    for br in loop_breaks(loop["id"]):
        for d in break_decisions(br["id"]):
            if d["decision_status"] == "PROVISIONAL":
                pending.append((br["sequence_index"], d["slot_index"], d["_seq"], d))
    pending.sort(key=lambda t: (t[0], t[1], t[2]))
    for _, _, _, d in pending:
        if d["decision_status"] != "PROVISIONAL":
            continue  # voided by an exhaustion cascade earlier in this pass
        d["decision_status"] = "COMMITTED"
        touch(d)
        if d["fill_type"] == "DIRECT":
            campaign = store.ad_campaigns.get(d["campaign_id"])
            if campaign is not None:
                campaign["spent_cents"] += d["committed_cost_cents"]
                touch(campaign)
                maybe_exhaust_campaign(campaign)
    loop["loop_status"] = "LOCKED"
    touch(loop)
    return ok(ser_loop(loop))


@bp.route("/v1/playlist-loops/<loop_id>/unlock", methods=["POST"])
def unlock_loop(loop_id):
    _, role = caller()
    body()
    require_roles(role, CP)
    loop = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    if loop["loop_status"] != "LOCKED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a LOCKED loop can be unlocked")
    ensure_loop_ops_allowed(store.channels[loop["channel_id"]])
    for br in loop_breaks(loop["id"]):
        for d in break_decisions(br["id"]):
            if d["decision_status"] == "COMMITTED":
                d["decision_status"] = "PROVISIONAL"
                touch(d)
                if d["fill_type"] == "DIRECT":
                    campaign = store.ad_campaigns.get(d["campaign_id"])
                    if campaign is not None:
                        campaign["spent_cents"] = max(
                            0, campaign["spent_cents"] - d["committed_cost_cents"]
                        )
                        touch(campaign)
    # Revival check after all compensations.
    seen = set()
    for br in loop_breaks(loop["id"]):
        for d in break_decisions(br["id"]):
            if d["campaign_id"] and d["campaign_id"] not in seen:
                seen.add(d["campaign_id"])
                campaign = store.ad_campaigns.get(d["campaign_id"])
                if campaign is not None:
                    maybe_revive_campaign(campaign)
    loop["loop_status"] = "VALIDATED"
    touch(loop)
    return ok(ser_loop(loop))


@bp.route("/v1/playlist-loops/<loop_id>/publish", methods=["POST"])
def publish_loop(loop_id):
    _, role = caller()
    b = body()
    expected_version = b.get("expected_channel_version")
    if not is_int(expected_version):
        raise_err(ERR_INVALID_REQUEST, "expected_channel_version is required and must be an integer")
    require_roles(role, CP)
    loop = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    if loop["loop_status"] != "LOCKED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a LOCKED loop can be published")
    channel = store.channels[loop["channel_id"]]
    # Tier 7 channel guards.
    if channel["channel_status"] != "LIVE":
        raise_err(ERR_CHANNEL_NOT_LIVE, "Publish requires channel_status == LIVE")
    ensure_posture_not_frozen(channel)
    # Tier 8 OCC.
    if expected_version != channel["version"]:
        raise_err(ERR_STALE_CHANNEL_VERSION, "expected_channel_version does not match the channel's current version")
    # Tier 10: rights coverage with ACTIVE grants only, aggregate plays.
    per_grant_needed = _rights_check(loop, ("ACTIVE",))
    # Tier 11: broadcast date not in the past.
    if loop["_broadcast_date"] < today():
        raise_err(ERR_BROADCAST_DATE_IN_PAST, "broadcast_date is earlier than the current logical date")
    # --- side effects ---
    # Supersede any other PUBLISHED loop for the same (channel, date).
    superseded = None
    for other in store.playlist_loops.values():
        if (
            other["id"] != loop["id"]
            and other["channel_id"] == loop["channel_id"]
            and other["broadcast_date"] == loop["broadcast_date"]
            and other["loop_status"] == "PUBLISHED"
        ):
            superseded = other
            break
    if superseded is not None:
        superseded["loop_status"] = "SUPERSEDED"
        touch(superseded)
    loop["supersedes_loop_id"] = superseded["id"] if superseded is not None else None
    # Rights play consumption.
    for gid, count in per_grant_needed.items():
        g = store.rights_grants[gid]
        g["plays_used"] += count
        touch(g)
        if g["grant_status"] == "ACTIVE" and g["plays_used"] >= g["max_plays"]:
            g["grant_status"] = "EXHAUSTED"
            touch(g)
            content = store.content_assets.get(g["content_id"])
            if content is not None:
                content_reevaluate(content)
    # Channel bookkeeping + posture recompute (clears GUARDED).
    channel["last_published_on"] = today().isoformat()
    channel["_last_published_date"] = today()
    touch(channel)
    recompute_posture(channel)
    loop["loop_status"] = "PUBLISHED"
    loop["published_at"] = now_str()
    touch(loop)
    return ok(ser_loop(loop))


@bp.route("/v1/playlist-loops/<loop_id>/archive", methods=["POST"])
def archive_loop(loop_id):
    _, role = caller()
    body()
    require_roles(role, CP)
    loop = get_or_404(store.playlist_loops, loop_id, "PlaylistLoop")
    if loop["loop_status"] not in ("PUBLISHED", "SUPERSEDED"):
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PUBLISHED or SUPERSEDED loop can be archived")
    if loop["_broadcast_date"] >= today():
        raise_err(ERR_INVALID_STATE_TRANSITION, "broadcast_date must be in the past to archive")
    loop["loop_status"] = "ARCHIVED"
    touch(loop)
    return ok(ser_loop(loop))
