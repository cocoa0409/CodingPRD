"""Derived values and calculations (PRD §2.8, §2.9, §3.3, §3.5, §3.6, §3.7).

Every derived field is recomputed from scratch from the rows it summarises;
none of them is incrementally patched and none accepts client input.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, now, touch

# --- constants -------------------------------------------------------------

TIER_RANK = {"TIER1": 1, "TIER2": 2, "TIER3": 3}
RANK_TIER = {1: "TIER1", 2: "TIER2", 3: "TIER3"}

BUREAU_WEIGHT = {
    "EQUIFAX": Decimal("0.35"),
    "EXPERIAN": Decimal("0.35"),
    "TRANSUNION": Decimal("0.30"),
}

BASE = Decimal(10)
TYPE_WEIGHT = {
    "SSN_TRACE": Decimal(25),
    "ACCOUNT_TAKEOVER": Decimal(20),
    "DARK_WEB": Decimal(15),
    "CREDIT_INQUIRY": Decimal(8),
}
ESCALATION_WEIGHT = Decimal(10)
SCORE_DROP_WEIGHT = Decimal(12)
SCORE_DROP_THRESHOLD = 40
FAMILY_CHILD_MULTIPLIER = Decimal("1.20")
SCORE_CEILING = 100
SCORE_FLOOR = 0

CONFIRMED = ("CONFIRMED_FRAUD", "ESCALATED")
COUNTED_STATUSES = {
    "LIVE": {
        "SSN_TRACE": ("CONFIRMED_FRAUD", "ESCALATED"),
        "ACCOUNT_TAKEOVER": ("CONFIRMED_FRAUD", "ESCALATED"),
        "DARK_WEB": ("ACKNOWLEDGED", "CONFIRMED_FRAUD", "ESCALATED"),
        "CREDIT_INQUIRY": ("NEW", "ACKNOWLEDGED", "CONFIRMED_FRAUD", "ESCALATED"),
    },
    "UNDERWRITING": {
        "SSN_TRACE": CONFIRMED,
        "ACCOUNT_TAKEOVER": CONFIRMED,
        "DARK_WEB": CONFIRMED,
        "CREDIT_INQUIRY": CONFIRMED,
    },
}

TIER2_RISK_THRESHOLD = 40
TIER3_RISK_THRESHOLD = 70
SLA_HOURS = {"TIER1": 72, "TIER2": 24, "TIER3": 4}

COVERAGE_PCT = {
    "LEGAL_FEES": Decimal("1.00"),
    "LOST_WAGES": Decimal("0.80"),
    "TRAVEL": Decimal("0.50"),
    "CHILDCARE": Decimal("0.50"),
    "NOTARY": Decimal("1.00"),
    "POSTAGE": Decimal("1.00"),
}
CATEGORY_SUBLIMIT_CENTS = {"LOST_WAGES": 250000, "TRAVEL": 100000, "CHILDCARE": 100000}
UNDOCUMENTED_FACTOR_PROVISIONAL = Decimal("0.50")
UNDOCUMENTED_FACTOR_FINAL = Decimal("0.00")
DEDUCTIBLE_CENTS = 2500

ACTIVE_CASE_STATUSES = ("ASSIGNED", "IN_PROGRESS", "PENDING_SUBSCRIBER")

ENGAGEMENT_BUFFER = timedelta(minutes=60)


def round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def max_tier(a, b):
    return RANK_TIER[max(TIER_RANK[a], TIER_RANK[b])]


# --- row selectors ---------------------------------------------------------

def profiles_of(subscriber_id):
    return [p for p in db.bureau_profiles.values() if p["subscriber_id"] == subscriber_id]


def alerts_of(subscriber_id):
    return [a for a in db.alerts.values() if a["subscriber_id"] == subscriber_id]


def family_of(subscriber_id):
    return [f for f in db.family_members.values() if f["subscriber_id"] == subscriber_id]


def cases_of_specialist(specialist_id):
    return [c for c in db.cases.values() if c["specialist_id"] == specialist_id]


def claims_of(subscriber_id):
    return [c for c in db.claims.values() if c["subscriber_id"] == subscriber_id]


# --- composite_credit_score ------------------------------------------------

def composite_credit_score(subscriber_id):
    """Weighted average over the bureau profiles that have reported a score.
    Profiles with a null credit_score are EXCLUDED and their weight is excluded
    from the renormalisation base — they are not treated as zero. Empty set -> None.
    """
    scored = [p for p in profiles_of(subscriber_id) if p["credit_score"] is not None]
    if not scored:
        return None
    w_sum = sum((BUREAU_WEIGHT[p["bureau"]] for p in scored), Decimal(0))
    weighted = sum(
        (BUREAU_WEIGHT[p["bureau"]] * Decimal(p["credit_score"]) for p in scored),
        Decimal(0),
    )
    return round_half_up(weighted / w_sum)


# --- identity_risk_score ---------------------------------------------------

def identity_risk_score(subscriber, variant):
    counted = COUNTED_STATUSES[variant]
    alerts = alerts_of(subscriber["id"])

    raw = BASE
    for alert_type, weight in TYPE_WEIGHT.items():
        n = sum(
            1
            for a in alerts
            if a["alert_type"] == alert_type and a["status"] in counted[alert_type]
        )
        raw += weight * n

    raw += ESCALATION_WEIGHT * sum(1 for a in alerts if a["status"] == "ESCALATED")

    baseline = subscriber.get("baseline_composite_credit_score")
    composite = subscriber.get("composite_credit_score")
    if (
        baseline is not None
        and composite is not None
        and (baseline - composite) >= SCORE_DROP_THRESHOLD
    ):
        raw += SCORE_DROP_WEIGHT

    if variant == "LIVE":
        monitored_children = {
            f["id"]
            for f in family_of(subscriber["id"])
            if f["relationship"] == "CHILD" and f["monitoring_status"] == "MONITORED"
        }
        if monitored_children and any(
            a["family_member_id"] in monitored_children and a["status"] in CONFIRMED
            for a in alerts
        ):
            raw = raw * FAMILY_CHILD_MULTIPLIER

    score = round_half_up(raw)
    return min(SCORE_CEILING, max(SCORE_FLOOR, score))


def recompute_risk(subscriber):
    subscriber["risk_score"] = identity_risk_score(subscriber, "LIVE")
    subscriber["underwriting_risk_score"] = identity_risk_score(subscriber, "UNDERWRITING")


# --- specialist_active_case_count -----------------------------------------

def recompute_specialist(specialist):
    count = sum(
        1
        for c in cases_of_specialist(specialist["id"])
        if c["status"] in ACTIVE_CASE_STATUSES
    )
    specialist["active_case_count"] = count
    specialist["status"] = (
        "AT_CAPACITY" if count >= specialist["max_caseload"] else "AVAILABLE"
    )


# --- insurance_remaining ---------------------------------------------------

def recompute_insurance(subscriber):
    plan = db.plans.get(subscriber["plan_id"])
    limit = plan["insurance_limit_cents"] if plan else 0
    paid_sum = sum(
        (c["approved_cents"] or 0)
        for c in claims_of(subscriber["id"])
        if c["status"] == "PAID"
    )
    remaining = limit - paid_sum
    subscriber["insurance_remaining_cents"] = remaining
    subscriber["insurance_status"] = "EXHAUSTED" if remaining <= 0 else "AVAILABLE"


# --- required_specialist_tier ---------------------------------------------

def tier_from_severity(severity):
    if severity == "CRITICAL":
        return "TIER3"
    if severity == "HIGH":
        return "TIER2"
    return "TIER1"


def required_specialist_tier(severity, plan_min_tier):
    return max_tier(tier_from_severity(severity), plan_min_tier)


# --- alert_escalation_tier -------------------------------------------------

def alert_escalation_tier(risk_snapshot, severity):
    if risk_snapshot >= TIER3_RISK_THRESHOLD or severity == "CRITICAL":
        return "TIER3"
    if risk_snapshot >= TIER2_RISK_THRESHOLD or severity == "HIGH":
        return "TIER2"
    return "TIER1"


def escalation_deadline(tier):
    return now() + timedelta(hours=SLA_HOURS[tier])


# --- specialist_selection --------------------------------------------------

def select_specialist(case):
    required_rank = TIER_RANK[case["required_specialist_tier"]]
    candidates = [
        sp
        for sp in db.specialists.values()
        if sp["status"] == "AVAILABLE"
        and TIER_RANK[sp["tier"]] >= required_rank
        and sp["active_case_count"] < sp["max_caseload"]
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda sp: (
            sp["active_case_count"],
            TIER_RANK[sp["tier"]],
            sp["created_at"],
            sp["_seq"],
        )
    )
    return candidates[0]


# --- claim_reimbursement ---------------------------------------------------

def claim_reimbursement(claim, variant, subscriber):
    """Pinned order: round per line item, sum per category, sublimit, deductible,
    remaining-insurance cap."""
    per_category = {}
    for expense in claim["expenses"]:
        pct = COVERAGE_PCT[expense["category"]]
        if expense["documented"]:
            factor = Decimal("1.00")
        elif variant == "PROVISIONAL":
            factor = UNDOCUMENTED_FACTOR_PROVISIONAL
        else:
            factor = UNDOCUMENTED_FACTOR_FINAL
        eligible = round_half_up(Decimal(expense["amount_cents"]) * pct * factor)
        per_category[expense["category"]] = per_category.get(expense["category"], 0) + eligible

    gross = 0
    for category, total in per_category.items():
        if category in CATEGORY_SUBLIMIT_CENTS:
            total = min(total, CATEGORY_SUBLIMIT_CENTS[category])
        gross += total

    after_deductible = max(0, gross - DEDUCTIBLE_CENTS)
    return min(after_deductible, subscriber["insurance_remaining_cents"])


# --- engagement capacity ---------------------------------------------------

def engagement_capacity_exceeded(specialist, new_start, new_end):
    """Half-open intervals [start, end), each extended by a 60-minute cool-down
    past its end for capacity accounting. Reject when at any instant the number of
    buffer-extended intervals covering it would exceed max_concurrent_engagements."""
    intervals = [
        (e["_ws"], e["_we"] + ENGAGEMENT_BUFFER)
        for e in db.engagements.values()
        if e["specialist_id"] == specialist["id"]
    ]
    intervals.append((new_start, new_end + ENGAGEMENT_BUFFER))

    events = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    # At an instant t, an interval ending exactly at t no longer covers t, so
    # the -1 events are processed before the +1 events at the same instant.
    events.sort(key=lambda ev: (ev[0], ev[1]))

    running = 0
    peak = 0
    for _, delta in events:
        running += delta
        peak = max(peak, running)
    return peak > specialist["max_concurrent_engagements"]


# --- thaw window -----------------------------------------------------------

def thaw_window_is_open(window):
    return window["_ws"] <= now() <= window["_we"]


def thaw_window_overlaps(profile_id, new_start, new_end):
    """Closed intervals, capacity 1. Touching endpoints DO collide."""
    for w in db.thaw_windows.values():
        if w["bureau_profile_id"] != profile_id:
            continue
        if new_start <= w["_we"] and w["_ws"] <= new_end:
            return True
    return False


# --- cascades --------------------------------------------------------------

def resolve_origin_alert(case):
    """Cross-entity hop fired when a RestorationCase reaches RESOLVED."""
    alert = db.alerts.get(case["origin_alert_id"])
    if alert is None or alert["status"] not in CONFIRMED:
        return None
    alert["status"] = "RESOLVED"
    touch(alert)
    return alert
