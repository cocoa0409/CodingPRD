"""Arithmetic: money rounding, tenure, lifetime value, margins, scores.

All rounding is ROUND_HALF_UP (PRD §2.8).  Money is whole cents; fractions are
carried to four decimal places.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import constants as K
from db import store, ordered

ONE = Decimal("1")
FOUR = Decimal("0.0001")


def cents(value):
    """Round a Decimal/int product half up to whole cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def frac4(value):
    return Decimal(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def ratio4(numerator, denominator):
    if denominator == 0:
        return Decimal("0.0000")
    return frac4(Decimal(numerator) / Decimal(denominator))


def half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_days(delta):
    return int(math.floor(delta.total_seconds() / 86400.0))


def ceil_days_ratio(delta, cycle_days):
    total = Decimal(delta.total_seconds()) / Decimal(86400)
    return int(math.ceil(total / Decimal(cycle_days)))


# --------------------------------------------------------------------------
# Tenure (PRD §3.9)
# --------------------------------------------------------------------------
def tenure_days_at(subscriber, instant):
    first = subscriber.get("first_subscribed_at")
    if first is None or instant is None:
        return 0
    return max(0, floor_days(instant - first))


def bucket_for_days(tenure_days):
    months = tenure_days // 30
    if months <= 1:
        return "M0_1"
    if months <= 3:
        return "M2_3"
    if months <= 6:
        return "M4_6"
    if months <= 12:
        return "M7_12"
    return "M13_PLUS"


def tenure_days_now(subscriber):
    return tenure_days_at(subscriber, store.now())


def tenure_bucket_now(subscriber):
    return bucket_for_days(tenure_days_now(subscriber))


def tenure_bucket_at(subscriber, instant):
    return bucket_for_days(tenure_days_at(subscriber, instant))


# --------------------------------------------------------------------------
# Relations
# --------------------------------------------------------------------------
def subscriptions_of(subscriber_id):
    return ordered([s for s in store.subscriptions.values()
                    if s["subscriber_id"] == subscriber_id])


def invoices_of_subscriber(subscriber_id):
    sub_ids = {s["id"] for s in store.subscriptions.values()
               if s["subscriber_id"] == subscriber_id}
    return ordered([i for i in store.invoices.values() if i["subscription_id"] in sub_ids])


def invoices_of_subscription(subscription_id):
    return ordered([i for i in store.invoices.values()
                    if i["subscription_id"] == subscription_id])


def attempts_of_invoice(invoice_id):
    return ordered([a for a in store.dunning_attempts.values()
                    if a["invoice_id"] == invoice_id])


def sessions_of_subscription(subscription_id):
    return ordered([s for s in store.cancellation_sessions.values()
                    if s["subscription_id"] == subscription_id])


def grants_of_session(session_id):
    return ordered([g for g in store.save_offer_grants.values()
                    if g["cancellation_session_id"] == session_id])


def grants_of_subscriber(subscriber_id):
    sub_ids = {s["id"] for s in store.subscriptions.values()
               if s["subscriber_id"] == subscriber_id}
    return ordered([g for g in store.save_offer_grants.values()
                    if g["subscription_id"] in sub_ids])


def mods_of_subscription(subscription_id):
    return ordered([m for m in store.subscription_modifications.values()
                    if m["subscription_id"] == subscription_id])


def notices_of_subscription(subscription_id):
    return ordered([n for n in store.compliance_notices.values()
                    if n["subscription_id"] == subscription_id])


def targets_of_subscriber(subscriber_id):
    return ordered([t for t in store.winback_targets.values()
                    if t["subscriber_id"] == subscriber_id])


def targets_of_campaign(campaign_id):
    return ordered([t for t in store.winback_targets.values()
                    if t["winback_campaign_id"] == campaign_id])


# --------------------------------------------------------------------------
# Lifetime value (PRD §3.9)
# --------------------------------------------------------------------------
def realized_ltv(subscriber):
    total = 0
    for inv in invoices_of_subscriber(subscriber["id"]):
        if inv["status"] == "PAID":
            total += inv["amount_cents"] - inv["cogs_cents"]
        elif inv["status"] == "WRITTEN_OFF":
            total -= inv["cogs_cents"]
    return total


def current_cycle_margin(subscriber):
    candidates = [i for i in invoices_of_subscriber(subscriber["id"])
                  if i["status"] in ("OPEN", "PAID")]
    if not candidates:
        return 0
    candidates.sort(key=lambda i: (i["due_at"], i["created_at"], i["_seq"]), reverse=True)
    top = candidates[0]
    return top["amount_cents"] - top["cogs_cents"]


def expected_remaining_cycles(subscriber):
    if subscriber.get("churn_type", "NONE") != "NONE":
        return 0
    base = K.CHANNEL_BASE_CHURN[subscriber["acquisition_channel"]]
    mult = K.TENURE_MULTIPLIER[tenure_bucket_now(subscriber)]
    rate = base * mult
    if rate <= 0:
        return K.HORIZON_CYCLES_CAP
    return min(K.HORIZON_CYCLES_CAP, half_up_int(ONE / rate))


def projected_ltv(subscriber):
    realized = realized_ltv(subscriber)
    margin = current_cycle_margin(subscriber)
    cyc = expected_remaining_cycles(subscriber)
    return realized + half_up_int(Decimal(margin) * Decimal(cyc))


def save_offer_grants_365d_count(subscriber):
    cutoff = store.now() - K.GRANT_WINDOW_DAYS * _one_day()
    count = 0
    for grant in grants_of_subscriber(subscriber["id"]):
        if grant["state"] in ("PRESENTED", "ACCEPTED") and grant["created_at"] >= cutoff:
            count += 1
    return count


def last_contacted_at(subscriber):
    rows = [t for t in targets_of_subscriber(subscriber["id"])
            if t["state"] in ("SENT", "EXPIRED", "CONVERTED") and t.get("sent_at")]
    if not rows:
        return None
    rows.sort(key=lambda t: (t["sent_at"], t["created_at"], t["_seq"]), reverse=True)
    return rows[0]["sent_at"]


def _one_day():
    from datetime import timedelta
    return timedelta(days=1)


# --------------------------------------------------------------------------
# Save-offer margins (PRD §3.6)
# --------------------------------------------------------------------------
def offer_margins(plan, template, target_plan=None):
    """Returns dict with per_cycle_margin_pct, blended_term_margin_pct,
    retention_value_cents, total_term_revenue_cents, total_term_cogs_cents."""
    price = Decimal(plan["monthly_price_cents"])
    cogs = Decimal(plan["unit_cogs_cents"])
    shipments = Decimal(plan["shipments_per_cycle"])
    horizon = K.POST_OFFER_HORIZON_CYCLES

    offer_type = template["offer_type"]
    rev_post = cents(price * shipments)
    cogs_post = int(cogs * shipments)

    if offer_type == "DISCOUNT":
        n = int(template["discount_cycles"])
        rev_offer = cents(price * shipments * (ONE - Decimal(template["discount_pct"])))
        cogs_offer = int(cogs * shipments)
    elif offer_type == "PAUSE":
        n = int(template["pause_cycles"])
        rev_offer = 0
        cogs_offer = 0
    elif offer_type == "SKIP":
        n = int(template["skip_count"])
        rev_offer = 0
        cogs_offer = 0
    else:  # PLAN_DOWNGRADE
        n = 0
        tgt = target_plan or plan
        rev_post = cents(Decimal(tgt["monthly_price_cents"]) * shipments)
        cogs_post = int(Decimal(tgt["unit_cogs_cents"]) * shipments)
        rev_offer = rev_post
        cogs_offer = cogs_post

    total_rev = n * rev_offer + horizon * rev_post
    total_cogs = n * cogs_offer + horizon * cogs_post

    per_cycle = ratio4(rev_offer - cogs_offer, rev_offer) if rev_offer else Decimal("0.0000")
    blended = ratio4(total_rev - total_cogs, total_rev) if total_rev else Decimal("0.0000")
    return {
        "per_cycle_margin_pct": per_cycle,
        "blended_term_margin_pct": blended,
        "retention_value_cents": total_rev - total_cogs,
        "total_term_revenue_cents": total_rev,
        "total_term_cogs_cents": total_cogs,
    }


# --------------------------------------------------------------------------
# Win-back priority score (PRD §3.8)
# --------------------------------------------------------------------------
def latest_reason_code(subscriber_id):
    sub_ids = {s["id"] for s in store.subscriptions.values()
               if s["subscriber_id"] == subscriber_id}
    rows = [s for s in store.cancellation_sessions.values() if s["subscription_id"] in sub_ids]
    if not rows:
        return None
    rows.sort(key=lambda s: (s["started_at"], s["created_at"], s["_seq"]), reverse=True)
    return rows[0].get("reason_code")


def winback_priority_score(subscriber, campaign, days_since_lapse):
    realized = Decimal(realized_ltv(subscriber))
    term1 = Decimal("0.45") * min(ONE, realized / K.LTV_NORMALIZER_CENTS)
    normalizer = Decimal(max(1, int(campaign["max_days_since_lapse"])))
    term2 = Decimal("0.30") * (ONE - min(ONE, Decimal(days_since_lapse) / normalizer))
    reason = latest_reason_code(subscriber["id"])
    weight = K.REASON_WEIGHT.get(reason, Decimal("0.0")) if reason else Decimal("0.0")
    term3 = Decimal("0.25") * weight
    score = frac4(term1 + term2 + term3)
    if subscriber.get("churn_type") == "INVOLUNTARY":
        score = min(score, K.INVOLUNTARY_SCORE_CEILING)
    return score
