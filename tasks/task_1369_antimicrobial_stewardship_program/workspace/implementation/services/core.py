"""Core domain services: clock, sweeps, computed fields, cascades."""

from datetime import timedelta
from decimal import Decimal

import db
from util import (
    INITIAL_CLOCK_ISO,
    clock_has_ms,
    format_clock,
    full_years_between,
    now_iso,
    parse_iso,
    round2,
)

# --- Constants pinned by SCAFFOLD calculations table / PRD section 3 ---------

CLASS_BREADTH_RANK = {
    "CARBAPENEM": 90,
    "GLYCOPEPTIDE": 70,
    "FLUOROQUINOLONE": 60,
    "EXTENDED_SPECTRUM_PENICILLIN": 50,
    "AMINOGLYCOSIDE": 45,
    "CEPHALOSPORIN": 40,
    "MACROLIDE": 30,
    "NARROW_PENICILLIN": 20,
}
UNKNOWN_CLASS_RANK = 999

SPECIMEN_EXCLUSIONS = {"CSF": {"MACROLIDE"}}

ANAPHYLAXIS_KEYWORDS = ("anaphylaxis", "angioedema", "hives", "wheeze")
LOW_RISK_THRESHOLD = Decimal("30")

CONVERSION_MIN_SCORE = Decimal("60")
DEESCALATION_MIN_SCORE = 65
ADOPTION_MIN_PCT = Decimal("70")
STALENESS_DROP_POINTS = Decimal("10")

ALLERGY_BLOCKING_STATUSES = {"SUSPECTED", "TESTING_SCHEDULED", "TESTED", "CONFIRMED"}
ALLERGY_TERMINAL_STATUSES = {"DELABELED", "WITHDRAWN"}

BENCHMARK_FLOORS = ((780, 90), (620, 75), (480, 50), (350, 25), (0, 10))


# --- Clock -------------------------------------------------------------------

def hospital_clock(hospital):
    """Logical clock as an aware datetime."""
    return parse_iso(hospital["current_utc"], "current_utc")


def set_hospital_clock(hospital, dt):
    hospital["current_utc"] = format_clock(dt, hospital.get("_clock_ms", False))


def init_hospital_clock(hospital):
    hospital["current_utc"] = INITIAL_CLOCK_ISO
    hospital["_clock_ms"] = clock_has_ms(INITIAL_CLOCK_ISO)


def clock_iso(hospital):
    return hospital["current_utc"]


def clock_plus(hospital, **delta_kwargs):
    """Hospital clock plus a timedelta, serialized in the clock's style."""
    dt = hospital_clock(hospital) + timedelta(**delta_kwargs)
    return format_clock(dt, hospital.get("_clock_ms", False))


# --- Mutation bookkeeping -----------------------------------------------------

def touch(resource):
    resource["updated_at"] = now_iso()
    resource["version"] = int(resource.get("version", 1)) + 1


def stamp_new(resource):
    ts = now_iso()
    resource["created_at"] = ts
    resource["updated_at"] = ts
    resource["version"] = 1


# --- Order DOT counters --------------------------------------------------------

def recompute_order_dot(order):
    """dot_calendar / dot_dose from the recorded administration events.

    dot_calendar: distinct UTC calendar dates with >= 1 administration between
    started_at and min(stopped_at, hospital clock) — while the order is open,
    all recorded events qualify (they are recorded against running therapy).
    dot_dose: administered_doses / frequency_per_day, 2dp half-up.
    """
    events = db.administration_events.get(order["id"], [])
    dates = {ev.date() for ev in events}
    order["dot_calendar"] = len(dates)
    order["administered_doses"] = len(events)
    freq = order["frequency_per_day"]
    order["dot_dose"] = round2(Decimal(len(events)) / Decimal(freq))


def order_dot_slice_in_month(order, label):
    """(calendar_dot, dose_dot) attributable to the given YYYY-MM month."""
    month_start, month_end = None, None
    from util import month_bounds

    month_start, month_end = month_bounds(label)
    events = db.administration_events.get(order["id"], [])
    started = parse_iso(order["started_at"]) if order.get("started_at") else None
    stopped = parse_iso(order["stopped_at"]) if order.get("stopped_at") else None
    cal_dates = set()
    dose_count = 0
    for ev in events:
        if started is not None and ev < started:
            continue
        if stopped is not None and ev > stopped:
            continue
        if not (month_start <= ev < month_end):
            continue
        cal_dates.add(ev.date())
        dose_count += 1
    dose_dot = round2(Decimal(dose_count) / Decimal(order["frequency_per_day"]))
    return len(cal_dates), dose_dot


def order_intersects_month(order, label):
    """Whether the therapy window intersects the snapshot month."""
    from util import month_bounds

    if order.get("started_at") is None:
        return False
    month_start, month_end = month_bounds(label)
    started = parse_iso(order["started_at"])
    if order.get("stopped_at"):
        end = parse_iso(order["stopped_at"])
    else:
        hospital = db.hospitals.get(order["_hospital_id"])
        end = hospital_clock(hospital) if hospital else None
    if end is None:
        return False
    return started < month_end and end >= month_start


# --- Practitioner standing -----------------------------------------------------

def recompute_standing(practitioner):
    count = practitioner.get("unresolved_noncompliance_count", 0)
    if count >= 3:
        practitioner["stewardship_standing"] = "SUSPENDED"
    elif count == 2:
        practitioner["stewardship_standing"] = "WATCH"
    else:
        practitioner["stewardship_standing"] = "GOOD"


# --- Allergy risk score ---------------------------------------------------------

def compute_allergy_risk(assessment, patient, effective_years=None):
    """penicillin_allergy_risk_score (PRD 3.6). Returns (risk_score Decimal, eligible bool)."""
    severity = assessment["reaction_severity"]
    base = {"MILD": 10, "MODERATE": 35, "SEVERE": 80}[severity]
    reaction_text = (assessment.get("reported_reaction") or "").lower()
    reaction_term = 20 if any(kw in reaction_text for kw in ANAPHYLAXIS_KEYWORDS) else 0
    years = assessment["years_since_reaction"] if effective_years is None else effective_years
    recency_term = max(0, 30 - 3 * years)
    comorbidity_term = 10 if patient.get("is_immunocompromised") else 0
    raw = Decimal(base + reaction_term + recency_term + comorbidity_term)
    score = round2(min(raw, Decimal(100)))
    eligible = (score < LOW_RISK_THRESHOLD) and severity != "SEVERE"
    return score, eligible


def recompute_assessment_verified_baseline(assessment, patient, hospital):
    """verified_baseline variant: recency uses stored years plus full elapsed
    years between assessment created_at and the logical clock at schedule time."""
    created = parse_iso(assessment["created_at"])
    clock = hospital_clock(hospital)
    elapsed = full_years_between(created, clock)
    effective_years = assessment["years_since_reaction"] + elapsed
    score, eligible = compute_allergy_risk(assessment, patient, effective_years=effective_years)
    assessment["risk_score"] = score
    assessment["delabel_eligible"] = eligible


# --- Cascades -------------------------------------------------------------------

def cascade_order_closed(order, hospital, stopped=True):
    """Cleanup when an AWAITING_APPROVAL order is denied/expired/withdrawn or
    an order is discontinued: open interventions -> SUPERSEDED, open
    opportunities -> EXPIRED."""
    if stopped and order.get("stopped_at") is None:
        order["stopped_at"] = clock_iso(hospital)
    for itv in db.audit_interventions.values():
        if itv["antibiotic_order_id"] == order["id"] and itv["recommendation_status"] in (
            "DOCUMENTED",
            "RECOMMENDED",
        ):
            itv["recommendation_status"] = "SUPERSEDED"
            touch(itv)
    for opp in db.conversion_opportunities.values():
        if opp["antibiotic_order_id"] == order["id"] and opp["status"] == "DETECTED":
            opp["status"] = "EXPIRED"
            touch(opp)


def maybe_flag_review_required(order, hospital):
    """ACTIVE -> REVIEW_REQUIRED when dot_calendar reaches the threshold."""
    if order["therapy_status"] != "ACTIVE":
        return
    if order["approval_status"] not in ("APPROVED", "NOT_REQUIRED"):
        return
    if order["dot_calendar"] >= hospital["dot_review_threshold"]:
        order["therapy_status"] = "REVIEW_REQUIRED"
        touch(order)


# --- Clock sweeps (PRD 2.4) ------------------------------------------------------

def run_clock_sweeps(hospital):
    """Fire the four scheduled sweeps for this hospital, in PRD order."""
    clock = hospital_clock(hospital)
    hospital_id = hospital["id"]

    # 1. SUBMITTED approval requests past the auto-expire window -> EXPIRED.
    expire_after = timedelta(hours=hospital["restricted_auto_expire_hours"])
    for req in list(db.approval_requests.values()):
        if req["status"] != "SUBMITTED":
            continue
        order = db.antibiotic_orders.get(req["antibiotic_order_id"])
        if order is None or order.get("_hospital_id") != hospital_id:
            continue
        submitted = parse_iso(req["submitted_at"])
        if clock >= submitted + expire_after:
            req["status"] = "EXPIRED"
            touch(req)
            order["approval_status"] = "EXPIRED"
            if order["therapy_status"] == "AWAITING_APPROVAL":
                order["therapy_status"] = "DISCONTINUED"
                order["stopped_at"] = clock_iso(hospital)
                cascade_order_closed(order, hospital, stopped=False)
            touch(order)

    # 2. RECOMMENDED interventions past due_at -> SUPERSEDED.
    for itv in list(db.audit_interventions.values()):
        if itv["recommendation_status"] != "RECOMMENDED":
            continue
        order = db.antibiotic_orders.get(itv["antibiotic_order_id"])
        if order is None or order.get("_hospital_id") != hospital_id:
            continue
        if itv.get("due_at") and clock > parse_iso(itv["due_at"]):
            itv["recommendation_status"] = "SUPERSEDED"
            touch(itv)

    # 3. DETECTED opportunities older than 48h -> EXPIRED.
    for opp in list(db.conversion_opportunities.values()):
        if opp["status"] != "DETECTED":
            continue
        order = db.antibiotic_orders.get(opp["antibiotic_order_id"])
        if order is None or order.get("_hospital_id") != hospital_id:
            continue
        detected = parse_iso(opp["detected_at"])
        if clock > detected + timedelta(hours=48):
            opp["status"] = "EXPIRED"
            touch(opp)

    # 4. ACTIVE orders at/over the DOT review threshold -> REVIEW_REQUIRED.
    for order in list(db.antibiotic_orders.values()):
        if order.get("_hospital_id") != hospital_id:
            continue
        maybe_flag_review_required(order, hospital)


# --- Guideline staleness -----------------------------------------------------------

def guideline_row_for(antibiogram_id, antimicrobial_id, syndrome=None):
    """Locate the AntibiogramRow summarizing a drug for a guideline's syndrome
    organism. Prefers an organism matching the syndrome string; otherwise the
    single matching row; otherwise the lowest-pct row (most conservative)."""
    rows = [
        r
        for r in db.antibiogram_rows.values()
        if r["antibiogram_id"] == antibiogram_id and r["antimicrobial_id"] == antimicrobial_id
    ]
    if not rows:
        return None
    if syndrome is not None:
        exact = [r for r in rows if r["organism"] == syndrome]
        if exact:
            return exact[0]
    if len(rows) == 1:
        return rows[0]
    return min(rows, key=lambda r: (r["pct_susceptible"], r["created_at"]))


def reevaluate_guideline_staleness(hospital, antibiogram):
    """On publish: ADOPTED guidelines whose first-line drug pct dropped by
    >= STALENESS_DROP_POINTS below the adoption snapshot become STALE."""
    for gl in list(db.empiric_guidelines.values()):
        if gl["hospital_id"] != hospital["id"] or gl["status"] != "ADOPTED":
            continue
        row = guideline_row_for(antibiogram["id"], gl["first_line_antimicrobial_id"], gl["syndrome"])
        if row is None or not row["is_reportable"]:
            continue
        adoption_pct = gl.get("pct_susceptible_at_adoption")
        if adoption_pct is None:
            continue
        if Decimal(str(row["pct_susceptible"])) <= Decimal(str(adoption_pct)) - STALENESS_DROP_POINTS:
            gl["status"] = "STALE"
            touch(gl)
