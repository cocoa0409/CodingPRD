"""The decision-run selector (decision_slot_allocation) and the revenue /
snapshot calculation engines."""

import calendar
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, new_id, next_seq, now_str, touch
from util import rhu_div, rate4, rhu_int
from services.core import (
    SLOT_SECONDS,
    loop_breaks,
    break_decisions,
)

WATCH_SECONDS_BONUS_THRESHOLD = 60000
ECPM_BONUS_THRESHOLD_CENTS = 2000
FILL_WEIGHT = 80


# ---------------------------------------------------------------------------
# Decision run selector
# ---------------------------------------------------------------------------

def _new_decision(break_id, slot_index, slots_spanned, fill_type,
                  creative_id, campaign_id, house_ad_id,
                  expected_impressions, committed_cost_cents):
    ts = now_str()
    rec = {
        "id": new_id(),
        "break_id": break_id,
        "slot_index": slot_index,
        "slots_spanned": slots_spanned,
        "fill_type": fill_type,
        "creative_id": creative_id,
        "campaign_id": campaign_id,
        "house_ad_id": house_ad_id,
        "expected_impressions": expected_impressions,
        "committed_cost_cents": committed_cost_cents,
        "actual_impressions": None,
        "reconciled_cost_cents": None,
        "decision_status": "PROVISIONAL",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    store.fill_decisions[rec["id"]] = rec
    return rec


def run_selector(br):
    """Greedy single pass over free slots ascending slot_index. DIRECT first,
    then the HOUSE waterfall; unfilled slots are slate (no decision rows)."""
    loop = store.playlist_loops[br["loop_id"]]
    channel = store.channels[loop["channel_id"]]
    broadcast_date = loop["_broadcast_date"]
    total_slots = br["duration_seconds"] // SLOT_SECONDS
    free = [True] * total_slots

    # Slots still occupied by surviving (non-voided) decisions, e.g. COMMITTED
    # decisions on a LOCKED loop during a re-decision.
    for d in break_decisions(br["id"]):
        if d["decision_status"] in ("PROVISIONAL", "COMMITTED", "RECONCILED"):
            for i in range(d["slot_index"], d["slot_index"] + d["slots_spanned"]):
                if 0 <= i < total_slots:
                    free[i] = False

    placed = []
    used_categories = set()

    # Competitive separation: IAB categories of PROVISIONAL/COMMITTED DIRECT
    # decisions on adjacent breaks of the same loop. gap == window counts as
    # adjacent (touching counts).
    window = channel["ad_separation_window_seconds"]
    this_start = br["start_offset_seconds"]
    this_end = this_start + br["duration_seconds"]
    adjacent_categories = set()
    for b2 in loop_breaks(loop["id"]):
        if b2["id"] == br["id"]:
            continue
        s2 = b2["start_offset_seconds"]
        e2 = s2 + b2["duration_seconds"]
        if s2 >= this_end:
            gap = s2 - this_end
        elif this_start >= e2:
            gap = this_start - e2
        else:
            gap = 0
        if gap <= window:
            for d in break_decisions(b2["id"]):
                if d["fill_type"] == "DIRECT" and d["decision_status"] in (
                    "PROVISIONAL",
                    "COMMITTED",
                ):
                    creative = store.ad_creatives.get(d["creative_id"])
                    if creative is not None:
                        adjacent_categories.add(creative["iab_category"])

    i = 0
    while i < total_slots:
        if not free[i]:
            i += 1
            continue
        run_len = 0
        while i + run_len < total_slots and free[i + run_len]:
            run_len += 1

        # ---- DIRECT pass at slot i ----
        candidates = []
        for creative in store.ad_creatives.values():
            if creative["creative_status"] != "APPROVED":
                continue
            campaign = store.ad_campaigns.get(creative["campaign_id"])
            if campaign is None or campaign["campaign_status"] != "ACTIVE":
                continue
            if not (
                campaign["_flight_start"]
                <= broadcast_date
                <= campaign["_flight_end"]
            ):
                continue
            span = creative["duration_seconds"] // SLOT_SECONDS
            if span < 1 or span > run_len:
                continue
            expected_impressions = channel["avg_slot_impressions"] * span
            committed_cost = rhu_div(
                campaign["cpm_cents"] * expected_impressions, 1000
            )
            if campaign["spent_cents"] + committed_cost > campaign["total_budget_cents"]:
                continue
            daily = 0
            for dd in store.fill_decisions.values():
                if (
                    dd["campaign_id"] == campaign["id"]
                    and dd["decision_status"] in ("PROVISIONAL", "COMMITTED")
                ):
                    dd_loop = store.playlist_loops.get(
                        store.ad_breaks[dd["break_id"]]["loop_id"]
                    )
                    if dd_loop is not None and dd_loop["_broadcast_date"] == broadcast_date:
                        daily += dd["committed_cost_cents"]
            if daily + committed_cost > campaign["daily_budget_cents"]:
                continue
            if (
                creative["iab_category"] in used_categories
                or creative["iab_category"] in adjacent_categories
            ):
                continue
            candidates.append((creative, campaign, span, committed_cost, expected_impressions))

        if candidates:
            # Ranking: cpm_cents DESC, priority DESC, creative.created_at ASC,
            # campaign.created_at ASC. Ids never participate.
            candidates.sort(
                key=lambda t: (
                    -t[1]["cpm_cents"],
                    -t[1]["priority"],
                    t[0]["created_at"],
                    t[0]["_seq"],
                    t[1]["created_at"],
                    t[1]["_seq"],
                )
            )
            creative, campaign, span, committed_cost, expected_impressions = candidates[0]
            placed.append(
                _new_decision(
                    br["id"], i, span, "DIRECT", creative["id"], campaign["id"],
                    None, expected_impressions, committed_cost,
                )
            )
            used_categories.add(creative["iab_category"])
            for j in range(i, i + span):
                free[j] = False
            i += span
            continue

        # ---- HOUSE waterfall at slot i ----
        house_candidates = []
        for h in store.house_ads.values():
            if h["house_ad_status"] != "ACTIVE":
                continue
            if h["channel_id"] is not None and h["channel_id"] != loop["channel_id"]:
                continue
            placements = 0
            for dd in store.fill_decisions.values():
                if dd["house_ad_id"] == h["id"] and dd["decision_status"] != "VOIDED":
                    dd_loop = store.playlist_loops.get(
                        store.ad_breaks[dd["break_id"]]["loop_id"]
                    )
                    if dd_loop is not None and dd_loop["_broadcast_date"] == broadcast_date:
                        placements += 1
            if placements < h["daily_impression_cap"]:
                house_candidates.append(h)
        if house_candidates:
            house_candidates.sort(
                key=lambda h: (-h["priority_weight"], h["created_at"], h["_seq"])
            )
            h = house_candidates[0]
            placed.append(
                _new_decision(br["id"], i, 1, "HOUSE", None, None, h["id"], 0, 0)
            )
            free[i] = False
            i += 1
            continue

        # Slate slot — no decision row.
        i += 1

    return placed


# ---------------------------------------------------------------------------
# Revenue report calculations
# ---------------------------------------------------------------------------

def compute_report_figures(report, variant):
    """cpm_revenue_attribution + revenue_share_statement.

    Round per (decision, platform) pair first, then sum rounded integers;
    the share rounds once at statement level. Variant selects the status
    filter: PROVISIONAL includes COMMITTED or RECONCILED; FINAL includes
    RECONCILED only."""
    agreement = store.distribution_agreements[report["agreement_id"]]
    year, month = map(int, report["period_month"].split("-"))
    last_day = calendar.monthrange(year, month)[1]

    included_statuses = (
        ("COMMITTED", "RECONCILED") if variant == "PROVISIONAL" else ("RECONCILED",)
    )

    gross = 0
    for loop in store.playlist_loops.values():
        if loop["channel_id"] != report["channel_id"]:
            continue
        bd = loop["_broadcast_date"]
        if bd.year != year or bd.month != month:
            continue
        for br in loop_breaks(loop["id"]):
            for d in break_decisions(br["id"]):
                if d["fill_type"] != "DIRECT" or d["decision_status"] not in included_statuses:
                    continue
                campaign = store.ad_campaigns.get(d["campaign_id"])
                if campaign is None:
                    continue
                imps = 0
                for ev in store.viewership_events.values():
                    if (
                        ev["event_type"] == "AD_IMPRESSION"
                        and ev["decision_id"] == d["id"]
                        and ev["platform_id"] == report["platform_id"]
                    ):
                        imps += ev["quantity"]
                gross += rhu_div(campaign["cpm_cents"] * imps, 1000)

    threshold = agreement["locked_tier_threshold_cents"]
    below = min(gross, threshold)
    above = max(0, gross - threshold)
    share_raw = (
        below * agreement["locked_rev_share_bps_below"]
        + above * agreement["locked_rev_share_bps_above"]
    )
    platform_share = max(
        rhu_div(share_raw, 10000), agreement["locked_minimum_guarantee_cents"]
    )
    net = gross - platform_share

    report["gross_revenue_cents"] = gross
    report["platform_share_cents"] = platform_share
    report["net_revenue_cents"] = net
    report["calculation_variant"] = variant


# ---------------------------------------------------------------------------
# Channel-day snapshot computation
# ---------------------------------------------------------------------------

def compute_snapshot_fields(snap, channel, snapshot_date):
    """All computed fields read the half-open day window
    [date 00:00:00Z, next day 00:00:00Z)."""
    wstart = datetime.combine(snapshot_date, time(0, 0, 0), tzinfo=timezone.utc)
    wend = wstart + timedelta(days=1)

    events = [
        e
        for e in store.viewership_events.values()
        if e["channel_id"] == channel["id"]
        and wstart <= e["_occurred"] < wend
    ]

    watch_seconds = sum(
        e["watch_seconds"] or 0 for e in events if e["event_type"] == "CONTENT_WATCH"
    )

    session_events = sorted(
        (e for e in events if e["event_type"] in ("SESSION_START", "SESSION_END")),
        key=lambda e: (e["_occurred"], e["created_at"], e["_seq"]),
    )
    running = 0
    peak = 0
    for e in session_events:
        running += 1 if e["event_type"] == "SESSION_START" else -1
        if running < 0:
            running = 0
        if running > peak:
            peak = running

    ad_impressions = 0
    direct_sold = 0
    for e in events:
        if e["event_type"] != "AD_IMPRESSION":
            continue
        qty = e["quantity"]
        ad_impressions += qty
        decision = store.fill_decisions.get(e["decision_id"] or "")
        if decision is not None and decision["fill_type"] == "DIRECT":
            direct_sold += qty

    published_loop = None
    for loop in store.playlist_loops.values():
        if (
            loop["channel_id"] == channel["id"]
            and loop["loop_status"] == "PUBLISHED"
            and loop["_broadcast_date"] == snapshot_date
        ):
            published_loop = loop
            break

    capacity_seconds = 0
    direct_seconds = 0
    house_seconds = 0
    direct_revenue = 0
    if published_loop is not None:
        for br in loop_breaks(published_loop["id"]):
            capacity_seconds += br["duration_seconds"]
            for d in break_decisions(br["id"]):
                if d["decision_status"] not in ("COMMITTED", "RECONCILED"):
                    continue
                if d["fill_type"] == "DIRECT":
                    direct_seconds += d["slots_spanned"] * SLOT_SECONDS
                    if d["decision_status"] == "RECONCILED":
                        direct_revenue += d["reconciled_cost_cents"] or 0
                    else:
                        direct_revenue += d["committed_cost_cents"]
                elif d["fill_type"] == "HOUSE":
                    house_seconds += d["slots_spanned"] * SLOT_SECONDS

    if capacity_seconds > 0:
        direct_fill_rate = rate4(direct_seconds, capacity_seconds)
        effective_fill_rate = rate4(direct_seconds + house_seconds, capacity_seconds)
    else:
        direct_fill_rate = Decimal("0.0000")
        effective_fill_rate = Decimal("0.0000")

    if direct_sold > 0:
        ecpm = rhu_div(direct_revenue * 1000, direct_sold)
    else:
        ecpm = 0

    score = rhu_int(direct_fill_rate * FILL_WEIGHT)
    if watch_seconds >= WATCH_SECONDS_BONUS_THRESHOLD:
        score += 20
    if ecpm >= ECPM_BONUS_THRESHOLD_CENTS:
        score += 20
    score = min(100, score)

    snap["watch_seconds"] = watch_seconds
    snap["peak_concurrent_viewers"] = peak
    snap["ad_impressions"] = ad_impressions
    snap["direct_sold_impressions"] = direct_sold
    snap["capacity_seconds"] = capacity_seconds
    snap["direct_seconds"] = direct_seconds
    snap["house_seconds"] = house_seconds
    snap["direct_fill_rate"] = direct_fill_rate
    snap["effective_fill_rate"] = effective_fill_rate
    snap["direct_revenue_cents"] = direct_revenue
    snap["ecpm_cents"] = ecpm
    snap["performance_score"] = score
