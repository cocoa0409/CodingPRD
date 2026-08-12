"""Business logic: customer risk recompute, alert scoring, QA quota, backlog,
cascades (customer exit), continuing-review scheduling."""
from datetime import timedelta
from decimal import Decimal

import db
from util import (HIGH_RISK_COUNTRIES, base_entity, ceil_int, dec, round0_int,
                  round4, touch)

# ---------------------------------------------------------------------------
# customer_risk_rating_recompute (scaffold section 1.3)
# ---------------------------------------------------------------------------

RISK_BASE = 100
SAR_POINTS = 250
LE_INQUIRY_POINTS = 150
EXITED_ACCOUNT_POINTS = 400
ENHANCED_MULTIPLIER = Decimal("1.5")
LE_OPEN_STATUSES = {"RECEIVED", "UNDER_REVIEW", "RESPONDED"}


def _rating_for(score):
    if score >= 700:
        return "PROHIBITED"
    if score >= 400:
        return "HIGH"
    if score >= 200:
        return "MEDIUM"
    return "LOW"


def recompute_customer_risk(customer):
    """Recompute scores/rating; fires the account restriction cascade when the
    rating crosses INTO HIGH or PROHIBITED from a lower band."""
    now = db.now()
    old_rating = customer["risk_rating"]

    window_start = now - timedelta(days=365)
    sar_count = sum(
        1 for s in db.sars.values()
        if s["customer_id"] == customer["id"] and s["status"] == "FILED"
        and s["filed_at"] is not None and window_start < s["filed_at"] <= now)
    le_open = sum(
        1 for i in db.inquiries.values()
        if i["subject_customer_id"] == customer["id"] and i["status"] in LE_OPEN_STATUSES)
    any_exited = any(
        a["customer_id"] == customer["id"] and a["status"] == "EXITED"
        for a in db.accounts.values())

    score_std = (RISK_BASE + SAR_POINTS * sar_count
                 + LE_INQUIRY_POINTS * le_open
                 + (EXITED_ACCOUNT_POINTS if any_exited else 0))
    score_enh = round0_int(Decimal(score_std) * ENHANCED_MULTIPLIER)
    applicable = score_enh if customer["country_risk"] == "HIGH" else score_std
    new_rating = _rating_for(applicable)

    changed = (
        customer["sar_filings_365d"] != sar_count
        or customer["open_le_inquiry_count"] != le_open
        or customer["any_account_exited"] != any_exited
        or customer["risk_score_standard"] != score_std
        or customer["risk_score_enhanced"] != score_enh
        or customer["risk_rating"] != new_rating)
    customer["sar_filings_365d"] = sar_count
    customer["open_le_inquiry_count"] = le_open
    customer["any_account_exited"] = any_exited
    customer["risk_score_standard"] = score_std
    customer["risk_score_enhanced"] = score_enh
    customer["risk_rating"] = new_rating
    if changed:
        touch(customer)

    # Risk cascade: crossing INTO HIGH|PROHIBITED from a lower band restricts
    # every OPEN account. HIGH -> PROHIBITED does NOT re-trigger.
    if new_rating in {"HIGH", "PROHIBITED"} and old_rating not in {"HIGH", "PROHIBITED"}:
        for account in db.accounts.values():
            if account["customer_id"] == customer["id"] and account["status"] == "OPEN":
                account["status"] = "RESTRICTED"
                account["restriction_reason"] = "RISK_CASCADE"
                touch(account)


# ---------------------------------------------------------------------------
# alert_risk_score (scaffold section 1.3) — pinned evaluation order:
# round each component half-up to 4dp FIRST, then sum, scale by 100,
# round half-up to integer.
# ---------------------------------------------------------------------------

def alert_score(w_amount, w_velocity, w_geo, aggregate_amount_cents, txn_count,
                high_risk_count, threshold_amount_cents, min_transaction_count):
    amount_ratio = min(Decimal(1),
                       Decimal(aggregate_amount_cents) / (2 * Decimal(threshold_amount_cents)))
    velocity_ratio = min(Decimal(1),
                         Decimal(txn_count) / (2 * Decimal(min_transaction_count)))
    geo_fraction = Decimal(high_risk_count) / Decimal(txn_count)
    contrib_amount = round4(dec(w_amount) * amount_ratio)
    contrib_velocity = round4(dec(w_velocity) * velocity_ratio)
    contrib_geo = round4(dec(w_geo) * geo_fraction)
    return round0_int(100 * (contrib_amount + contrib_velocity + contrib_geo))


def high_risk_count(matching_txns):
    return sum(1 for t in matching_txns if t["counterparty_country"] in HIGH_RISK_COUNTRIES)


# ---------------------------------------------------------------------------
# qa_sample_quota (scaffold section 1.3) — pinned order:
# (1) count completions in the current UTC calendar month (independent of
#     sampling state), (2) quota = clamp(ceil(completed * 0.34), 1, 25),
# (3) count samples with period_month == current month.
# ---------------------------------------------------------------------------

SAMPLE_RATE = Decimal("0.34")
MIN_SAMPLE = 1
MAX_SAMPLE = 25


def qa_quota():
    now = db.now()
    year, month = now.year, now.month
    period = now.strftime("%Y-%m")

    def in_month(dt):
        return dt is not None and dt.year == year and dt.month == month

    completed = (
        sum(1 for c in db.cases.values() if in_month(c["closed_at"]))
        + sum(1 for s in db.sars.values() if in_month(s["filed_at"]))
        + sum(1 for a in db.alerts.values() if in_month(a["dismissed_at"])))
    quota = ceil_int(Decimal(completed) * SAMPLE_RATE)
    quota = max(MIN_SAMPLE, min(MAX_SAMPLE, quota))
    sampled = sum(1 for q in db.qa_reviews.values() if q["period_month"] == period)
    return quota, sampled


# ---------------------------------------------------------------------------
# backlog_aging_buckets (scaffold section 1.3)
# ---------------------------------------------------------------------------

OPEN_CASE_STATUSES = {"OPEN", "ASSIGNED", "INVESTIGATING", "ON_HOLD",
                      "SAR_IN_PROGRESS", "PENDING_QA"}


def backlog_summary():
    now = db.now()
    open_cases = [c for c in db.cases.values() if c["status"] in OPEN_CASE_STATUSES]
    b0_15 = b16_30 = b31_60 = b61 = 0
    for case in open_cases:
        age = int((now - case["created_at"]).total_seconds() // 86400)
        if age < 16:
            b0_15 += 1
        elif age < 31:
            b16_30 += 1
        elif age < 61:
            b31_60 += 1
        else:
            b61 += 1
    overdue_sar = sum(
        1 for s in db.sars.values()
        if s["status"] != "FILED" and s["deadline_at"] < now)
    stale_alerts = 0
    for alert in db.alerts.values():
        if alert["status"] not in {"NEW", "UNDER_TRIAGE"}:
            continue
        scenario = db.scenarios.get(alert["scenario_id"])
        stale_days = scenario["stale_alert_days"] if scenario else 30
        if now - alert["created_at"] > timedelta(days=stale_days):
            stale_alerts += 1
    overdue_reviews = sum(
        1 for r in db.reviews.values()
        if r["status"] in {"SCHEDULED", "OVERDUE"} and r["due_at"] < now)
    quota, sampled = qa_quota()
    return {
        "cases_open": len(open_cases),
        "cases_age_0_15": b0_15,
        "cases_age_16_30": b16_30,
        "cases_age_31_60": b31_60,
        "cases_age_61_plus": b61,
        "overdue_sar_count": overdue_sar,
        "stale_alert_count": stale_alerts,
        "overdue_review_count": overdue_reviews,
        "qa_samples_this_month": sampled,
        "qa_quota_this_month": quota,
    }


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def customer_exit_cascade(customer):
    """Customer -> EXITED side effects: auto-close open alerts, cancel DRAFT
    314(b) shares."""
    for alert in db.alerts.values():
        if alert["customer_id"] == customer["id"] and alert["status"] in {"NEW", "UNDER_TRIAGE"}:
            alert["status"] = "AUTO_CLOSED"
            alert["closure_reason"] = "CUSTOMER_EXITED"
            touch(alert)
    for share in db.shares.values():
        if share["subject_customer_id"] == customer["id"] and share["status"] == "DRAFT":
            share["status"] = "CANCELLED"
            touch(share)


def maybe_exit_customer(customer):
    """After an account exits: if no account remains OPEN|RESTRICTED, the
    customer transitions ACTIVE -> EXITED and the exit cascade fires."""
    has_open = any(
        a["customer_id"] == customer["id"] and a["status"] in {"OPEN", "RESTRICTED"}
        for a in db.accounts.values())
    if not has_open and customer["status"] == "ACTIVE":
        customer["status"] = "EXITED"
        touch(customer)
        customer_exit_cascade(customer)


def create_continuing_review(sar):
    """On SAR filing: schedule the continuing review. cycle_number is 1 for the
    first review of a SAR chain root and increments along prior_sar_id."""
    depth = 1
    cursor = sar
    while cursor.get("prior_sar_id"):
        parent = db.sars.get(cursor["prior_sar_id"])
        if parent is None:
            break
        depth += 1
        cursor = parent
    review = base_entity()
    review.update({
        "sar_report_id": sar["id"],
        "cycle_number": depth,
        "due_at": sar["filed_at"] + timedelta(days=90),
        "filing_deadline_at": sar["filed_at"] + timedelta(days=120),
        "status": "SCHEDULED",
        "outcome": "NONE",
        "completed_at": None,
        "created_continuing_sar_id": None,
    })
    db.reviews[review["id"]] = review
    return review
