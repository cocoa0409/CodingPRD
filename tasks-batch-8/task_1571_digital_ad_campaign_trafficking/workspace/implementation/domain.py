"""Domain logic: serializers, aggregates, pacing, attribution, cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from core import (
    db, now_dt, today, render_ts, render_instant, rhu_int, rate4, ceil_dec,
    sorted_items, touch,
)

PACING_ALERT_RATIO = Fraction(9, 10)          # 0.90
TRAILING_WINDOW_DAYS = 3
DISCREPANCY_TOLERANCE = Decimal("0.10")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_io(io_id):
    return db.insertion_orders.get(io_id)


def get_li(li_id):
    return db.line_items.get(li_id)


def get_creative(cid):
    return db.creatives.get(cid)


def get_snapshot(sid):
    return db.snapshots.get(sid)


def get_vr(vid):
    return db.verification_reports.get(vid)


def get_mg(mid):
    return db.make_goods.get(mid)


def get_rec(rid):
    return db.reconciliations.get(rid)


def get_wrap(wid):
    return db.wrap_reports.get(wid)


def line_items_of_io(io_id):
    return [li for li in db.line_items.values() if li["io_id"] == io_id]


def creatives_of_li(li_id):
    return [c for c in db.creatives.values() if c["line_item_id"] == li_id]


def posted_snapshots(li_id):
    return [s for s in db.snapshots.values()
            if s["line_item_id"] == li_id and s["status"] == "POSTED"]


def reports_of_li(li_id):
    return [v for v in db.verification_reports.values() if v["line_item_id"] == li_id]


def make_goods_of_report(vid):
    return [m for m in db.make_goods.values() if m["verification_report_id"] == vid]


def recs_of_li(li_id):
    return [r for r in db.reconciliations.values() if r["line_item_id"] == li_id]


# ---------------------------------------------------------------------------
# Aggregates (computed on read so they can never go stale)
# ---------------------------------------------------------------------------
def budget_cents_of(li):
    return rhu_int(li["goal_impressions"] * li["cpm_rate_cents"], 1000)


def delivered(li_id):
    imps = sum(s["impressions"] for s in posted_snapshots(li_id))
    clicks = sum(s["clicks"] for s in posted_snapshots(li_id))
    spend = sum(s["spend_cents"] for s in posted_snapshots(li_id))
    return imps, clicks, spend


def io_booked_budget(io_id):
    return sum(budget_cents_of(li) for li in line_items_of_io(io_id)
               if li["status"] != "CANCELLED")


def io_applied_credit(io_id):
    total = 0
    for mg in db.make_goods.values():
        if mg["status"] != "APPLIED":
            continue
        if mg.get("credit_cents") is None:
            continue
        vr = get_vr(mg["verification_report_id"])
        if vr is None:
            continue
        li = get_li(vr["line_item_id"])
        if li is None or li["io_id"] != io_id:
            continue
        total += mg["credit_cents"]
    return total


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------
def pacing_fields(li):
    start = li["_start"]
    end = li["_end"]
    total_days = (end - start).days + 1
    elapsed = (today() - start).days
    elapsed = max(0, min(elapsed, total_days))
    remaining = total_days - elapsed
    imps, _clicks, _spend = delivered(li["id"])

    # Lifetime-average variant
    if elapsed == 0:
        proj = imps
    else:
        rate = Decimal(imps) / Decimal(elapsed)
        proj = int((Decimal(imps) + remaining * rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))

    # Trailing-3-day variant: window is [current_date - 2 days, current_date]
    cur = today()
    lo = cur - timedelta(days=TRAILING_WINDOW_DAYS - 1)
    window_sum = sum(s["impressions"] for s in posted_snapshots(li["id"])
                     if lo <= s["_date"] <= cur)
    trailing_rate = Decimal(window_sum) / Decimal(TRAILING_WINDOW_DAYS)
    proj_t = int((Decimal(imps) + remaining * trailing_rate).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))

    # Pacing alert: exact real comparison, no rounding
    if li["pacing_mode"] == "EVEN":
        expected = Fraction(li["goal_impressions"] * elapsed, total_days)
    else:  # ASAP
        expected = Fraction(li["goal_impressions"], 1)
    alert = Fraction(imps, 1) < PACING_ALERT_RATIO * expected

    return proj, proj_t, alert


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def io_view(io):
    return {
        "id": io["id"],
        "advertiser_name": io["advertiser_name"],
        "total_budget_cents": io["total_budget_cents"],
        "flight_start": io["flight_start"],
        "flight_end": io["flight_end"],
        "billing_basis": io["billing_basis"],
        "viewability_threshold_pct": io["viewability_threshold_pct"],
        "ivt_threshold_pct": io["ivt_threshold_pct"],
        "status": io["status"],
        "booked_budget_cents": io_booked_budget(io["id"]),
        "total_applied_credit_cents": io_applied_credit(io["id"]),
        "created_at": render_ts(io["_created_dt"]),
        "updated_at": render_ts(io["_updated_dt"]),
        "version": io["version"],
    }


def li_view(li):
    imps, clicks, spend = delivered(li["id"])
    proj, proj_t, alert = pacing_fields(li)
    return {
        "id": li["id"],
        "io_id": li["io_id"],
        "name": li["name"],
        "goal_impressions": li["goal_impressions"],
        "cpm_rate_cents": li["cpm_rate_cents"],
        "start_date": li["start_date"],
        "end_date": li["end_date"],
        "pacing_mode": li["pacing_mode"],
        "targeting": li["targeting"],
        "frequency_cap_max_impressions": li["frequency_cap_max_impressions"],
        "frequency_cap_window_hours": li["frequency_cap_window_hours"],
        "status": li["status"],
        "fraud_posture": li["fraud_posture"],
        "budget_cents": budget_cents_of(li),
        "delivered_impressions": imps,
        "delivered_clicks": clicks,
        "delivered_spend_cents": spend,
        "pacing_projection_impressions": proj,
        "pacing_projection_trailing_impressions": proj_t,
        "pacing_alert": alert,
        "created_at": render_ts(li["_created_dt"]),
        "updated_at": render_ts(li["_updated_dt"]),
        "version": li["version"],
    }


def creative_view(c):
    return {
        "id": c["id"],
        "line_item_id": c["line_item_id"],
        "name": c["name"],
        "asset_url": c["asset_url"],
        "width": c["width"],
        "height": c["height"],
        "ad_tag": c["ad_tag"],
        "qa_failure_reason": c["qa_failure_reason"],
        "status": c["status"],
        "created_at": render_ts(c["_created_dt"]),
        "updated_at": render_ts(c["_updated_dt"]),
        "version": c["version"],
    }


def snapshot_view(s):
    return {
        "id": s["id"],
        "line_item_id": s["line_item_id"],
        "snapshot_date": s["snapshot_date"],
        "impressions": s["impressions"],
        "clicks": s["clicks"],
        "spend_cents": s["spend_cents"],
        "status": s["status"],
        "created_at": render_ts(s["_created_dt"]),
    }


def event_view(e):
    return {
        "id": e["id"],
        "line_item_id": e["line_item_id"],
        "user_key": e["user_key"],
        "occurred_at": e["occurred_at"],
        "created_at": render_ts(e["_created_dt"]),
    }


def vr_view(vr):
    return {
        "id": vr["id"],
        "line_item_id": vr["line_item_id"],
        "vendor": vr["vendor"],
        "period_start": vr["period_start"],
        "period_end": vr["period_end"],
        "measured_impressions": vr["measured_impressions"],
        "viewable_impressions": vr["viewable_impressions"],
        "ivt_impressions": vr["ivt_impressions"],
        "viewability_rate": float(vr["_viewability_rate"]),
        "ivt_rate": float(vr["_ivt_rate"]),
        "assessment": vr["assessment"],
        "make_good_max_credit_cents": vr["make_good_max_credit_cents"],
        "status": vr["status"],
        "recorded_by_user_id": vr["recorded_by_user_id"],
        "created_at": render_ts(vr["_created_dt"]),
        "updated_at": render_ts(vr["_updated_dt"]),
        "version": vr["version"],
    }


def mg_view(mg):
    return {
        "id": mg["id"],
        "verification_report_id": mg["verification_report_id"],
        "kind": mg["kind"],
        "credit_cents": mg["credit_cents"],
        "bonus_impressions": mg["bonus_impressions"],
        "status": mg["status"],
        "proposed_by_user_id": mg["proposed_by_user_id"],
        "decided_by_user_id": mg["decided_by_user_id"],
        "created_at": render_ts(mg["_created_dt"]),
        "updated_at": render_ts(mg["_updated_dt"]),
        "version": mg["version"],
    }


def rec_view(r):
    disc = r["_discrepancy_pct"]
    return {
        "id": r["id"],
        "line_item_id": r["line_item_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "third_party_impressions": r["third_party_impressions"],
        "agency_impressions": r["agency_impressions"],
        "discrepancy_pct": (float(disc) if disc is not None else None),
        "billing_impressions": r["billing_impressions"],
        "billable_cents": r["billable_cents"],
        "status": r["status"],
        "reconciled_by_user_id": r["reconciled_by_user_id"],
        "locked_by_user_id": r["locked_by_user_id"],
        "created_at": render_ts(r["_created_dt"]),
        "updated_at": render_ts(r["_updated_dt"]),
        "version": r["version"],
    }


def wrap_view(w):
    return {
        "id": w["id"],
        "io_id": w["io_id"],
        "attribution_model": w["attribution_model"],
        "total_conversions": w["total_conversions"],
        "status": w["status"],
        "total_delivered_impressions": w["total_delivered_impressions"],
        "total_spend_cents": w["total_spend_cents"],
        "total_billable_cents": w["total_billable_cents"],
        "total_applied_credit_cents": w["total_applied_credit_cents"],
        "net_billable_cents": w["net_billable_cents"],
        "attribution": w["attribution"],
        "created_at": render_ts(w["_created_dt"]),
        "updated_at": render_ts(w["_updated_dt"]),
        "version": w["version"],
    }


# ---------------------------------------------------------------------------
# Cascades / shared transitions
# ---------------------------------------------------------------------------
def archive_creative(c):
    c["status"] = "ARCHIVED"
    touch(c)


def pause_creative(c):
    c["status"] = "PAUSED"
    touch(c)


def activate_creative(c):
    c["status"] = "LIVE"
    touch(c)


def cancel_line_item(li):
    """LineItem -> CANCELLED with creative archive cascade."""
    for c in creatives_of_li(li["id"]):
        if c["status"] != "ARCHIVED":
            archive_creative(c)
    li["status"] = "CANCELLED"
    touch(li)


def complete_line_item(li):
    """LineItem -> COMPLETED; creatives in LIVE/PAUSED are archived."""
    for c in creatives_of_li(li["id"]):
        if c["status"] in ("LIVE", "PAUSED"):
            archive_creative(c)
    li["status"] = "COMPLETED"
    touch(li)


def pause_line_item(li):
    """LineItem LIVE -> PAUSED with creative pause cascade."""
    for c in creatives_of_li(li["id"]):
        if c["status"] == "LIVE":
            pause_creative(c)
    li["status"] = "PAUSED"
    touch(li)


def maybe_auto_complete(li):
    """After a snapshot post: LIVE line item meeting its goal auto-completes."""
    if li["status"] != "LIVE":
        return
    imps, _c, _s = delivered(li["id"])
    if imps >= li["goal_impressions"]:
        complete_line_item(li)


def fire_fraud_cascade(li):
    """IVT breach: fraud_posture := BREACH; LIVE line item auto-pauses."""
    li["fraud_posture"] = "BREACH"
    if li["status"] == "LIVE":
        pause_line_item(li)  # bumps version, pauses LIVE creatives
    else:
        touch(li)


# ---------------------------------------------------------------------------
# Reconciliation computation
# ---------------------------------------------------------------------------
def agency_impressions_for(li_id, ps, pe):
    """Sum of POSTED snapshot impressions with snapshot_date in [ps, pe)."""
    return sum(s["impressions"] for s in posted_snapshots(li_id)
               if ps <= s["_date"] < pe)


def reconcile_compute(rec):
    """Recompute agency_impressions / discrepancy / billing / billable."""
    li = get_li(rec["line_item_id"])
    io = get_io(li["io_id"])
    agency = agency_impressions_for(li["id"], rec["_ps"], rec["_pe"])
    rec["agency_impressions"] = agency
    tp = rec["third_party_impressions"]
    if agency == 0:
        disc = None
    else:
        disc = rate4(tp - agency, agency)
    rec["_discrepancy_pct"] = disc
    basis = io["billing_basis"]
    if basis == "AGENCY_PLATFORM":
        billing = agency
    elif basis == "THIRD_PARTY_TAG":
        billing = tp
    else:  # LOWER_OF
        if agency == 0:
            billing = 0
        elif abs(disc) > DISCREPANCY_TOLERANCE:
            billing = min(agency, tp)
        else:
            billing = agency
    rec["billing_impressions"] = billing
    rec["billable_cents"] = rhu_int(billing * li["cpm_rate_cents"], 1000)


# ---------------------------------------------------------------------------
# Attribution (largest-remainder)
# ---------------------------------------------------------------------------
def compute_attribution(lis, model, total_conversions):
    """lis: non-CANCELLED line items sorted by (created_at, seq)."""
    n = len(lis)
    if n == 0:
        return []
    if model == "LINEAR_CLICKS":
        nums = [delivered(li["id"])[1] for li in lis]
    else:  # VIEW_WEIGHTED
        nums = []
        for li in lis:
            nums.append(sum(v["viewable_impressions"] for v in reports_of_li(li["id"])))
    denom = sum(nums)
    if denom == 0:
        weights = [Fraction(1, n)] * n
    else:
        weights = [Fraction(x, denom) for x in nums]
    raws = [total_conversions * w for w in weights]
    floors = [r.numerator // r.denominator for r in raws]
    remainder_slots = total_conversions - sum(floors)
    order = sorted(
        range(n),
        key=lambda i: (-(raws[i] - floors[i]), lis[i]["_created_dt"], lis[i]["_seq"]),
    )
    conv = list(floors)
    for i in order[:remainder_slots]:
        conv[i] += 1
    out = []
    for li, w, c in zip(lis, weights, conv):
        out.append({
            "line_item_id": li["id"],
            "weight": float(w),
            "attributed_conversions": c,
        })
    return out
