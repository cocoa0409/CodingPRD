"""Engagement scoring, churn banding and the propensity refresh (PRD 3.4)."""
from decimal import Decimal

import config
from clock import clock, days_between, parse_date
from db import db
from services.money import rhu2

HALF = Decimal("0.5")


def reader_events(reader_id):
    return [e for e in db.reader_events.values() if e.get("reader_id") == reader_id]


def accumulated_total(reader):
    """Full-precision sum over the half-open 30-day window (never re-rounded)."""
    now = clock.now()
    total = Decimal("0")
    for event in reader_events(reader["id"]):
        age = days_between(now, event["_occurred_dt"])
        if age < 0 or age >= config.ENGAGEMENT_WINDOW_DAYS:
            continue
        weight = Decimal(str(event.get("weight") or 0))
        if weight == 0:
            continue
        decay = HALF ** (age // config.ENGAGEMENT_DECAY_STEP_DAYS)
        total += weight * decay
    return total


def rolling(reader):
    return rhu2(accumulated_total(reader))


def tenure_days(reader):
    return max(0, days_between(clock.now(), reader["_created_dt"]))


def cohort_normalized(reader):
    """Frozen onto a cancellation request as projected_engagement_score."""
    total = accumulated_total(reader)
    tenure = tenure_days(reader)
    if tenure < config.ENGAGEMENT_WINDOW_DAYS:
        return rhu2(total * Decimal(config.ENGAGEMENT_WINDOW_DAYS) / Decimal(max(1, tenure)))
    return rhu2(total)


def dunning_override(reader):
    considered = (
        "PENDING_ACTIVATION",
        "ACTIVE",
        "PAUSED",
        "CANCEL_SCHEDULED",
        "CANCELLED_NONPAY",
    )
    for sub in db.subscriptions.values():
        if sub.get("reader_id") != reader["id"]:
            continue
        if sub.get("lifecycle_status") not in considered:
            continue
        if sub.get("dunning_status") in ("RETRYING", "FAILED_FINAL"):
            return True
    return False


def churn_band(reader):
    if dunning_override(reader):
        return "SEVERE"
    score = Decimal(str(reader.get("engagement_score") or 0))
    if score < config.CHURN_SEVERE_BELOW:
        return "SEVERE"
    if score < config.CHURN_HIGH_BELOW:
        return "HIGH"
    if score < config.CHURN_MEDIUM_BELOW:
        return "MEDIUM"
    return "LOW"


def rescore(reader):
    """Write engagement_score then re-derive churn_risk_band. Returns True on change."""
    before = (reader.get("engagement_score"), reader.get("churn_risk_band"))
    reader["engagement_score"] = float(rolling(reader))
    reader["churn_risk_band"] = churn_band(reader)
    return before != (reader.get("engagement_score"), reader.get("churn_risk_band"))


def reband_churn(reader):
    before = reader.get("churn_risk_band")
    reader["churn_risk_band"] = churn_band(reader)
    return before != reader["churn_risk_band"]


def refresh_propensity(reader):
    score = Decimal(str(reader.get("engagement_score") or 0))
    if score >= config.PROPENSITY_HIGH_AT:
        band = "HIGH"
    elif score >= config.PROPENSITY_MEDIUM_AT:
        band = "MEDIUM"
    else:
        band = "LOW"
    changed = reader.get("propensity_band") != band
    reader["propensity_band"] = band
    return changed


def intervention_count_in_period(reader):
    started = reader.get("meter_period_started_on")
    if started is None:
        return 0
    floor_date = parse_date(started)
    count = 0
    for event in reader_events(reader["id"]):
        if event.get("event_type") not in config.INTERVENTION_EVENT_TYPES:
            continue
        if event["_occurred_dt"].date() >= floor_date:
            count += 1
    return count


def maybe_reset_meter_period(reader):
    """Lazy 30-day meter roll-over. Returns True when the period rolled."""
    started = reader.get("meter_period_started_on")
    today = clock.date()
    if started is None:
        reader["meter_period_started_on"] = today.isoformat()
        return True
    if (today - parse_date(started)).days >= config.METER_PERIOD_DAYS:
        reader["metered_article_ids"] = []
        reader["metered_distinct_article_count"] = 0
        reader["meter_period_started_on"] = today.isoformat()
        return True
    return False


def card_status(reader):
    if reader.get("card_last4") is None:
        return "MISSING"
    now = clock.now()
    stored = (reader.get("card_exp_year"), reader.get("card_exp_month"))
    if stored[0] is None or stored[1] is None:
        return "MISSING"
    if stored < (now.year, now.month):
        return "EXPIRED"
    return "CURRENT"
