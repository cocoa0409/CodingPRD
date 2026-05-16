"""Pure-function computations: LRE, triennial status, transition age, mastery, comp minutes."""

from decimal import Decimal

from core.clock import days_between, add_years_same_md, date_at_or_after, parse_dt
from core.precision import round_half_up
from core.store import SERVICES, SESSIONS, IEPS


# ---------- Triennial ----------

def compute_triennial_status(student: dict, district_current_date: str) -> str:
    due = student.get("triennial_reevaluation_due_date")
    if due is None:
        return "NOT_APPLICABLE"
    days = days_between(due, district_current_date)
    if days > 90:
        return "ON_TRACK"
    if days >= 0:
        return "DUE_SOON"
    return "OVERDUE"


def compute_triennial_due_date(finalized_at: str) -> str:
    return add_years_same_md(finalized_at, 3)


# ---------- Transition plan eligibility ----------

def compute_requires_transition_plan(student: dict, district_current_date: str) -> bool:
    dob = student.get("date_of_birth")
    if not dob:
        return False
    if not student.get("current_iep_id"):
        return False
    age_threshold = add_years_same_md(dob, 16)
    return date_at_or_after(district_current_date, age_threshold)


# ---------- LRE ----------

def _sped_pullout_minutes(iep_id: str) -> int:
    """Sum minutes_per_week across ACTIVE services on IEP whose location_setting is PULL_OUT or COMMUNITY."""
    total = 0
    for s in SERVICES.values():
        if s.get("iep_id") != iep_id:
            continue
        if s.get("status") != "ACTIVE":
            continue
        if s.get("location_setting") in ("PULL_OUT", "COMMUNITY"):
            total += s.get("minutes_per_week", 0)
    return total


def sped_pullout_minutes_for_iep(iep_id: str) -> int:
    """Public alias: pull-out-minutes numerator for the LRE summary
    (PRD §3.8 — `total_sped_minutes` is the pull-out numerator)."""
    return _sped_pullout_minutes(iep_id)


def _sped_total_minutes(iep_id: str) -> int:
    """Sum minutes_per_week across ALL ACTIVE services on IEP (used for instructional-cap check)."""
    total = 0
    for s in SERVICES.values():
        if s.get("iep_id") != iep_id:
            continue
        if s.get("status") != "ACTIVE":
            continue
        total += s.get("minutes_per_week", 0)
    return total


def recompute_iep_lre(iep: dict) -> None:
    """Recompute special_education_minutes_per_week + lre_percentage_instructional + lre_percentage_school_day on the IEP dict in place.

    NOTE: This is the side-effect helper — it mutates the dict. The caller is
    responsible for stamping `updated_at`/`version` if it deems this a logical update.
    """
    pullout = _sped_pullout_minutes(iep["id"])
    sped_total = _sped_total_minutes(iep["id"])
    iep["special_education_minutes_per_week"] = sped_total

    instr_denom = iep.get("total_instructional_minutes_per_week", 0)
    school_denom = iep.get("total_school_day_minutes_per_week", 0)

    if instr_denom and instr_denom > 0:
        iep["lre_percentage_instructional"] = round_half_up(
            Decimal(100) * Decimal(pullout) / Decimal(instr_denom), 2
        )
    else:
        iep["lre_percentage_instructional"] = 0.00

    if school_denom and school_denom > 0:
        iep["lre_percentage_school_day"] = round_half_up(
            Decimal(100) * Decimal(pullout) / Decimal(school_denom), 2
        )
    else:
        iep["lre_percentage_school_day"] = 0.00


def classify_lre_from_instructional(pct: float) -> str:
    """Return LRE bucket from the instructional-basis percentage."""
    if pct <= 20.00:
        return "LRE_A"
    if pct <= 60.00:
        return "LRE_B"
    return "LRE_C"


def recompute_student_lre_classification(student: dict) -> None:
    """Set Student.lre_classification from the current IEP's lre_percentage_instructional.

    NOT_APPLICABLE if no current IEP.
    """
    iep_id = student.get("current_iep_id")
    if not iep_id:
        student["lre_classification"] = "NOT_APPLICABLE"
        return
    iep = IEPS.get(iep_id)
    if iep is None:
        student["lre_classification"] = "NOT_APPLICABLE"
        return
    student["lre_classification"] = classify_lre_from_instructional(
        iep.get("lre_percentage_instructional", 0.0)
    )


# ---------- Goal mastery ----------

def recompute_goal_mastery(goal: dict) -> None:
    """Update goal.mastery_score (Decimal weighted sum) and goal.mastery_tier."""
    total = Decimal(0)
    for obj in goal.get("objectives", []):
        w = Decimal(str(obj.get("weight", 0)))
        p = Decimal(str(obj.get("latest_progress_percent", 0)))
        total += w * p
    score = round_half_up(total, 2)
    goal["mastery_score"] = score
    if score >= 80.00:
        goal["mastery_tier"] = "MASTERED"
    elif score >= 50.00:
        goal["mastery_tier"] = "PROGRESSING"
    else:
        goal["mastery_tier"] = "INSUFFICIENT_PROGRESS"


# ---------- Compensatory minutes ----------

MAKEUP_MULTIPLIER = Decimal("1.5")


def compute_compensatory_minutes(service: dict, district_current_date: str) -> int:
    """Sum of round_half_up(scheduled_minutes * 1.5, 0) for SCHEDULED sessions on this
    service whose scheduled_start <= district.current_date (at the moment of suspension).
    """
    current_dt = parse_dt(district_current_date)
    per_session = []
    for ses in SESSIONS.values():
        if ses.get("related_service_id") != service["id"]:
            continue
        if ses.get("status") != "SCHEDULED":
            continue
        try:
            start_dt = parse_dt(ses["scheduled_start"])
        except Exception:
            continue
        if start_dt <= current_dt:
            raw = Decimal(ses.get("scheduled_minutes", 0)) * MAKEUP_MULTIPLIER
            per_session.append(round_half_up(raw, 0))
    return sum(per_session)


# ---------- Service utilization ----------

def recompute_service_utilization(service: dict, district_current_date: str) -> None:
    """Recompute total_prescribed_minutes_to_date and utilization_percent for the service."""
    first_active = service.get("first_active_at")
    if not first_active:
        service["total_prescribed_minutes_to_date"] = 0
        service["utilization_percent"] = 0.00
        return

    # Reference time: suspended_at if available, otherwise current_date.
    end_ref = service.get("suspended_at") or district_current_date
    end_dt = parse_dt(end_ref)
    start_dt = parse_dt(first_active)
    delta_seconds = (end_dt - start_dt).total_seconds()
    weeks_active = int(delta_seconds // (7 * 86400))
    if weeks_active < 0:
        weeks_active = 0
    mpw = service.get("minutes_per_week", 0)
    prescribed = weeks_active * mpw
    service["total_prescribed_minutes_to_date"] = prescribed
    delivered = service.get("total_delivered_minutes", 0)
    if prescribed == 0:
        service["utilization_percent"] = 0.00
    else:
        service["utilization_percent"] = round_half_up(
            Decimal(100) * Decimal(delivered) / Decimal(prescribed), 2
        )
