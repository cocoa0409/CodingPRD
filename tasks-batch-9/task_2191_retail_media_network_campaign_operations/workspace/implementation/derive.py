"""Derived aggregates, the eighteen named calculations, and the resource
serialisers.  Every figure here is recomputed from its defining population,
never incremented ad hoc (PRD 2.10).
"""
import math
from decimal import Decimal

from core import (
    db, dec, ceil_int, floor_utc_day, fmt_dt, lookup, now, overlaps, rhu,
    rhu_dec, trunc_int, whole_days,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RESERVING_DELIVERY = ("SCHEDULED", "DELIVERING", "PAUSED")
OCCUPYING_STATUSES = ("ELIGIBLE", "SERVING", "OOS_PAUSED", "MANUAL_PAUSED")
SEGMENT_BONUS = {"NEW": "0.00", "RETURNING": "0.03", "LOYALTY": "0.06"}
TIER_MULTIPLIER = {"TIER_1": "1.10", "TIER_2": "1.00", "TIER_3": "0.90"}
TIER_ORDER = {"TIER_1": 0, "TIER_2": 1, "TIER_3": 2}
MATCH_WEIGHT = {"CLICK": "1.0", "OFFSITE_VIEW": "0.4", "IMPRESSION": "0.2"}
EVENT_PRECEDENCE = {"CLICK": 0, "OFFSITE_VIEW": 1, "IMPRESSION": 2}
SLA_BASE_HOURS = {
    "IMPRESSION_DISCREPANCY": 72,
    "ATTRIBUTION_WINDOW": 120,
    "OFFSITE_SPEND_VARIANCE": 96,
    "INCREMENTALITY_RESTATEMENT": 240,
}
SLA_FLOOR_HOURS = 24
INFO_REQUEST_EXTENSION_HOURS = 48
MAX_INFO_REQUESTS = 2
MAX_ADJUSTMENT_ROUNDS = 2
MAX_REVISION_ROUNDS = 3
MIN_TOP_UP_CENTS = 50000
MIN_ACCRUAL_CENTS = 1000
MIN_APPROVAL_CREDIT_LIMIT_CENTS = 100000
NET_TERMS_DAYS = 30
DISPUTE_GRACE_DAYS = 15
WRITE_OFF_DAYS = 60
WASHOUT_HOURS = 168
SIGNIFICANCE_MIN = Decimal("1.96")
VARIANCE_TOLERANCE_PCT = Decimal("2.00")
IROAS_TARGET = Decimal("3.0")
SLA_BREACH_UPLIFT = Decimal("1.10")
IMPRESSION_EVIDENCE_PCT = Decimal("0.25")
PACING_CATCHUP_THRESHOLD = Decimal("0.80")
PACING_CATCHUP_FACTOR = Decimal("1.25")


# ---------------------------------------------------------------------------
# Population accessors
# ---------------------------------------------------------------------------
def campaigns_of_plan(plan_id):
    return [c for c in db.campaigns.values() if c["budget_plan_id"] == plan_id]


def campaigns_of_advertiser(adv_id):
    return [c for c in db.campaigns.values() if c["advertiser_id"] == adv_id]


def line_items_of_campaign(camp_id):
    return [l for l in db.line_items.values() if l["campaign_id"] == camp_id]


def line_items_of_slot(slot_id):
    return [l for l in db.line_items.values() if l["placement_slot_id"] == slot_id]


def assignments_of_line_item(li_id):
    return [a for a in db.product_assignments.values() if a["line_item_id"] == li_id]


def assignments_of_product(prod_id):
    return [a for a in db.product_assignments.values()
            if a["catalog_product_id"] == prod_id]


def plans_of_advertiser(adv_id):
    return [p for p in db.budget_plans.values() if p["advertiser_id"] == adv_id]


def invoices_of_advertiser(adv_id):
    return [i for i in db.invoices.values() if i["advertiser_id"] == adv_id]


def invoices_of_plan(plan_id):
    return [i for i in db.invoices.values() if i["budget_plan_id"] == plan_id]


def invoices_of_pool(pool_id):
    return [i for i in db.invoices.values() if i["trade_fund_account_id"] == pool_id]


def disputes_of_invoice(inv_id):
    return [d for d in db.measurement_disputes.values() if d["invoice_id"] == inv_id]


def studies_of_campaign(camp_id):
    return [s for s in db.incrementality_studies.values()
            if s["campaign_id"] == camp_id]


def events_of_auction(auc_id):
    return [e for e in db.engagement_events.values() if e["auction_event_id"] == auc_id]


def events_of_line_item(li_id):
    return [e for e in db.engagement_events.values() if e["line_item_id"] == li_id]


def bids_of_auction(auc_id):
    return [b for b in db.auction_bids.values() if b["auction_event_id"] == auc_id]


def sales_of_line_item(li_id):
    return [s for s in db.attributed_sales.values() if s["line_item_id"] == li_id]


def settled_auctions():
    return [a for a in db.auction_events.values() if a["status"] == "SETTLED"]


def campaign_of_line_item(li):
    return lookup("campaign", li["campaign_id"]) if li else None


def plan_of_campaign(camp):
    return lookup("budget_plan", camp["budget_plan_id"]) if camp else None


def advertiser_of_campaign(camp):
    return lookup("advertiser", camp["advertiser_id"]) if camp else None


def slot_of_line_item(li):
    return lookup("placement_slot", li["placement_slot_id"]) if li else None


# ---------------------------------------------------------------------------
# Calculation 15: budget_plan_available
# ---------------------------------------------------------------------------
def plan_cash_share(plan):
    return plan["committed_total_cents"] - plan["trade_fund_share_cents"]


def plan_reserved(plan):
    return sum(c["allocated_budget_cents"] for c in campaigns_of_plan(plan["id"])
               if c["delivery_status"] in RESERVING_DELIVERY)


def plan_consumed(plan):
    total = 0
    for auc in settled_auctions():
        li = lookup("line_item", auc.get("winning_line_item_id"))
        if li is None:
            continue
        camp = campaign_of_line_item(li)
        if camp is not None and camp["budget_plan_id"] == plan["id"]:
            total += auc["settled_spend_cents"]
    for camp in campaigns_of_plan(plan["id"]):
        if camp["delivery_status"] != "REJECTED":
            total += camp["offsite_reported_spend_cents"]
    return total


def plan_available(plan):
    return (plan["committed_total_cents"] + plan["top_up_total_cents"]
            - plan_reserved(plan) - plan_consumed(plan))


# ---------------------------------------------------------------------------
# Calculation 16: trade_fund_available
# ---------------------------------------------------------------------------
def pool_reserved(pool):
    return sum(p["trade_fund_share_cents"] for p in db.budget_plans.values()
               if p["advertiser_id"] == pool["advertiser_id"]
               and p["fiscal_period_code"] == pool["fiscal_period_code"]
               and p["plan_status"] in ("APPROVED", "ACTIVE"))


def pool_deducted(pool):
    total = pool["_manual_deducted_cents"]
    for inv in invoices_of_pool(pool["id"]):
        if inv["invoice_status"] in ("ISSUED", "DISPUTED", "ADJUSTED", "SETTLED"):
            total += inv["trade_fund_deduction_cents"]
    return total


def pool_available(pool):
    return pool["accrued_cents"] - pool_reserved(pool) - pool_deducted(pool)


def pool_for(adv_id, fiscal_period_code):
    """The fund pool of one advertiser and fiscal period (unique pairing)."""
    for pool in db.trade_fund_accounts.values():
        if (pool["advertiser_id"] == adv_id
                and pool["fiscal_period_code"] == fiscal_period_code):
            return pool
    return None


# ---------------------------------------------------------------------------
# Calculation 17: advertiser_credit_exposure
# ---------------------------------------------------------------------------
def advertiser_exposure(adv):
    total = sum(p["committed_total_cents"] for p in plans_of_advertiser(adv["id"])
                if p["plan_status"] in ("APPROVED", "ACTIVE", "EXHAUSTED"))
    for inv in invoices_of_advertiser(adv["id"]):
        if inv["invoice_status"] in ("ISSUED", "DISPUTED", "ADJUSTED"):
            total += inv["net_cash_due_cents"]
    return total


def effective_credit_limit(adv):
    parent = lookup("advertiser", adv.get("parent_advertiser_id"))
    if adv.get("parent_advertiser_id") and parent is not None:
        return parent["credit_limit_cents"]
    return adv["credit_limit_cents"]


def dispute_credit_balance(adv):
    total = 0
    for d in db.measurement_disputes.values():
        if d["dispute_status"] != "UPHELD":
            continue
        inv = lookup("invoice", d["invoice_id"])
        if inv is None or inv["advertiser_id"] != adv["id"]:
            continue
        if inv["invoice_status"] == "SETTLED":
            continue
        total += d["approved_credit_cents"]
    return total


# ---------------------------------------------------------------------------
# Calculation 11 / 18: slot occupancy and line item aggregates
# ---------------------------------------------------------------------------
def slot_occupancy(slot):
    return len([l for l in line_items_of_slot(slot["id"])
                if l["line_item_status"] in OCCUPYING_STATUSES])


def active_eligible_assignments(li_id):
    out = []
    for a in assignments_of_line_item(li_id):
        if a["assignment_status"] != "ACTIVE":
            continue
        prod = lookup("catalog_product", a["catalog_product_id"])
        if prod is not None and prod["eligibility_status"] == "ELIGIBLE":
            out.append(a)
    return out


def eligible_product_count(li):
    return len(active_eligible_assignments(li["id"]))


def line_item_spend(li):
    return sum(a["settled_spend_cents"] for a in settled_auctions()
               if a.get("winning_line_item_id") == li["id"])


def line_item_reservation(li):
    days = whole_days(li["flight_start_at"], li["flight_end_at"])
    return li["daily_budget_cents"] * max(1, days)


# ---------------------------------------------------------------------------
# Campaign aggregates
# ---------------------------------------------------------------------------
def campaign_delivered_spend(camp):
    ids = set(l["id"] for l in line_items_of_campaign(camp["id"]))
    return sum(a["settled_spend_cents"] for a in settled_auctions()
               if a.get("winning_line_item_id") in ids)


def campaign_attributed_revenue(camp):
    total = 0
    for li in line_items_of_campaign(camp["id"]):
        for sale in sales_of_line_item(li["id"]):
            if not sale["restated"]:
                total += sale["attributed_credit_cents"]
    return total


def latest_published_study(camp_id):
    pub = [s for s in studies_of_campaign(camp_id) if s["study_status"] == "PUBLISHED"]
    if not pub:
        return None
    pub.sort(key=lambda s: (s["window_end_at"], s["created_at"], s["_seq"]))
    best = pub[-1]
    # ties on window_end_at broken by ascending created_at
    tied = [s for s in pub if s["window_end_at"] == best["window_end_at"]]
    tied.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return tied[0]


def campaign_incremental_revenue(camp):
    study = latest_published_study(camp["id"])
    if study is None or study["incremental_sales_cents"] is None:
        return 0
    return study["incremental_sales_cents"]


def campaign_oos_count(camp):
    return len([l for l in line_items_of_campaign(camp["id"])
                if l["line_item_status"] == "OOS_PAUSED"])


def campaign_roas_denominator(camp):
    return campaign_delivered_spend(camp) + camp["offsite_reported_spend_cents"]


def campaign_roas(camp):
    denom = campaign_roas_denominator(camp)
    if denom == 0:
        return 0.0
    return rhu(dec(campaign_attributed_revenue(camp)) / dec(denom), 4)


def campaign_iroas(camp):
    denom = campaign_roas_denominator(camp)
    if denom == 0:
        return 0.0
    return rhu(dec(campaign_incremental_revenue(camp)) / dec(denom), 4)


def campaign_iroas_dec(camp):
    denom = campaign_roas_denominator(camp)
    if denom == 0:
        return Decimal("0.0")
    return rhu_dec(dec(campaign_incremental_revenue(camp)) / dec(denom), 4)


# ---------------------------------------------------------------------------
# Calculation 10: campaign_pacing_allowance
# ---------------------------------------------------------------------------
def pacing_figures(camp, at=None):
    at = at or now()
    total_days = whole_days(camp["flight_start_at"], camp["flight_end_at"])
    elapsed = whole_days(camp["flight_start_at"], at)
    if elapsed < 0:
        elapsed = 0
    if elapsed > total_days:
        elapsed = total_days
    delivered = campaign_delivered_spend(camp)
    if total_days == 0:
        ideal = 0
    else:
        ideal = rhu(dec(camp["allocated_budget_cents"]) * dec(elapsed) / dec(total_days))
    if ideal == 0:
        index = Decimal("0.0000")
    else:
        index = rhu_dec(dec(delivered) / dec(ideal), 4)
    remaining_days = max(1, total_days - elapsed)
    remaining_budget = max(0, camp["allocated_budget_cents"] - delivered)
    if camp["pacing_mode"] == "ACCELERATED":
        base = remaining_budget
    else:
        base = trunc_int(dec(remaining_budget) / dec(remaining_days))
    if camp["pacing_mode"] == "EVEN" and index < PACING_CATCHUP_THRESHOLD:
        base = trunc_int(dec(base) * PACING_CATCHUP_FACTOR)
    allowance = min(camp["daily_cap_cents"], base)
    return {
        "total_days": total_days,
        "elapsed_days": elapsed,
        "ideal_spend_cents": ideal,
        "pacing_index": float(index),
        "daily_allowance_cents": allowance,
    }


def recompute_pacing(camp, at=None):
    camp["pacing_index"] = pacing_figures(camp, at)["pacing_index"]
    return camp["pacing_index"]


# ---------------------------------------------------------------------------
# Calculation 3: line_item_priority_tier
# ---------------------------------------------------------------------------
def priority_tier(li):
    camp = campaign_of_line_item(li)
    plan = plan_of_campaign(camp)
    adv = advertiser_of_campaign(camp)
    if plan is None:
        denom = 0
        avail = 0
    else:
        denom = plan["committed_total_cents"] + plan["top_up_total_cents"]
        avail = plan_available(plan)
    ratio = Decimal("0.0") if denom == 0 else dec(avail) / dec(denom)
    managed = adv is not None and adv["service_model"] == "MANAGED"
    if managed and ratio >= Decimal("0.50"):
        return "TIER_1"
    if managed or ratio >= Decimal("0.20"):
        return "TIER_2"
    return "TIER_3"


# ---------------------------------------------------------------------------
# Calculation 1: relevance_score_composition
# ---------------------------------------------------------------------------
def relevance_for(li, auction):
    terms = li.get("keyword_match_terms") or []
    tokens = (auction["request_context_query"] or "").split(" ")
    token_set = set(tokens)
    if len(terms) == 0:
        overlap_ratio = Decimal("0.0")
    else:
        distinct_hits = set(t for t in terms if t in token_set)
        overlap_ratio = dec(len(distinct_hits)) / dec(len(terms))
    active = active_eligible_assignments(li["id"])
    if active:
        margins = []
        for a in active:
            prod = lookup("catalog_product", a["catalog_product_id"])
            margins.append(dec(prod["margin_pct"]))
        margin_avg = sum(margins) / dec(len(margins))
    else:
        margin_avg = Decimal("0.0")
    hero = Decimal("0.10") if any(a["is_hero"] for a in active) else Decimal("0.00")
    bonus = Decimal(SEGMENT_BONUS.get(auction["shopper_segment"], "0.00"))
    raw = (Decimal("0.60") * overlap_ratio + Decimal("0.25") * margin_avg
           + hero + bonus)
    if raw > Decimal("1.0"):
        raw = Decimal("1.0")
    return rhu_dec(raw, 4)


def recompute_relevance_contributions(li_id):
    active = active_eligible_assignments(li_id)
    active_ids = set(a["id"] for a in active)
    count = max(1, len(active))
    for a in assignments_of_line_item(li_id):
        if a["id"] in active_ids:
            prod = lookup("catalog_product", a["catalog_product_id"])
            value = rhu(Decimal("0.25") * dec(prod["margin_pct"]) / dec(count), 4)
        else:
            value = 0.0
        a["relevance_contribution"] = value


# ---------------------------------------------------------------------------
# Calculation 2: relevance_adjusted_bid_ranking -- daily headroom
# ---------------------------------------------------------------------------
def day_window(at=None):
    start = floor_utc_day(at or now())
    from datetime import timedelta
    return start, start + timedelta(hours=24)


def _in_window(ts, start, end):
    return ts is not None and start <= ts < end


def line_item_day_spend(li, start, end):
    return sum(e["billable_cents"] for e in events_of_line_item(li["id"])
               if _in_window(e["occurred_at"], start, end))


def campaign_day_spend(camp, start, end):
    ids = set(l["id"] for l in line_items_of_campaign(camp["id"]))
    return sum(a["settled_spend_cents"] for a in settled_auctions()
               if a.get("winning_line_item_id") in ids
               and _in_window(a["requested_at"], start, end))


def advertiser_day_spend(adv, start, end):
    total = 0
    for camp in campaigns_of_advertiser(adv["id"]):
        total += campaign_day_spend(camp, start, end)
    return total


def daily_headroom(li):
    start, end = day_window()
    camp = campaign_of_line_item(li)
    adv = advertiser_of_campaign(camp)
    caps = [li["daily_budget_cents"] - line_item_day_spend(li, start, end)]
    if camp is not None:
        allowance = pacing_figures(camp)["daily_allowance_cents"]
        caps.append(allowance - campaign_day_spend(camp, start, end))
    if adv is not None and adv["service_model"] == "SELF_SERVE":
        caps.append(adv["self_serve_daily_spend_cap_cents"]
                    - advertiser_day_spend(adv, start, end))
    return min(caps)


def quality_adjusted(effective_bid, relevance, weight, tier):
    base = dec(relevance) ** dec(weight) if relevance > 0 else Decimal("0")
    value = dec(effective_bid) * base * Decimal(TIER_MULTIPLIER[tier])
    return rhu_dec(value, 4)


# ---------------------------------------------------------------------------
# Calculation 8: offsite_spend_reconciliation
# ---------------------------------------------------------------------------
def logged_offsite(camp):
    ids = set(l["id"] for l in line_items_of_campaign(camp["id"]))
    total = 0
    for auc in settled_auctions():
        if auc.get("winning_line_item_id") not in ids:
            continue
        slot = lookup("placement_slot", auc["placement_slot_id"])
        if slot is not None and slot["channel"] == "OFFSITE":
            total += auc["settled_spend_cents"]
    return total


def offsite_variance_dec(camp):
    logged = logged_offsite(camp)
    reported = camp["offsite_reported_spend_cents"]
    if logged == 0 and reported == 0:
        return Decimal("0.00")
    if logged == 0 and reported > 0:
        return Decimal("100.00")
    return rhu_dec((dec(reported) - dec(logged)) / dec(logged) * dec(100), 2)


def offsite_variance_pct(camp):
    return float(offsite_variance_dec(camp))


def offsite_basis(camp):
    if abs(offsite_variance_dec(camp)) >= VARIANCE_TOLERANCE_PCT:
        return "LOGGED_BASIS"
    return "REPORTED_BASIS"


def offsite_billable(camp):
    if offsite_basis(camp) == "LOGGED_BASIS":
        return logged_offsite(camp)
    return camp["offsite_reported_spend_cents"]


# ---------------------------------------------------------------------------
# Calculation 12: study_window_washout
# ---------------------------------------------------------------------------
def washout_violation(campaign_id, candidate_id, win_start, win_end, supersedes_id):
    for other in studies_of_campaign(campaign_id):
        if other["id"] == candidate_id:
            continue
        if other["study_status"] not in ("RUNNING", "MEASURING", "PUBLISHED"):
            continue
        if supersedes_id is not None and other["id"] == supersedes_id:
            continue
        if win_start >= other["window_end_at"]:
            gap = (win_start - other["window_end_at"]).total_seconds() / 3600.0
        elif other["window_start_at"] >= win_end:
            gap = (other["window_start_at"] - win_end).total_seconds() / 3600.0
        else:
            gap = -1.0
        if gap < WASHOUT_HOURS:
            return other
    return None


# ---------------------------------------------------------------------------
# Calculation 7: incremental_sales_lift
# ---------------------------------------------------------------------------
def compute_study_results(study):
    eg = study["exposed_group_size"]
    cg = study["control_group_size"]
    exposed_rate = dec(study["exposed_conversions"]) / dec(eg) if eg else Decimal("0")
    control_rate = dec(study["control_conversions"]) / dec(cg) if cg else Decimal("0")
    if study["design_method"] == "GEO_HOLDOUT":
        if control_rate == 0:
            lift = Decimal("1.0000")
        else:
            lift = rhu_dec(exposed_rate / control_rate - Decimal("1.0"), 4)
        if lift > 0:
            incremental = rhu(dec(study["exposed_sales_cents"])
                              * (lift / (Decimal("1.0") + lift)))
        else:
            incremental = 0
    else:
        if cg:
            scaled = dec(study["control_sales_cents"]) * dec(eg) / dec(cg)
        else:
            scaled = Decimal("0")
        diff = dec(study["exposed_sales_cents"]) - scaled
        incremental = rhu(diff if diff > 0 else Decimal("0"))
        if scaled == 0:
            lift = Decimal("1.0000")
        else:
            lift = rhu_dec(diff / scaled, 4)
    smaller = min(eg, cg) if eg and cg else 0
    sig = rhu_dec(abs(exposed_rate - control_rate) * dec(math.sqrt(smaller)), 4)
    study["lift_pct"] = float(lift)
    study["incremental_sales_cents"] = incremental
    study["significance_score"] = float(sig)
    study["significance_flag"] = bool(sig >= SIGNIFICANCE_MIN)


# ---------------------------------------------------------------------------
# Calculation 6: attributed_sales_credit
# ---------------------------------------------------------------------------
def _sale_engagement(sale):
    return db.engagement_events.get(sale["engagement_event_id"])


def compute_attribution(sale):
    """Sets within_window, attribution_weight and attributed_credit_cents."""
    from datetime import timedelta
    engagement = _sale_engagement(sale)
    li = lookup("line_item", engagement["line_item_id"])
    camp = campaign_of_line_item(li)
    window = timedelta(hours=24 * camp["attribution_window_days"])
    delta = sale["occurred_at"] - engagement["occurred_at"]
    within = sale["occurred_at"] >= engagement["occurred_at"] and delta < window
    sale["within_window"] = bool(within)
    sale["attribution_model_applied"] = camp["attribution_model"]
    if not within:
        sale["attribution_weight"] = 0.0
        sale["attributed_credit_cents"] = 0
        return
    lower = sale["occurred_at"] - window
    candidates = []
    for e in db.engagement_events.values():
        if e["shopper_hash"] != engagement["shopper_hash"]:
            continue
        if e["catalog_product_id"] != sale["catalog_product_id"]:
            continue
        if not (lower <= e["occurred_at"] <= sale["occurred_at"]):
            continue
        cli = lookup("line_item", e["line_item_id"])
        ccamp = campaign_of_line_item(cli)
        if ccamp is None or ccamp["delivery_status"] == "REJECTED":
            continue
        candidates.append(e)
    if not candidates:
        candidates = [engagement]
    if camp["attribution_model"] == "LAST_TOUCH":
        ordered = sorted(
            candidates,
            key=lambda e: (e["occurred_at"],
                           -EVENT_PRECEDENCE[e["event_type"]],
                           -e["_seq"]),
        )
        credited = ordered[-1]
        weight = Decimal("1.0") if credited["id"] == engagement["id"] else Decimal("0.0")
        sale["attribution_weight"] = float(weight)
    else:
        total = sum(Decimal(MATCH_WEIGHT[e["event_type"]]) for e in candidates)
        if total == 0:
            weight = Decimal("0.0")
        else:
            weight = rhu_dec(Decimal(MATCH_WEIGHT[engagement["event_type"]]) / total, 4)
        sale["attribution_weight"] = float(weight)
    sale["attributed_credit_cents"] = rhu(dec(sale["sale_cents"]) * weight)


# ---------------------------------------------------------------------------
# Calculation 13: dispute_sla_clock
# ---------------------------------------------------------------------------
def dispute_advertiser(dispute):
    inv = lookup("invoice", dispute["invoice_id"])
    return lookup("advertiser", inv["advertiser_id"]) if inv else None


def recompute_sla(dispute, base_hours=None):
    from datetime import timedelta
    adv = dispute_advertiser(dispute)
    base = base_hours if base_hours is not None else SLA_BASE_HOURS[dispute["dispute_category"]]
    reduction = 24 if (adv is not None and adv["service_model"] == "MANAGED") else 0
    hours = max(SLA_FLOOR_HOURS,
                base - reduction
                + INFO_REQUEST_EXTENSION_HOURS * dispute["info_request_count"])
    dispute["sla_response_hours"] = hours
    dispute["sla_due_at"] = dispute["filed_at"] + timedelta(hours=hours)
    refresh_breach(dispute)


def refresh_breach(dispute):
    due = dispute["sla_due_at"]
    if due is None:
        dispute["sla_breached"] = False
    elif dispute["first_response_at"] is not None:
        dispute["sla_breached"] = bool(dispute["first_response_at"] > due)
    else:
        dispute["sla_breached"] = bool(now() >= due)
    return dispute["sla_breached"]


# ---------------------------------------------------------------------------
# Calculation 14: dispute_credit_award
# ---------------------------------------------------------------------------
def evidence_cap(dispute, invoice):
    li = lookup("line_item", dispute.get("line_item_id"))
    camp = campaign_of_line_item(li)
    category = dispute["dispute_category"]
    if category == "IMPRESSION_DISCREPANCY":
        return rhu(dec(invoice["onsite_spend_cents"]) * IMPRESSION_EVIDENCE_PCT)
    if category == "ATTRIBUTION_WINDOW":
        if li is None:
            return 0
        return sum(s["attributed_credit_cents"] for s in sales_of_line_item(li["id"])
                   if not s["within_window"])
    if category == "OFFSITE_SPEND_VARIANCE":
        if camp is None:
            return 0
        return max(0, camp["offsite_reported_spend_cents"] - logged_offsite(camp))
    # INCREMENTALITY_RESTATEMENT
    if camp is None:
        ratio = Decimal("0.0")
    else:
        ratio = campaign_iroas_dec(camp) / IROAS_TARGET
    if ratio > Decimal("1.0"):
        ratio = Decimal("1.0")
    return rhu(dec(invoice["gross_spend_cents"]) * (Decimal("1.0") - ratio))


def dispute_credit_award(dispute, invoice, requested):
    cap = evidence_cap(dispute, invoice)
    uplift = (SLA_BREACH_UPLIFT
              if (dispute["sla_breached"] and dispute["escalation_level"] == 1)
              else Decimal("1.00"))
    capped = rhu(dec(cap) * uplift)
    ceiling = invoice["net_cash_due_cents"] + invoice["trade_fund_deduction_cents"]
    return min(requested, dispute["claimed_amount_cents"], capped, ceiling)


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------
def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": fmt_dt(row["created_at"])}
    if versioned:
        out["updated_at"] = fmt_dt(row["updated_at"])
        out["version"] = row["version"]
    return out


def ser_advertiser(row):
    out = _common(row)
    out.update({
        "legal_name": row["legal_name"],
        "brand_code": row["brand_code"],
        "service_model": row["service_model"],
        "onboarding_status": row["onboarding_status"],
        "parent_advertiser_id": row["parent_advertiser_id"],
        "account_manager_user_id": row["account_manager_user_id"],
        "credit_limit_cents": row["credit_limit_cents"],
        "credit_exposure_cents": advertiser_exposure(row),
        "kyc_document_count": row["kyc_document_count"],
        "suspension_reason": row["suspension_reason"],
        "self_serve_daily_spend_cap_cents": row["self_serve_daily_spend_cap_cents"],
        "managed_service_fee_pct": row["managed_service_fee_pct"],
        "dispute_credit_balance_cents": dispute_credit_balance(row),
        "onboarding_submitted_by_user_id": row["onboarding_submitted_by_user_id"],
        "kyc_decided_by_user_id": row["kyc_decided_by_user_id"],
    })
    return out


def ser_budget_plan(row):
    out = _common(row)
    out.update({
        "advertiser_id": row["advertiser_id"],
        "fiscal_period_code": row["fiscal_period_code"],
        "plan_status": row["plan_status"],
        "committed_total_cents": row["committed_total_cents"],
        "trade_fund_share_cents": row["trade_fund_share_cents"],
        "cash_share_cents": plan_cash_share(row),
        "reserved_cents": plan_reserved(row),
        "consumed_cents": plan_consumed(row),
        "available_cents": plan_available(row),
        "top_up_total_cents": row["top_up_total_cents"],
        "window_start_at": fmt_dt(row["window_start_at"]),
        "window_end_at": fmt_dt(row["window_end_at"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "revision_round": row["revision_round"],
        "exhausted_at": fmt_dt(row["exhausted_at"]),
    })
    return out


def ser_trade_fund_account(row):
    out = _common(row)
    out.update({
        "advertiser_id": row["advertiser_id"],
        "fiscal_period_code": row["fiscal_period_code"],
        "account_status": row["account_status"],
        "accrual_basis": row["accrual_basis"],
        "deduction_cap_pct": row["deduction_cap_pct"],
        "accrued_cents": row["accrued_cents"],
        "reserved_cents": pool_reserved(row),
        "deducted_cents": pool_deducted(row),
        "available_cents": pool_available(row),
        "frozen_reason": row["frozen_reason"],
        "last_reconciled_at": fmt_dt(row["last_reconciled_at"]),
    })
    return out


def ser_campaign(row):
    out = _common(row)
    out.update({
        "advertiser_id": row["advertiser_id"],
        "budget_plan_id": row["budget_plan_id"],
        "name": row["name"],
        "channel_mix": row["channel_mix"],
        "delivery_status": row["delivery_status"],
        "billing_status": row["billing_status"],
        "flight_start_at": fmt_dt(row["flight_start_at"]),
        "flight_end_at": fmt_dt(row["flight_end_at"]),
        "pacing_mode": row["pacing_mode"],
        "daily_cap_cents": row["daily_cap_cents"],
        "allocated_budget_cents": row["allocated_budget_cents"],
        "attribution_model": row["attribution_model"],
        "attribution_window_days": row["attribution_window_days"],
        "delivered_spend_cents": campaign_delivered_spend(row),
        "offsite_reported_spend_cents": row["offsite_reported_spend_cents"],
        "offsite_variance_pct": offsite_variance_pct(row),
        "attributed_revenue_cents": campaign_attributed_revenue(row),
        "incremental_revenue_cents": campaign_incremental_revenue(row),
        "roas": campaign_roas(row),
        "iroas": campaign_iroas(row),
        "pacing_index": row["pacing_index"],
        "oos_paused_line_item_count": campaign_oos_count(row),
        "review_decided_by_user_id": row["review_decided_by_user_id"],
        "submitted_for_review_by_user_id": row["submitted_for_review_by_user_id"],
    })
    return out


def ser_placement_slot(row):
    out = _common(row)
    out.update({
        "slot_code": row["slot_code"],
        "channel": row["channel"],
        "page_type": row["page_type"],
        "position_index": row["position_index"],
        "max_concurrent_line_items": row["max_concurrent_line_items"],
        "floor_cpc_cents": row["floor_cpc_cents"],
        "exclusivity_category_code": row["exclusivity_category_code"],
        "buffer_minutes": row["buffer_minutes"],
        "slot_status": row["slot_status"],
        "relevance_weight": row["relevance_weight"],
        "occupancy_count": slot_occupancy(row),
    })
    return out


def ser_line_item(row):
    out = _common(row)
    out.update({
        "campaign_id": row["campaign_id"],
        "placement_slot_id": row["placement_slot_id"],
        "line_item_status": row["line_item_status"],
        "bid_cents": row["bid_cents"],
        "bid_type": row["bid_type"],
        "flight_start_at": fmt_dt(row["flight_start_at"]),
        "flight_end_at": fmt_dt(row["flight_end_at"]),
        "daily_budget_cents": row["daily_budget_cents"],
        "category_code": row["category_code"],
        "keyword_match_terms": list(row["keyword_match_terms"]),
        "reserved_cents": row["reserved_cents"],
        "spend_cents": line_item_spend(row),
        "eligible_product_count": eligible_product_count(row),
        "relevance_score": row["relevance_score"],
        "quality_adjusted_score": row["quality_adjusted_score"],
        "priority_tier": row["priority_tier"],
        "pause_reason": row["pause_reason"],
        "last_pause_at": fmt_dt(row["last_pause_at"]),
        "eligibility_decided_by_user_id": row["eligibility_decided_by_user_id"],
    })
    return out


def ser_catalog_product(row):
    out = _common(row)
    out.update({
        "sku": row["sku"],
        "category_code": row["category_code"],
        "title": row["title"],
        "price_cents": row["price_cents"],
        "in_stock_units": row["in_stock_units"],
        "min_stock_units_for_serving": row["min_stock_units_for_serving"],
        "eligibility_status": row["eligibility_status"],
        "restricted_reason": row["restricted_reason"],
        "margin_pct": row["margin_pct"],
        "last_stock_change_at": fmt_dt(row["last_stock_change_at"]),
    })
    return out


def ser_product_assignment(row):
    out = _common(row)
    out.update({
        "line_item_id": row["line_item_id"],
        "catalog_product_id": row["catalog_product_id"],
        "assignment_status": row["assignment_status"],
        "is_hero": row["is_hero"],
        "relevance_contribution": row["relevance_contribution"],
        "removed_at": fmt_dt(row["removed_at"]),
    })
    return out


def ser_auction_event(row):
    out = _common(row)
    out.update({
        "placement_slot_id": row["placement_slot_id"],
        "winning_line_item_id": row["winning_line_item_id"],
        "status": row["status"],
        "request_context_query": row["request_context_query"],
        "shopper_segment": row["shopper_segment"],
        "requested_at": fmt_dt(row["requested_at"]),
        "candidate_count": row["candidate_count"],
        "winner_score": row["winner_score"],
        "second_best_score": row["second_best_score"],
        "clearing_price_cents": row["clearing_price_cents"],
        "settled_spend_cents": row["settled_spend_cents"],
        "no_fill_reason": row["no_fill_reason"],
    })
    return out


def ser_auction_bid(row):
    out = _common(row, versioned=False)
    out.update({
        "auction_event_id": row["auction_event_id"],
        "line_item_id": row["line_item_id"],
        "raw_bid_cents": row["raw_bid_cents"],
        "relevance_score": row["relevance_score"],
        "quality_adjusted_score": row["quality_adjusted_score"],
        "rank": row["rank"],
        "outcome": row["outcome"],
        "filter_reason": row["filter_reason"],
    })
    return out


def ser_engagement_event(row):
    out = _common(row, versioned=False)
    out.update({
        "line_item_id": row["line_item_id"],
        "auction_event_id": row["auction_event_id"],
        "catalog_product_id": row["catalog_product_id"],
        "event_type": row["event_type"],
        "occurred_at": fmt_dt(row["occurred_at"]),
        "shopper_hash": row["shopper_hash"],
        "channel": row["channel"],
        "billable_cents": row["billable_cents"],
    })
    return out


def ser_attributed_sale(row):
    out = _common(row)
    out.update({
        "engagement_event_id": row["engagement_event_id"],
        "line_item_id": row["line_item_id"],
        "catalog_product_id": row["catalog_product_id"],
        "retail_order_ref": row["retail_order_ref"],
        "sale_cents": row["sale_cents"],
        "units": row["units"],
        "occurred_at": fmt_dt(row["occurred_at"]),
        "match_type": row["match_type"],
        "attribution_model_applied": row["attribution_model_applied"],
        "attribution_weight": row["attribution_weight"],
        "attributed_credit_cents": row["attributed_credit_cents"],
        "within_window": row["within_window"],
        "restated": row["restated"],
    })
    return out


def ser_study(row):
    out = _common(row)
    out.update({
        "campaign_id": row["campaign_id"],
        "supersedes_study_id": row["supersedes_study_id"],
        "study_status": row["study_status"],
        "design_method": row["design_method"],
        "holdout_pct": row["holdout_pct"],
        "exposed_group_size": row["exposed_group_size"],
        "control_group_size": row["control_group_size"],
        "exposed_conversions": row["exposed_conversions"],
        "control_conversions": row["control_conversions"],
        "exposed_sales_cents": row["exposed_sales_cents"],
        "control_sales_cents": row["control_sales_cents"],
        "lift_pct": row["lift_pct"],
        "incremental_sales_cents": row["incremental_sales_cents"],
        "significance_score": row["significance_score"],
        "significance_flag": row["significance_flag"],
        "window_start_at": fmt_dt(row["window_start_at"]),
        "window_end_at": fmt_dt(row["window_end_at"]),
        "published_by_user_id": row["published_by_user_id"],
        "invalidated_reason": row["invalidated_reason"],
    })
    return out


def ser_invoice(row):
    out = _common(row)
    out.update({
        "advertiser_id": row["advertiser_id"],
        "budget_plan_id": row["budget_plan_id"],
        "trade_fund_account_id": row["trade_fund_account_id"],
        "invoice_status": row["invoice_status"],
        "billing_period_code": row["billing_period_code"],
        "onsite_spend_cents": row["onsite_spend_cents"],
        "offsite_spend_cents": row["offsite_spend_cents"],
        "gross_spend_cents": row["gross_spend_cents"],
        "managed_service_fee_cents": row["managed_service_fee_cents"],
        "trade_fund_deduction_cents": row["trade_fund_deduction_cents"],
        "dispute_credit_cents": row["dispute_credit_cents"],
        "net_cash_due_cents": row["net_cash_due_cents"],
        "variance_pct": row["variance_pct"],
        "adjustment_round": row["adjustment_round"],
        "issued_at": fmt_dt(row["issued_at"]),
        "due_at": fmt_dt(row["due_at"]),
        "settled_at": fmt_dt(row["settled_at"]),
        "issued_by_user_id": row["issued_by_user_id"],
    })
    return out


def ser_dispute(row):
    out = _common(row)
    out.update({
        "invoice_id": row["invoice_id"],
        "line_item_id": row["line_item_id"],
        "dispute_status": row["dispute_status"],
        "dispute_category": row["dispute_category"],
        "claimed_amount_cents": row["claimed_amount_cents"],
        "approved_credit_cents": row["approved_credit_cents"],
        "filed_at": fmt_dt(row["filed_at"]),
        "sla_response_hours": row["sla_response_hours"],
        "sla_due_at": fmt_dt(row["sla_due_at"]),
        "first_response_at": fmt_dt(row["first_response_at"]),
        "info_request_count": row["info_request_count"],
        "review_rounds": row["review_rounds"],
        "sla_breached": row["sla_breached"],
        "escalation_level": row["escalation_level"],
        "assigned_analyst_user_id": row["assigned_analyst_user_id"],
        "resolved_by_user_id": row["resolved_by_user_id"],
    })
    return out


SERIALISERS = {
    "advertiser": ser_advertiser,
    "budget_plan": ser_budget_plan,
    "trade_fund_account": ser_trade_fund_account,
    "campaign": ser_campaign,
    "placement_slot": ser_placement_slot,
    "line_item": ser_line_item,
    "catalog_product": ser_catalog_product,
    "product_assignment": ser_product_assignment,
    "auction_event": ser_auction_event,
    "auction_bid": ser_auction_bid,
    "engagement_event": ser_engagement_event,
    "attributed_sale": ser_attributed_sale,
    "study": ser_study,
    "invoice": ser_invoice,
    "dispute": ser_dispute,
}


def ser(kind, row):
    return SERIALISERS[kind](row)


def ser_many(kind, rows_):
    fn = SERIALISERS[kind]
    return [fn(r) for r in rows_]
