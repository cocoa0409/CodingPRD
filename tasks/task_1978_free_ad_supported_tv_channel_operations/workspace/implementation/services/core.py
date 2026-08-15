"""Core business logic: offset walk, cascades, posture recompute, rights
coverage, fill accounting."""

from datetime import datetime, time, timedelta, timezone

from db import store, today, touch
from errors import (
    raise_err,
    ERR_INVALID_STATE_TRANSITION,
    ERR_CHANNEL_POSTURE_FROZEN,
    ERR_NOT_FOUND,
)

SLOT_SECONDS = 30
AD_CAPACITY_PCT = 25
MAX_DISPUTE_ROUNDS = 3


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_or_404(collection, rid, label):
    rec = collection.get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "%s %s not found" % (label, rid))
    return rec


def loop_entries(loop_id):
    return sorted(
        (e for e in store.playlist_entries.values() if e["loop_id"] == loop_id),
        key=lambda e: (e["sequence_index"], e["_seq"]),
    )


def loop_breaks(loop_id):
    return sorted(
        (b for b in store.ad_breaks.values() if b["loop_id"] == loop_id),
        key=lambda b: (b["sequence_index"], b["_seq"]),
    )


def break_decisions(break_id):
    return sorted(
        (d for d in store.fill_decisions.values() if d["break_id"] == break_id),
        key=lambda d: (d["slot_index"], d["_seq"]),
    )


# ---------------------------------------------------------------------------
# Offset walk (loop_offset_walk calculation)
# ---------------------------------------------------------------------------

def recompute_walk(loop):
    """Deterministic offset walk: entries ascending sequence_index; breaks
    with after_entry_index == k are placed immediately before entry k,
    ascending break sequence_index; breaks with after_entry_index == entry
    count go after the last entry. used_seconds = final offset.

    The walk assigns derived layout values only — it never bumps versions or
    refreshes timestamps (offsets are computed layout, not resource
    modifications; the mutating endpoint touches the loop explicitly)."""
    entries = loop_entries(loop["id"])
    brks = loop_breaks(loop["id"])
    by_after = {}
    for b in brks:
        by_after.setdefault(b["after_entry_index"], []).append(b)
    for lst in by_after.values():
        lst.sort(key=lambda b: (b["sequence_index"], b["_seq"]))
    offset = 0
    n = len(entries)
    for k, entry in enumerate(entries):
        for b in by_after.get(k, []):
            b["start_offset_seconds"] = offset
            offset += b["duration_seconds"]
        content = store.content_assets.get(entry["content_id"])
        runtime = content["runtime_seconds"] if content else 0
        entry["start_offset_seconds"] = offset
        offset += runtime
        entry["end_offset_seconds"] = offset
    for b in by_after.get(n, []):
        b["start_offset_seconds"] = offset
        offset += b["duration_seconds"]
    loop["used_seconds"] = offset


# ---------------------------------------------------------------------------
# Air windows and rights coverage
# ---------------------------------------------------------------------------

def air_window(loop, entry):
    """Closed interval [broadcast_date + start_offset, broadcast_date +
    end_offset] as datetimes."""
    base = datetime.combine(
        loop["_broadcast_date"], time(0, 0, 0), tzinfo=timezone.utc
    )
    start = base + timedelta(seconds=entry["start_offset_seconds"])
    end = base + timedelta(seconds=entry["end_offset_seconds"])
    return start, end


def grant_covers_window(grant, astart, aend):
    """Half-open grant window contains the closed air window; an air window
    ending exactly at window_end_utc is permitted."""
    return grant["_wstart"] <= astart and aend <= grant["_wend"]


def covering_grant(loop, entry, statuses):
    """The unique grant for (content, channel) in one of `statuses` whose
    window contains the entry's air window, or None."""
    astart, aend = air_window(loop, entry)
    for g in store.rights_grants.values():
        if (
            g["content_id"] == entry["content_id"]
            and g["channel_id"] == loop["channel_id"]
            and g["grant_status"] in statuses
            and grant_covers_window(g, astart, aend)
        ):
            return g
    return None


def published_loop_has_uncovered_entry(channel_id, loop):
    """FROZEN rule coverage: an entry's air window is covered iff a grant for
    (content, channel) contains the window and is ACTIVE or EXHAUSTED (a grant
    exhausted by this loop's own publish legitimately paid for those plays;
    REVOKED/EXPIRED/PENDING grants never count)."""
    for e in loop_entries(loop["id"]):
        astart, aend = air_window(loop, e)
        ok = False
        for g in store.rights_grants.values():
            if (
                g["content_id"] == e["content_id"]
                and g["channel_id"] == channel_id
                and g["grant_status"] in ("ACTIVE", "EXHAUSTED")
                and grant_covers_window(g, astart, aend)
            ):
                ok = True
                break
        if not ok:
            return True
    return False


# ---------------------------------------------------------------------------
# Channel posture (channel_posture_recompute)
# ---------------------------------------------------------------------------

def recompute_posture(channel):
    """Derived gating dimension. OFFLINE/ARCHIVED channels hold posture as-is
    until archive. FROZEN > GUARDED > ACTIVE."""
    if channel["channel_status"] in ("OFFLINE", "ARCHIVED"):
        return
    frozen = False
    for loop in store.playlist_loops.values():
        if loop["channel_id"] != channel["id"] or loop["loop_status"] != "PUBLISHED":
            continue
        if published_loop_has_uncovered_entry(channel["id"], loop):
            frozen = True
            break
    if frozen:
        new_posture = "FROZEN"
    else:
        lpd = channel["_last_published_date"]
        if lpd is None and channel["channel_status"] == "LIVE":
            stale = True
        elif lpd is not None and today() > lpd + timedelta(
            days=channel["refresh_cadence_days"]
        ):
            stale = True
        else:
            stale = False
        new_posture = "GUARDED" if stale else "ACTIVE"
    if channel["channel_posture"] != new_posture:
        channel["channel_posture"] = new_posture
        touch(channel)


# ---------------------------------------------------------------------------
# Fill accounting on breaks
# ---------------------------------------------------------------------------

def recompute_break_fill(br, touch_break=True, collapse=True):
    """direct_seconds: PROVISIONAL/COMMITTED/RECONCILED DIRECT decisions;
    house_seconds: non-VOIDED HOUSE decisions; slate: the remainder. A DECIDED
    break left with no PROVISIONAL/COMMITTED decisions collapses to MARKED —
    but only on void cascades, never as part of a decision run itself."""
    ds = 0
    hs = 0
    remaining = False
    for d in break_decisions(br["id"]):
        st = d["decision_status"]
        if d["fill_type"] == "DIRECT" and st in ("PROVISIONAL", "COMMITTED", "RECONCILED"):
            ds += d["slots_spanned"] * SLOT_SECONDS
        if d["fill_type"] == "HOUSE" and st != "VOIDED":
            hs += d["slots_spanned"] * SLOT_SECONDS
        if st in ("PROVISIONAL", "COMMITTED"):
            remaining = True
    changed = (
        br["direct_seconds"] != ds
        or br["house_seconds"] != hs
        or br["slate_seconds"] != br["duration_seconds"] - ds - hs
    )
    br["direct_seconds"] = ds
    br["house_seconds"] = hs
    br["slate_seconds"] = br["duration_seconds"] - ds - hs
    if collapse and br["break_status"] == "DECIDED" and not remaining:
        br["break_status"] = "MARKED"
        changed = True
    if changed and touch_break:
        touch(br)


# ---------------------------------------------------------------------------
# Campaign spend helpers
# ---------------------------------------------------------------------------

def maybe_revive_campaign(campaign):
    """EXHAUSTED -> ACTIVE when spend drops below total and the flight end is
    on or after the current logical date."""
    if (
        campaign["campaign_status"] == "EXHAUSTED"
        and campaign["spent_cents"] < campaign["total_budget_cents"]
        and campaign["_flight_end"] >= today()
    ):
        campaign["campaign_status"] = "ACTIVE"
        touch(campaign)


def void_decision(d, refund=True, touch_break=True):
    """PROVISIONAL|COMMITTED -> VOIDED. COMMITTED refunds committed cost to
    the campaign's spent_cents (may revive an EXHAUSTED campaign). The parent
    break recomputes and collapses DECIDED -> MARKED when emptied."""
    was = d["decision_status"]
    if was not in ("PROVISIONAL", "COMMITTED"):
        return
    d["decision_status"] = "VOIDED"
    touch(d)
    if was == "COMMITTED" and refund and d["fill_type"] == "DIRECT":
        campaign = store.ad_campaigns.get(d["campaign_id"])
        if campaign is not None:
            campaign["spent_cents"] = max(
                0, campaign["spent_cents"] - d["committed_cost_cents"]
            )
            touch(campaign)
            maybe_revive_campaign(campaign)
    br = store.ad_breaks.get(d["break_id"])
    if br is not None:
        recompute_break_fill(br, touch_break=touch_break)


def exhaust_campaign(campaign):
    """ACTIVE -> EXHAUSTED cascade: void the campaign's remaining PROVISIONAL
    decisions; affected breaks recompute (DECIDED -> MARKED when emptied)."""
    if campaign["campaign_status"] != "EXHAUSTED":
        campaign["campaign_status"] = "EXHAUSTED"
        touch(campaign)
    for d in list(store.fill_decisions.values()):
        if d["campaign_id"] == campaign["id"] and d["decision_status"] == "PROVISIONAL":
            void_decision(d)


def maybe_exhaust_campaign(campaign):
    if (
        campaign["campaign_status"] == "ACTIVE"
        and campaign["spent_cents"] >= campaign["total_budget_cents"]
    ):
        exhaust_campaign(campaign)


def void_campaign_provisionals(campaign):
    """Pause/complete cascade: void PROVISIONAL decisions only."""
    for d in list(store.fill_decisions.values()):
        if d["campaign_id"] == campaign["id"] and d["decision_status"] == "PROVISIONAL":
            void_decision(d)


# ---------------------------------------------------------------------------
# Loop revert cascade
# ---------------------------------------------------------------------------

def loop_revert(loop):
    """VALIDATED|LOCKED -> DRAFT: provisional decisions voided without spend
    impact; committed decisions voided with a committed-cost refund (may
    revive EXHAUSTED campaigns); emptied DECIDED breaks fall back to MARKED
    with fill seconds recomputed."""
    for br in loop_breaks(loop["id"]):
        for d in break_decisions(br["id"]):
            if d["decision_status"] in ("PROVISIONAL", "COMMITTED"):
                void_decision(d)
        recompute_break_fill(br)
    if loop["loop_status"] != "DRAFT":
        loop["loop_status"] = "DRAFT"
        touch(loop)


def content_reevaluate(content):
    """When a grant leaves the usable set and no other grant for the content
    remains PENDING or ACTIVE, an AVAILABLE asset transitions to
    WINDOW_EXPIRED with the loop-revert cascade."""
    if content["content_status"] != "AVAILABLE":
        return
    for g in store.rights_grants.values():
        if g["content_id"] == content["id"] and g["grant_status"] in ("PENDING", "ACTIVE"):
            return
    content["content_status"] = "WINDOW_EXPIRED"
    touch(content)
    loops_with_content = {
        e["loop_id"]
        for e in store.playlist_entries.values()
        if e["content_id"] == content["id"]
    }
    for loop_id in loops_with_content:
        loop = store.playlist_loops.get(loop_id)
        if loop is not None and loop["loop_status"] in ("VALIDATED", "LOCKED"):
            loop_revert(loop)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def ensure_loop_ops_allowed(channel):
    """No loop operations are permitted while a channel is OFFLINE or
    ARCHIVED."""
    if channel["channel_status"] in ("OFFLINE", "ARCHIVED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "No loop operations are permitted while the channel is %s"
            % channel["channel_status"],
        )


def ensure_posture_not_frozen(channel):
    if channel["channel_posture"] == "FROZEN":
        raise_err(ERR_CHANNEL_POSTURE_FROZEN, "Channel posture is FROZEN")
