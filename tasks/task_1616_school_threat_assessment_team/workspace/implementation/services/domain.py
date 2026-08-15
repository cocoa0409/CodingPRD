"""Core domain logic: calculations, state transitions, cascades, sweeps.

All business rules per PRD section 3 and scaffold sections 1.2-1.3.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    raise_err,
    ERR_CASE_NOT_FOUND,
    ERR_CHECKIN_DAY_CONFLICT,
    ERR_INVALID_DUE_DATE,
    ERR_INVALID_REQUEST,
    ERR_SCHOOL_NOT_FOUND,
)
from util import round_half_up_int, round_half_up_2dp, sort_by_created_at


# ---------------------------------------------------------------------------
# Constants (scaffold section 1.3 / PRD section 3)
# ---------------------------------------------------------------------------

SCREENING_FACTORS = (
    "threat_of_violence",
    "weapon_mention",
    "target_identified",
    "plan_described",
    "prior_incidents",
    "current_distress",
)
SUBSTANTIVE_THRESHOLD = 3

FACTOR_WEIGHTS = {
    "WEAPON_ACCESS": 20,
    "PLAN_SPECIFICITY": 15,
    "GRIEVANCE_HISTORY": 10,
    "PEER_REPORTS": 5,
    "BEHAVIORAL_ESCALATION": 10,
    "SUPERVISION_GAP": 8,
}
FACTOR_CODES = set(FACTOR_WEIGHTS)
CRITICAL_BONUS_STANDARD = 10
CRITICAL_BONUS_EXPEDITED = 15
EXPEDITED_MULTIPLIER = Decimal("1.5")
EXPEDITED_COUNTED_CODES = {"WEAPON_ACCESS", "PLAN_SPECIFICITY"}

RISK_LEVELS = ("LOW", "MODERATE", "HIGH", "IMMINENT")
DEFAULT_CADENCE_DAYS = {"IMMINENT": 3, "HIGH": 7, "MODERATE": 14, "LOW": 30}
MAX_CADENCE_DAYS = {"IMMINENT": 7, "HIGH": 14, "MODERATE": 30, "LOW": 60}

URGENT_SLA_HOURS = 72
ROUTINE_SLA_HOURS = 240

AUTO_REFERRAL_AGENCY = "DISTRICT_SRT"
REENTRY_CHECKIN_DAYS = 30

MAX_INTERVIEWS_PER_CASE = 8

CASE_STATUSES = {
    "INTAKE", "TRIAGED", "UNDER_ASSESSMENT", "PLAN_ACTIVE",
    "REMOVED", "CLOSED_NO_THREAT", "CLOSED_MANAGED", "PURGED",
}
REFERRAL_OPEN_CASE_STATUSES = {"TRIAGED", "UNDER_ASSESSMENT", "PLAN_ACTIVE", "REMOVED"}


# ---------------------------------------------------------------------------
# Audit trail (PRD section 2.8)
# ---------------------------------------------------------------------------

def audit(case_id: str, action: str, detail: str, actor_user_id: str, actor_role: str) -> dict:
    event = {
        "case_id": case_id,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "action": action,
        "detail": detail,
    }
    db.stamp_new_light(event)
    db.audit_events[event["id"]] = event
    return event


def audit_system(case_id: str, action: str, detail: str) -> dict:
    """Automatic transitions record the literal actor 'system'/'system'."""
    return audit(case_id, action, detail, "system", "system")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_case_or_404(case_id: str) -> dict:
    case = db.threat_cases.get(case_id)
    if case is None:
        raise_err(ERR_CASE_NOT_FOUND, "Threat case does not exist")
    return case


def get_school_for_case(case: dict) -> dict | None:
    return db.schools.get(case["school_id"])


def require_school(school_id: str) -> dict:
    school = db.schools.get(school_id)
    if school is None:
        raise_err(ERR_SCHOOL_NOT_FOUND, "school_id references a non-existent school")
    return school


def case_children(store: dict, case_id: str) -> list[dict]:
    return sort_by_created_at([e for e in store.values() if e.get("case_id") == case_id])


def active_plan_for_case(case_id: str) -> dict | None:
    for plan in case_children(db.management_plans, case_id):
        if plan["status"] == "ACTIVE":
            return plan
    return None


def has_finalized_assessment(case_id: str) -> bool:
    return any(a["status"] == "FINALIZED" for a in case_children(db.risk_assessments, case_id))


def has_open_assessment(case_id: str) -> bool:
    return any(
        a["status"] in ("DRAFT", "SUBMITTED")
        for a in case_children(db.risk_assessments, case_id)
    )


def has_open_reentry_plan(case_id: str) -> bool:
    return any(
        p["status"] in ("PROPOSED", "APPROVED")
        for p in case_children(db.reentry_plans, case_id)
    )


def has_acknowledged_le_referral(case_id: str) -> bool:
    return any(
        r["referral_type"] == "LAW_ENFORCEMENT" and r["status"] == "ACKNOWLEDGED"
        for r in case_children(db.referrals, case_id)
    )


def has_live_le_referral(case_id: str) -> bool:
    """LAW_ENFORCEMENT referral in SENT or ACKNOWLEDGED (IMMINENT cascade gate)."""
    return any(
        r["referral_type"] == "LAW_ENFORCEMENT" and r["status"] in ("SENT", "ACKNOWLEDGED")
        for r in case_children(db.referrals, case_id)
    )


def checkin_blocking_exists(case_id: str, due_date: str, exclude_id: str | None = None) -> bool:
    """A SCHEDULED or MISSED check-in already occupies the case's calendar day."""
    for chk in case_children(db.check_ins, case_id):
        if chk["id"] == exclude_id:
            continue
        if chk["status"] in ("SCHEDULED", "MISSED") and chk["due_date"] == due_date:
            return True
    return False


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_screening(body: dict) -> tuple[int, str]:
    score = 0
    for name in SCREENING_FACTORS:
        value = body.get(name, False)
        if value is None:
            value = False
        if not isinstance(value, bool):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
        if value:
            score += 1
    outcome = "SUBSTANTIVE" if score >= SUBSTANTIVE_THRESHOLD else "NON_SUBSTANTIVE"
    return score, outcome


def validate_factors(factors) -> list:
    if not isinstance(factors, list):
        raise_err(ERR_INVALID_REQUEST, "Field factors must be an array")
    for entry in factors:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "factors entries must be objects")
        code = entry.get("factor_code")
        if not isinstance(code, str) or code not in FACTOR_CODES:
            raise_err(ERR_INVALID_REQUEST, "factor_code must be one of the declared codes")
        severity = entry.get("severity")
        if isinstance(severity, bool) or not isinstance(severity, int) or severity < 0 or severity > 3:
            raise_err(ERR_INVALID_REQUEST, "severity must be an integer in 0..3")
    return factors


def compute_assessment_score(variant: str, factors: list) -> tuple[int, str]:
    """assessment_risk_score per scaffold section 1.3 / PRD section 3.4."""
    any_critical = any(f["severity"] == 3 for f in factors)
    if variant == "STANDARD":
        base = sum(FACTOR_WEIGHTS[f["factor_code"]] * f["severity"] for f in factors)
        if any_critical:
            base += CRITICAL_BONUS_STANDARD
    else:  # EXPEDITED
        counted = sum(
            FACTOR_WEIGHTS[f["factor_code"]] * f["severity"]
            for f in factors
            if f["factor_code"] in EXPEDITED_COUNTED_CODES
        )
        base = round_half_up_int(Decimal(counted) * EXPEDITED_MULTIPLIER)
        if any_critical:
            base += CRITICAL_BONUS_EXPEDITED
    raw_score = max(0, min(100, base))
    if raw_score < 20:
        level = "LOW"
    elif raw_score < 40:
        level = "MODERATE"
    elif raw_score < 60:
        level = "HIGH"
    else:
        level = "IMMINENT"
    return raw_score, level


def retention_purge_date(closed_dt: datetime, retention_days: int) -> str:
    return (closed_dt.date() + timedelta(days=retention_days)).isoformat()


def compute_referral_sla(sent_dt: datetime, urgency: str) -> str:
    hours = URGENT_SLA_HOURS if urgency == "URGENT" else ROUTINE_SLA_HOURS
    return db.format_iso(sent_dt + timedelta(hours=hours))


def next_checkin_due_date(plan: dict, completion_date: date) -> str:
    """monitoring_next_due_date per PRD section 3.5."""
    cadence = plan["cadence_days"]
    if plan["cadence_mode"] == "FROM_COMPLETION":
        return (completion_date + timedelta(days=cadence)).isoformat()
    # FIXED_ANCHOR: earliest grid date strictly after the completion date.
    anchor = db.parse_iso(plan["activated_at"]).date()
    k = (completion_date - anchor).days // cadence + 1
    return (anchor + timedelta(days=k * cadence)).isoformat()


# ---------------------------------------------------------------------------
# Referral creation (manual send and automatic cascades)
# ---------------------------------------------------------------------------

def create_referral(case: dict, referral_type: str, agency_name: str, urgency: str,
                    auto_created: bool) -> dict:
    now = db.clock()
    referral = {
        "case_id": case["id"],
        "referral_type": referral_type,
        "agency_name": agency_name,
        "urgency": urgency,
        "status": "SENT",
        "auto_created": auto_created,
        "sla_due_at": compute_referral_sla(now, urgency),
        "sla_breached": False,
        "decline_reason": None,
    }
    db.stamp_new(referral)
    db.referrals[referral["id"]] = referral
    return referral


def auto_create_le_referral(case: dict, actor_user_id: str, actor_role: str, reason: str) -> dict:
    referral = create_referral(case, "LAW_ENFORCEMENT", AUTO_REFERRAL_AGENCY, "URGENT", True)
    audit(
        case["id"],
        "REFERRAL_AUTO_CREATED",
        f"Auto-created URGENT LAW_ENFORCEMENT referral to {AUTO_REFERRAL_AGENCY} ({reason})",
        actor_user_id,
        actor_role,
    )
    return referral


# ---------------------------------------------------------------------------
# Check-in auto-creation
# ---------------------------------------------------------------------------

def auto_create_checkin(case_id: str, due_date: str, respect_day_exclusion: bool = True) -> dict | None:
    """Auto-created check-in; optionally suppressed when a SCHEDULED/MISSED
    check-in already occupies the case's calendar day (plan activation and
    completion chaining). The re-entry check-in is created unconditionally."""
    if respect_day_exclusion and checkin_blocking_exists(case_id, due_date):
        return None
    checkin = {
        "case_id": case_id,
        "due_date": due_date,
        "status": "SCHEDULED",
        "auto_created": True,
        "outcome": None,
        "notes": None,
        "completed_at": None,
    }
    db.stamp_new(checkin)
    db.check_ins[checkin["id"]] = checkin
    return checkin


# ---------------------------------------------------------------------------
# Clock-driven transitions (PRD section 2.5)
# ---------------------------------------------------------------------------

def apply_clock_transitions(new_dt: datetime) -> None:
    """Apply pending automatic transitions after a clock advance:
    SCHEDULED check-ins past their due date become MISSED (with the
    consecutive-miss escalation cascade), and SENT referrals whose sla_due_at
    the clock has passed are marked breached (with case escalation)."""
    new_date = new_dt.date()
    touched_cases: set[str] = set()

    def touch_case_once(case: dict) -> None:
        if case["id"] not in touched_cases:
            touched_cases.add(case["id"])
            db.touch(case)

    # --- Check-in MISS sweep (created_at ASC) ---
    for chk in sort_by_created_at(list(db.check_ins.values())):
        if chk["status"] != "SCHEDULED":
            continue
        if date.fromisoformat(chk["due_date"]) >= new_date:
            continue
        chk["status"] = "MISSED"
        db.touch(chk)
        case = db.threat_cases.get(chk["case_id"])
        if case is None:
            continue
        case["consecutive_missed_count"] = case.get("consecutive_missed_count", 0) + 1
        audit_system(
            case["id"],
            "CHECKIN_MISSED",
            f"Monitoring check-in {chk['id']} due {chk['due_date']} was missed",
        )
        if case["consecutive_missed_count"] == 2:
            # PRD section 3.5: "the moment that count reaches two, the case's
            # escalation_flag is set and ESCALATION_RAISED is written".
            case["escalation_flag"] = True
            audit_system(
                case["id"],
                "ESCALATION_RAISED",
                "Escalation raised: consecutive missed check-ins reached 2",
            )
        touch_case_once(case)

    # --- Referral SLA breach sweep (created_at ASC) ---
    for ref in sort_by_created_at(list(db.referrals.values())):
        if ref["status"] != "SENT" or ref["sla_breached"]:
            continue
        if db.parse_iso(ref["sla_due_at"]) >= new_dt:
            continue
        ref["sla_breached"] = True
        db.touch(ref)
        case = db.threat_cases.get(ref["case_id"])
        if case is None:
            continue
        case["escalation_flag"] = True
        audit_system(
            case["id"],
            "REFERRAL_SLA_BREACHED",
            f"Referral {ref['id']} SLA breached at {ref['sla_due_at']}",
        )
        touch_case_once(case)


# ---------------------------------------------------------------------------
# Records retention purge (PRD section 3.8)
# ---------------------------------------------------------------------------

def run_retention_purge() -> tuple[int, list[str]]:
    today = db.clock().date()
    eligible = []
    for case in sort_by_created_at(list(db.threat_cases.values())):
        if case["status"] not in ("CLOSED_NO_THREAT", "CLOSED_MANAGED"):
            continue
        if case.get("purged_at") is not None:
            continue
        purge_after = case.get("retention_purge_after")
        if purge_after is None:
            continue
        if date.fromisoformat(purge_after) <= today:  # >= semantics: equal date purges
            eligible.append(case)

    purged_ids: list[str] = []
    for case in eligible:
        case["status"] = "PURGED"
        case["purged_at"] = db.now_logical_iso()
        case["subject_alias"] = "PURGED"
        db.touch(case)
        for doc in case_children(db.documents, case["id"]):
            doc["body"] = None
            doc["purged"] = True
        audit_system(case["id"], "CASE_PURGED", "Case purged by records retention")
        purged_ids.append(case["id"])
    return len(purged_ids), purged_ids


# ---------------------------------------------------------------------------
# District annual report (PRD section 3.8)
# ---------------------------------------------------------------------------

def build_district_annual_report(school_year: str) -> dict:
    import re

    match = re.fullmatch(r"(\d{4})-(\d{4})", school_year or "")
    if not match:
        raise_err(ERR_INVALID_REQUEST, "school_year must be in YYYY-YYYY form")
    year_a = int(match.group(1))
    year_b = int(match.group(2))
    if year_b != year_a + 1:
        raise_err(ERR_INVALID_REQUEST, "school_year second year must be exactly one greater")

    window_start = datetime(year_a, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    window_end = datetime(year_a + 1, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    cases_in_window = [
        c for c in db.threat_cases.values()
        if window_start <= db.parse_iso(c["created_at"]) < window_end
    ]

    per_school: list[dict] = []
    rounded_rates: list[Decimal] = []
    total_cases = 0
    substantiated_cases = 0

    for school in sort_by_created_at(list(db.schools.values())):
        school_cases = [c for c in cases_in_window if c["school_id"] == school["id"]]
        if not school_cases:
            continue  # zero-case schools excluded from per_school and the mean
        school_total = len(school_cases)
        school_substantiated = sum(
            1 for c in school_cases if c.get("screening_outcome") == "SUBSTANTIVE"
        )
        # Pinned rounding order: per-school rate rounded to 2dp FIRST.
        rate = round_half_up_2dp(
            Decimal(100 * school_substantiated) / Decimal(school_total)
        )
        per_school.append({
            "school_id": school["id"],
            "school_code": school["school_code"],
            "total_cases": school_total,
            "substantiated_cases": school_substantiated,
            "substantiation_rate": float(rate),
            "school_total": school_total,
            "school_substantiated": school_substantiated,
            "school_rate": float(rate),
        })
        rounded_rates.append(rate)
        total_cases += school_total
        substantiated_cases += school_substantiated

    if rounded_rates:
        district_rate = round_half_up_2dp(
            sum(rounded_rates, Decimal("0")) / Decimal(len(rounded_rates))
        )
    else:
        district_rate = Decimal("0.00")

    return {
        "school_year": school_year,
        "total_cases": total_cases,
        "substantiated_cases": substantiated_cases,
        "per_school": per_school,
        "district_substantiation_rate": float(district_rate),
    }
