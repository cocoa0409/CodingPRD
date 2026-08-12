"""Domain constants, validation helpers, recomputes, cascades, calculations,
and serializers for the Physician Onboarding & Practice Ramp API."""

import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, bump, fmt_clock
from errors import (
    ApiError, ERR_VALIDATION,
)

# ---------------------------------------------------------------------------
# Constants (PRD section 3, scaffold calculation tables)
# ---------------------------------------------------------------------------

SPECIALTIES = ["FAMILY_MEDICINE", "INTERNAL_MEDICINE", "CARDIOLOGY", "ORTHOPEDICS", "PEDIATRICS"]
HIRE_TYPES = ["NEW_GRAD", "EXPERIENCED", "LEADERSHIP"]
ITEM_TYPES = [
    "STATE_LICENSE", "DEA_REGISTRATION", "BOARD_CERTIFICATION",
    "PAYER_ENROLLMENT_MEDICARE", "PAYER_ENROLLMENT_COMMERCIAL", "HOSPITAL_PRIVILEGES",
]
REQUIRED_CREDENTIAL_TYPES = {"STATE_LICENSE", "DEA_REGISTRATION", "PAYER_ENROLLMENT_MEDICARE"}
PAYER_ITEM_TYPES = {"PAYER_ENROLLMENT_MEDICARE", "PAYER_ENROLLMENT_COMMERCIAL"}
MODULE_CODES = ["EHR_FUNDAMENTALS", "ORDER_ENTRY", "NOTE_TEMPLATES", "BILLING"]
BASE_REQUIRED_MODULES = ["EHR_FUNDAMENTALS", "ORDER_ENTRY", "NOTE_TEMPLATES"]
BLOCK_TYPES = ["CLINIC", "PROCEDURE", "OR", "ADMIN"]
COUNTING_BLOCK_TYPES = {"CLINIC", "PROCEDURE", "OR"}
EVENT_TYPES = ["COMMUNITY_TALK", "REFERRAL_DINNER", "MEDIA", "OPEN_HOUSE"]
DAY_MARKERS = ["D30", "D90", "D180", "D270", "D365"]
SENTIMENTS = ["POSITIVE", "NEUTRAL", "CONCERN", "CRISIS"]
SNAPSHOT_VARIANTS = ["TRAILING", "LEADING"]

OFFER_STATUSES = ["DRAFT", "EXTENDED", "COUNTERED", "ACCEPTED", "EXECUTED",
                  "SUPERSEDED", "WITHDRAWN", "DECLINED", "EXPIRED"]
NON_TERMINAL_OFFER_STATUSES = {"DRAFT", "EXTENDED", "COUNTERED", "ACCEPTED"}

SLA_DAYS = {
    "STATE_LICENSE": 90,
    "DEA_REGISTRATION": 45,
    "BOARD_CERTIFICATION": 30,
    "PAYER_ENROLLMENT_MEDICARE": 60,
    "PAYER_ENROLLMENT_COMMERCIAL": 75,
    "HOSPITAL_PRIVILEGES": 50,
}
START_DATE_BUFFER_DAYS = 14
MAX_NEGOTIATION_ROUNDS = 5
PASS_SCORE = 80
REPORT_GRACE_DAYS = 15

REQUIRED_WEEKLY_CLINIC_MINUTES = {
    "FAMILY_MEDICINE": 1200,
    "INTERNAL_MEDICINE": 1200,
    "PEDIATRICS": 1100,
    "CARDIOLOGY": 1000,
    "ORTHOPEDICS": 900,
}

COLLECTION_CREDIT_CAP_CENTS = 1_800_000
MISSED_PENALTY_PCT = Decimal("0.10")
FORGIVENESS_PER_ATTAINED_MONTH_CENTS = 100_000

WRVU_TARGET_CURVE = [100, 150, 200, 250, 300, 350, 400, 420, 440, 460, 480, 500]
RAMP_FILL_CURVE = [
    Decimal("0.10"), Decimal("0.18"), Decimal("0.26"), Decimal("0.34"),
    Decimal("0.42"), Decimal("0.50"), Decimal("0.58"), Decimal("0.65"),
    Decimal("0.71"), Decimal("0.77"), Decimal("0.82"), Decimal("0.85"),
]

WEIGHT_MILESTONE = Decimal("0.35")
WEIGHT_PANEL = Decimal("0.25")
WEIGHT_SENTIMENT = Decimal("0.25")
WEIGHT_SCHEDULE = Decimal("0.15")

SENTIMENT_VALUES = {"POSITIVE": 0, "NEUTRAL": 40, "CONCERN": 70, "CRISIS": 100}

IN_FLIGHT_CREDENTIAL_STATUSES = {"PENDING", "DOCS_SUBMITTED", "VERIFIED", "FILED"}
EXPIRABLE_CREDENTIAL_STATUSES = {"PENDING", "DOCS_SUBMITTED", "VERIFIED", "FILED", "APPROVED"}

# ---------------------------------------------------------------------------
# Parsing / validation helpers
# ---------------------------------------------------------------------------


def get_body():
    from flask import request
    return request.get_json(silent=True) or {}


def parse_date(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400, "%s must be an ISO date string" % field)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ApiError(ERR_VALIDATION, 400, "%s must be a valid ISO date (YYYY-MM-DD)" % field)


def parse_datetime(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400, "%s must be an ISO 8601 datetime string" % field)
    text = value.strip()
    parsed = None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        pass
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise ApiError(ERR_VALIDATION, 400, "%s must be a valid ISO 8601 datetime" % field)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_present(body, field):
    value = body.get(field)
    if value is None:
        raise ApiError(ERR_VALIDATION, 400, "%s is required" % field)
    return value


def req_str(body, field):
    value = req_present(body, field)
    if not isinstance(value, str) or value == "":
        raise ApiError(ERR_VALIDATION, 400, "%s must be a non-empty string" % field)
    return value


def opt_str(body, field):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400, "%s must be a string" % field)
    return value


def req_int(body, field):
    value = req_present(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_VALIDATION, 400, "%s must be an integer" % field)
    return value


def opt_int(body, field):
    value = body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_VALIDATION, 400, "%s must be an integer" % field)
    return value


def opt_bool(body, field, default=False):
    value = body.get(field)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ApiError(ERR_VALIDATION, 400, "%s must be a boolean" % field)
    return value


def req_enum(body, field, allowed):
    value = req_present(body, field)
    if value not in allowed:
        raise ApiError(ERR_VALIDATION, 400, "%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def non_negative(value, field):
    if value < 0:
        raise ApiError(ERR_VALIDATION, 400, "%s must not be negative" % field)
    return value


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------


def clock():
    return store.clock


def clock_date():
    return store.clock.date()


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def case_of_id(case_id):
    return store.cases.get(case_id)


def case_for_physician(physician_id):
    for c in store.cases.values():
        if c["physician_id"] == physician_id:
            return c
    return None


def items_of_case(case_id):
    return [i for i in store.credential_items.values() if i["onboarding_case_id"] == case_id]


def offers_of_case(case_id):
    return [o for o in store.offers.values() if o["onboarding_case_id"] == case_id]


def plan_of_case(case_id):
    for p in store.training_plans.values():
        if p["onboarding_case_id"] == case_id:
            return p
    return None


def modules_of_plan(plan_id):
    return [m for m in store.training_modules.values() if m["training_plan_id"] == plan_id]


def templates_of_case(case_id):
    return [t for t in store.schedule_templates.values() if t["onboarding_case_id"] == case_id]


def panel_of_case(case_id):
    for p in store.panels.values():
        if p["onboarding_case_id"] == case_id:
            return p
    return None


def campaigns_of_case(case_id):
    return [c for c in store.campaigns.values() if c["onboarding_case_id"] == case_id]


def guarantee_of_case(case_id):
    for g in store.guarantees.values():
        if g["onboarding_case_id"] == case_id:
            return g
    return None


def milestones_of_case(case_id):
    return [m for m in store.milestones.values() if m["onboarding_case_id"] == case_id]


def assignments_of_case(case_id):
    return [a for a in store.assignments.values() if a["onboarding_case_id"] == case_id]


def checkins_of_assignment(mentorship_id):
    return [c for c in store.checkins.values() if c["mentorship_id"] == mentorship_id]


def executed_offer_of_case(case_id):
    for o in store.offers.values():
        if o["onboarding_case_id"] == case_id and o["status"] == "EXECUTED":
            return o
    return None


# ---------------------------------------------------------------------------
# Recomputes (PRD 2.6)
# ---------------------------------------------------------------------------


def recompute_credential_status(case):
    items = items_of_case(case["id"])
    if any(i["status"] in ("BLOCKED", "EXPIRED", "LAPSED") for i in items):
        case["credential_status"] = "BLOCKED"
        return
    approved_types = {i["item_type"] for i in items if i["status"] == "APPROVED"}
    if REQUIRED_CREDENTIAL_TYPES <= approved_types:
        case["credential_status"] = "COMPLETE"
    elif items:
        case["credential_status"] = "IN_PROGRESS"
    else:
        case["credential_status"] = "NOT_STARTED"


def recompute_training_status(case):
    plan = plan_of_case(case["id"])
    if plan is None:
        case["training_status"] = "NOT_STARTED"
    elif plan["status"] == "COMPLETE":
        case["training_status"] = "COMPLETE"
    else:
        case["training_status"] = "IN_PROGRESS"


def recompute_practice(case):
    physician = store.physicians.get(case["physician_id"])
    required = REQUIRED_WEEKLY_CLINIC_MINUTES[physician["specialty"]]
    active = [t for t in templates_of_case(case["id"]) if t["status"] == "ACTIVE"]
    minutes = sum(
        t["end_minute"] - t["start_minute"]
        for t in active if t["block_type"] in COUNTING_BLOCK_TYPES
    )
    case["weekly_active_minutes"] = minutes
    if minutes >= required:
        case["practice_status"] = "READY"
    elif active:
        case["practice_status"] = "BUILDING"
    else:
        case["practice_status"] = "PLANNING"


def components_ready(case):
    return (
        case["credential_status"] == "COMPLETE"
        and case["training_status"] == "COMPLETE"
        and case["practice_status"] == "READY"
    )


def recompute_posture(case):
    if executed_offer_of_case(case["id"]) is None:
        case["posture"] = "PRE_CONTRACT"
        return
    panel = panel_of_case(case["id"])
    if panel is not None and panel["status"] == "OPEN":
        case["posture"] = "LIVE"
        return
    if case["credential_status"] != "COMPLETE":
        case["posture"] = "CREDENTIALING"
    elif case["training_status"] != "COMPLETE" or case["practice_status"] != "READY":
        case["posture"] = "RAMP_PREP"
    else:
        case["posture"] = "GO_LIVE_READY"


def freeze_panel_if_unready(case):
    """Credential expiry / template retirement cascade: an OPEN panel whose
    readiness components no longer all hold freezes."""
    panel = panel_of_case(case["id"])
    if panel is not None and panel["status"] == "OPEN" and not components_ready(case):
        panel["status"] = "FROZEN"
        bump(panel)


def recompute_case_counts(case):
    milestones = milestones_of_case(case["id"])
    case["attained_milestone_count"] = sum(
        1 for m in milestones if m["status"] == "ATTESTED" and m["attained"] is True
    )
    case["missed_milestone_count"] = sum(
        1 for m in milestones
        if (m["status"] == "ATTESTED" and m["attained"] is False) or m["status"] == "LAPSED"
    )


# ---------------------------------------------------------------------------
# Credential dependency graph (PRD 3.3)
# ---------------------------------------------------------------------------


def cascade_credential_failure(failed_item):
    """BFS over dependents: in-flight dependents become BLOCKED (recording
    blocked_from_status); APPROVED dependents become LAPSED; transitive."""
    queue = [failed_item]
    seen = {failed_item["id"]}
    while queue:
        node = queue.pop(0)
        for item in store.credential_items.values():
            if node["id"] not in item["depends_on_item_ids"]:
                continue
            if item["id"] in seen:
                continue
            if item["status"] in IN_FLIGHT_CREDENTIAL_STATUSES:
                item["blocked_from_status"] = item["status"]
                item["status"] = "BLOCKED"
                bump(item)
                seen.add(item["id"])
                queue.append(item)
            elif item["status"] == "APPROVED":
                item["status"] = "LAPSED"
                bump(item)
                seen.add(item["id"])
                queue.append(item)


def restore_blocked_items(case_id):
    """Every BLOCKED item whose dependencies are all APPROVED returns to its
    recorded blocked_from_status (blocked_from_status cleared)."""
    changed = True
    while changed:
        changed = False
        for item in items_of_case(case_id):
            if item["status"] != "BLOCKED":
                continue
            deps_ok = all(
                store.credential_items.get(dep_id) is not None
                and store.credential_items[dep_id]["status"] == "APPROVED"
                for dep_id in item["depends_on_item_ids"]
            )
            if deps_ok:
                item["status"] = item["blocked_from_status"]
                item["blocked_from_status"] = None
                bump(item)
                changed = True


def critical_path_days(case_id):
    """Longest remaining-dependency-chain length over the case's credential DAG."""
    items = items_of_case(case_id)
    memo = {}

    def chain(item):
        if item["id"] in memo:
            return memo[item["id"]]
        remaining = 0 if item["status"] == "APPROVED" else SLA_DAYS[item["item_type"]]
        best = 0
        for dep_id in item["depends_on_item_ids"]:
            dep = store.credential_items.get(dep_id)
            if dep is not None:
                best = max(best, chain(dep))
        memo[item["id"]] = remaining + best
        return memo[item["id"]]

    return max((chain(i) for i in items), default=0)


# ---------------------------------------------------------------------------
# Milestone month arithmetic (PRD 3.8)
# ---------------------------------------------------------------------------


def month_for_offset(start_month, offset):
    """start_month is 'YYYY-MM'; offset is 1-based."""
    year, month = int(start_month[0:4]), int(start_month[5:7])
    total = (year * 12 + (month - 1)) + (offset - 1)
    return total // 12, total % 12 + 1


def month_end_for_offset(start_month, offset):
    year, month = month_for_offset(start_month, offset)
    last = calendar.monthrange(year, month)[1]
    return datetime(year, month, last).date()


def reporting_deadline(start_month, offset):
    return month_end_for_offset(start_month, offset) + timedelta(days=REPORT_GRACE_DAYS)


# ---------------------------------------------------------------------------
# Income guarantee draws (PRD 3.8; ACTUAL and PROJECTED variants)
# ---------------------------------------------------------------------------


def guarantee_derived(guarantee):
    milestones = {
        m["month_offset"]: m
        for m in milestones_of_case(guarantee["onboarding_case_id"])
        if m["month_offset"] <= guarantee["term_months"]
    }
    total_advanced = 0
    unreconciled = 0
    months_reconciled = 0
    attained_count = 0
    for offset in range(1, guarantee["term_months"] + 1):
        m = milestones.get(offset)
        if m is None or m["status"] in ("PENDING", "REPORTED"):
            unreconciled += 1
            continue
        months_reconciled += 1
        if m["status"] == "LAPSED":
            total_advanced += guarantee["monthly_guarantee_cents"]
            continue
        # ATTESTED
        base_credit = min(m["collections_cents"], COLLECTION_CREDIT_CAP_CENTS)
        if m["attained"]:
            credit = base_credit
            attained_count += 1
        else:
            credit = int(
                (Decimal(base_credit) * (Decimal(1) - MISSED_PENALTY_PCT)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        total_advanced += max(0, guarantee["monthly_guarantee_cents"] - credit)
    projected = total_advanced + guarantee["monthly_guarantee_cents"] * unreconciled
    forgiveness = FORGIVENESS_PER_ATTAINED_MONTH_CENTS * attained_count
    outstanding = max(
        0, total_advanced - guarantee["total_repaid_cents"] - forgiveness
    )
    return {
        "months_reconciled": months_reconciled,
        "total_advanced_cents": total_advanced,
        "projected_total_draw_cents": projected,
        "forgiveness_accrued_cents": forgiveness,
        "outstanding_balance_cents": outstanding,
    }


# ---------------------------------------------------------------------------
# Retention risk score (PRD 3.9; TRAILING / LEADING variants)
# ---------------------------------------------------------------------------


def _round2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_risk(case, variant):
    guarantee = guarantee_of_case(case["id"])
    panel = panel_of_case(case["id"])
    physician = store.physicians.get(case["physician_id"])
    today = clock_date()

    milestones = milestones_of_case(case["id"])
    by_offset = {m["month_offset"]: m for m in milestones}
    term_months = guarantee["term_months"] if guarantee else 0

    # --- milestone_risk ---
    if variant == "TRAILING":
        attested = [m for m in milestones if m["status"] == "ATTESTED"]
        missed = [m for m in attested if m["attained"] is False]
        if attested:
            milestone_risk = Decimal(len(missed)) / Decimal(len(attested)) * 100
        else:
            milestone_risk = Decimal(0)
    else:  # LEADING
        due_offsets = [
            off for off in range(1, term_months + 1)
            if today > reporting_deadline(guarantee["start_month"], off)
        ]
        if not due_offsets:
            milestone_risk = Decimal(0)
        else:
            missed = 0
            for off in due_offsets:
                m = by_offset.get(off)
                if m is None or m["status"] in ("PENDING", "REPORTED", "LAPSED"):
                    missed += 1  # unreported elapsed months count as missed
                elif m["status"] == "ATTESTED" and m["attained"] is False:
                    missed += 1
            milestone_risk = Decimal(missed) / Decimal(len(due_offsets)) * 100

    # --- panel_risk ---
    capacity = panel["capacity"] if panel else 0
    current_size = panel["current_size"] if panel else 0
    if guarantee:
        sy, sm = int(guarantee["start_month"][0:4]), int(guarantee["start_month"][5:7])
        month_offset = max(1, (today.year - sy) * 12 + (today.month - sm) + 1)
    else:
        month_offset = 1
    idx = min(month_offset, len(RAMP_FILL_CURVE))
    if variant == "LEADING":
        idx = min(month_offset + 1, len(RAMP_FILL_CURVE))
    expected_fill = Decimal(capacity) * RAMP_FILL_CURVE[idx - 1]
    if expected_fill == 0:
        panel_risk = Decimal(0)
    else:
        panel_risk = max(Decimal(0), expected_fill - Decimal(current_size)) / expected_fill * 100

    # --- sentiment_risk ---
    sentiments = []
    for assignment in assignments_of_case(case["id"]):
        for checkin in checkins_of_assignment(assignment["id"]):
            sentiments.append(SENTIMENT_VALUES[checkin["sentiment"]])
    if sentiments:
        sentiment_risk = Decimal(sum(sentiments)) / Decimal(len(sentiments))
    else:
        sentiment_risk = Decimal(50)

    # --- schedule_risk ---
    required = REQUIRED_WEEKLY_CLINIC_MINUTES[physician["specialty"]]
    shortfall = max(0, required - case["weekly_active_minutes"])
    schedule_risk = Decimal(shortfall) / Decimal(required) * 100

    # Components rounded to 2dp HALF_UP before weighting; each weighted term
    # rounded to 2dp HALF_UP, then summed (pinned order).
    milestone_risk = _round2(milestone_risk)
    panel_risk = _round2(panel_risk)
    sentiment_risk = _round2(sentiment_risk)
    schedule_risk = _round2(schedule_risk)

    score = (
        _round2(WEIGHT_MILESTONE * milestone_risk)
        + _round2(WEIGHT_PANEL * panel_risk)
        + _round2(WEIGHT_SENTIMENT * sentiment_risk)
        + _round2(WEIGHT_SCHEDULE * schedule_risk)
    )

    if score >= 75:
        band = "CRITICAL"
    elif score >= 50:
        band = "HIGH"
    elif score >= 25:
        band = "MODERATE"
    else:
        band = "LOW"

    return {
        "milestone_risk": float(milestone_risk),
        "panel_risk": float(panel_risk),
        "sentiment_risk": float(sentiment_risk),
        "schedule_risk": float(schedule_risk),
        "score": float(score),
        "risk_band": band,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_physician(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "specialty": p["specialty"],
        "email": p["email"],
        "hire_type": p["hire_type"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_case(c):
    return {
        "id": c["id"],
        "physician_id": c["physician_id"],
        "target_start_date": c["target_start_date"],
        "actual_start_date": c["actual_start_date"],
        "case_status": c["case_status"],
        "credential_status": c["credential_status"],
        "training_status": c["training_status"],
        "practice_status": c["practice_status"],
        "posture": c["posture"],
        "weekly_active_minutes": c["weekly_active_minutes"],
        "attained_milestone_count": c["attained_milestone_count"],
        "missed_milestone_count": c["missed_milestone_count"],
        "latest_risk_score": c["latest_risk_score"],
        "latest_risk_band": c["latest_risk_band"],
        "at_risk": c["at_risk"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_offer(o):
    return {
        "id": o["id"],
        "onboarding_case_id": o["onboarding_case_id"],
        "base_salary_cents": o["base_salary_cents"],
        "signing_bonus_cents": o["signing_bonus_cents"],
        "guarantee_monthly_cents": o["guarantee_monthly_cents"],
        "guarantee_term_months": o["guarantee_term_months"],
        "panel_capacity": o["panel_capacity"],
        "proposed_start_date": o["proposed_start_date"],
        "expires_at": o["expires_at"],
        "negotiation_round": o["negotiation_round"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_credential_item(i):
    return {
        "id": i["id"],
        "onboarding_case_id": i["onboarding_case_id"],
        "item_type": i["item_type"],
        "payer_code": i["payer_code"],
        "depends_on_item_ids": list(i["depends_on_item_ids"]),
        "document_ref": i["document_ref"],
        "expires_on": i["expires_on"],
        "submitted_by_user_id": i["submitted_by_user_id"],
        "verified_by_user_id": i["verified_by_user_id"],
        "blocked_from_status": i["blocked_from_status"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_plan(p):
    return {
        "id": p["id"],
        "onboarding_case_id": p["onboarding_case_id"],
        "required_module_count": p["required_module_count"],
        "templates_required": p["templates_required"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_module(m):
    return {
        "id": m["id"],
        "training_plan_id": m["training_plan_id"],
        "module_code": m["module_code"],
        "required": m["required"],
        "scheduled_on": m["scheduled_on"],
        "score": m["score"],
        "templates_built_count": m["templates_built_count"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_template(t):
    return {
        "id": t["id"],
        "onboarding_case_id": t["onboarding_case_id"],
        "weekday": t["weekday"],
        "start_minute": t["start_minute"],
        "end_minute": t["end_minute"],
        "block_type": t["block_type"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_panel(p):
    return {
        "id": p["id"],
        "onboarding_case_id": p["onboarding_case_id"],
        "capacity": p["capacity"],
        "current_size": p["current_size"],
        "opened_at": p["opened_at"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_campaign(c):
    return {
        "id": c["id"],
        "onboarding_case_id": c["onboarding_case_id"],
        "name": c["name"],
        "budget_cents": c["budget_cents"],
        "spent_cents": c["spent_cents"],
        "referrals_attributed": c["referrals_attributed"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_event(e):
    return {
        "id": e["id"],
        "campaign_id": e["campaign_id"],
        "event_type": e["event_type"],
        "start_date": e["start_date"],
        "end_date": e["end_date"],
        "cost_cents": e["cost_cents"],
        "venue": e["venue"],
        "referrals_generated": e["referrals_generated"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_guarantee(g):
    derived = guarantee_derived(g)
    return {
        "id": g["id"],
        "onboarding_case_id": g["onboarding_case_id"],
        "monthly_guarantee_cents": g["monthly_guarantee_cents"],
        "term_months": g["term_months"],
        "start_month": g["start_month"],
        "months_reconciled": derived["months_reconciled"],
        "total_advanced_cents": derived["total_advanced_cents"],
        "projected_total_draw_cents": derived["projected_total_draw_cents"],
        "forgiveness_accrued_cents": derived["forgiveness_accrued_cents"],
        "total_repaid_cents": g["total_repaid_cents"],
        "outstanding_balance_cents": derived["outstanding_balance_cents"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_milestone(m):
    return {
        "id": m["id"],
        "onboarding_case_id": m["onboarding_case_id"],
        "month_offset": m["month_offset"],
        "target_wrvu": m["target_wrvu"],
        "actual_wrvu": m["actual_wrvu"],
        "collections_cents": m["collections_cents"],
        "attained": m["attained"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_assignment(a):
    return {
        "id": a["id"],
        "onboarding_case_id": a["onboarding_case_id"],
        "mentor_physician_id": a["mentor_physician_id"],
        "checkins_recorded": a["checkins_recorded"],
        "escalated": a["escalated"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_checkin(c):
    return {
        "id": c["id"],
        "mentorship_id": c["mentorship_id"],
        "day_marker": c["day_marker"],
        "sentiment": c["sentiment"],
        "occurred_on": c["occurred_on"],
        "notes": c["notes"],
        "created_at": c["created_at"],
    }


def serialize_snapshot(s):
    return {
        "id": s["id"],
        "onboarding_case_id": s["onboarding_case_id"],
        "variant": s["variant"],
        "milestone_risk": s["milestone_risk"],
        "panel_risk": s["panel_risk"],
        "sentiment_risk": s["sentiment_risk"],
        "schedule_risk": s["schedule_risk"],
        "score": s["score"],
        "risk_band": s["risk_band"],
        "created_at": s["created_at"],
    }
