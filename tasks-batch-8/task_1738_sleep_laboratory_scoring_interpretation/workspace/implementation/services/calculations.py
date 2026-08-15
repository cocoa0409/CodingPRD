"""Business calculations (scaffold Table 3 / PRD 2.6 and section 3)."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from db import db
from util import parse_date, parse_dt, ratio_round_half_up, round_half_up, round_to_half_step, num, to_decimal

IN_LAB_TYPES = {"PSG_DIAGNOSTIC", "SPLIT_NIGHT", "TITRATION_PAP"}

# Study statuses that consume an authorized night (auth_nights_consumption)
NIGHT_CONSUMING_STATUSES = {
    "SCHEDULED", "IN_PROGRESS", "SCORING_QUEUED", "SCORING_IN_PROGRESS",
    "SCORED", "INTERPRETATION_IN_PROGRESS", "INTERPRETED", "REPORT_FINALIZED",
}

# Scoring-task terminal states
TASK_TERMINAL = {"ACCEPTED", "RECALLED"}

# DME terminal states
DME_TERMINAL = {"FOLLOW_UP_PASSED", "FOLLOW_UP_RESOLVED", "DECLINED", "CANCELLED"}


# ---------------------------------------------------------------------------
# ahi_rdi_rei_computation
# ---------------------------------------------------------------------------

def compute_indexes(study_type, obstructive, central, mixed, hypopneas, reras,
                    tst_minutes, trt_minutes):
    """Return (ahi, rdi, rei) as floats (1 decimal, round-half-up) or None."""
    events = obstructive + central + mixed + hypopneas
    if study_type == "HST":
        rei = num(ratio_round_half_up(events * 60, trt_minutes, 1))
        return None, None, rei
    ahi = num(ratio_round_half_up(events * 60, tst_minutes, 1))
    rdi = num(ratio_round_half_up((events + reras) * 60, tst_minutes, 1))
    return ahi, rdi, None


# ---------------------------------------------------------------------------
# severity_classification
# ---------------------------------------------------------------------------

def classify_severity(idx: float) -> str:
    idx = to_decimal(idx)
    if idx < Decimal("5.0"):
        return "NORMAL"
    if idx < Decimal("15.0"):
        return "MILD"
    if idx < Decimal("30.0"):
        return "MODERATE"
    return "SEVERE"


# ---------------------------------------------------------------------------
# interpretation_turnaround (business window Mon-Fri 08:00-17:00 UTC)
# ---------------------------------------------------------------------------

BUSINESS_START = time(8, 0, 0)
BUSINESS_END = time(17, 0, 0)


def _business_minutes(start: datetime, end: datetime) -> int:
    if end <= start:
        return 0
    total_seconds = 0.0
    day = start.date()
    last = end.date()
    while day <= last:
        if day.weekday() < 5:  # Monday..Friday only; weekends contribute zero
            win_start = datetime.combine(day, BUSINESS_START, tzinfo=timezone.utc)
            win_end = datetime.combine(day, BUSINESS_END, tzinfo=timezone.utc)
            lo = max(start, win_start)
            hi = min(end, win_end)
            if hi > lo:
                total_seconds += (hi - lo).total_seconds()
        day += timedelta(days=1)
    return int(total_seconds // 60)


def compute_turnaround(start_iso: str, end_iso: str, priority: str):
    """Return (business_hours, calendar_hours, sla_breached) — 1-decimal half-up hours."""
    start = parse_dt(start_iso)
    end = parse_dt(end_iso)
    cal_seconds = max(0.0, (end - start).total_seconds())
    cal_minutes = int(cal_seconds // 60)
    bus_minutes = _business_minutes(start, end)
    cal_hours = num(ratio_round_half_up(cal_minutes, 60, 1))
    bus_hours = num(ratio_round_half_up(bus_minutes, 60, 1))
    if priority == "STAT":
        breached = to_decimal(cal_hours) > Decimal("24.0")
    else:
        breached = to_decimal(bus_hours) > Decimal("48.0")
    return bus_hours, cal_hours, bool(breached)


# ---------------------------------------------------------------------------
# titration_pressure_recommendation (pinned order: raw -> band(raw) -> adjust
# -> sum -> clamp -> round; band is never recomputed after adjustment)
# ---------------------------------------------------------------------------

def titration_recommendation(raw_pressure, residual_ahi, leak_95th):
    raw = to_decimal(raw_pressure)
    ahi = to_decimal(residual_ahi)
    leak = to_decimal(leak_95th)
    if ahi >= Decimal("10.0"):
        ahi_adj = Decimal("1.0")
    elif ahi >= Decimal("5.0"):
        ahi_adj = Decimal("0.5")
    else:
        ahi_adj = Decimal("0.0")
    low_band = raw <= Decimal("10.0")  # band computed from RAW only
    if low_band and leak > Decimal("24.0"):
        leak_adj = Decimal("0.5")
    elif (not low_band) and leak > Decimal("36.0"):
        leak_adj = Decimal("1.0")
    else:
        leak_adj = Decimal("0.0")
    summed = raw + ahi_adj + leak_adj
    clamped = max(Decimal("4.0"), min(Decimal("20.0"), summed))
    return num(round_to_half_step(clamped))


# ---------------------------------------------------------------------------
# night_staffing_capacity
# ---------------------------------------------------------------------------

def confirmed_capacity(shift_date: str) -> int:
    return sum(
        a["patient_capacity"]
        for a in db["staffing_assignments"].values()
        if a["shift_date"] == shift_date and a["status"] == "CONFIRMED"
    )


def occupied_inlab(shift_date: str) -> int:
    return sum(
        1
        for s in db["sleep_studies"].values()
        if s["scheduled_date"] == shift_date
        and s.get("bed_id") is not None
        and s["status"] in ("SCHEDULED", "IN_PROGRESS")
    )


# ---------------------------------------------------------------------------
# auth_nights_consumption
# ---------------------------------------------------------------------------

def consumed_nights(order_id: str) -> int:
    return sum(
        1
        for s in db["sleep_studies"].values()
        if s["order_id"] == order_id and s["status"] in NIGHT_CONSUMING_STATUSES
    )


def live_approved_auth(order_id: str):
    for a in db["authorizations"].values():
        if a["order_id"] == order_id and a["status"] == "APPROVED":
            return a
    return None


# ---------------------------------------------------------------------------
# dme_adherence_compliance (boundaries inclusive)
# ---------------------------------------------------------------------------

def adherence_compliant(usage_hours_avg, compliant_nights_percent) -> bool:
    return (to_decimal(usage_hours_avg) >= Decimal("4.0")
            and to_decimal(compliant_nights_percent) >= Decimal("70.0"))


# ---------------------------------------------------------------------------
# inter_rater_agreement
# ---------------------------------------------------------------------------

def task_index(task, study_type):
    """AHI for in-lab types, REI for HST."""
    return task["rei"] if study_type == "HST" else task["ahi"]


def adjudication_metrics(study_type, primary_task, rescore_task, epochs_concordant):
    idx_primary = task_index(primary_task, study_type)
    idx_rescore = task_index(rescore_task, study_type)
    delta = round_half_up(abs(to_decimal(idx_primary) - to_decimal(idx_rescore)), 2)
    pct = ratio_round_half_up(epochs_concordant * 100, rescore_task["epochs_total"], 2)
    concordant = delta <= Decimal("2.0") and pct >= Decimal("85.0")
    return num(idx_primary), num(idx_rescore), num(delta), num(pct), bool(concordant)


def rescorer_adjudicated_cases(scorer_id: str):
    """This scorer's ADJUDICATED cases as rescorer, ordered adjudicated_at ASC,
    tie-break created_at ASC (insertion seq breaks any residual ties)."""
    cases = []
    for case in db["inter_rater_cases"].values():
        if case["status"] != "ADJUDICATED":
            continue
        rescore_task = db["scoring_tasks"].get(case["rescore_task_id"])
        if rescore_task is None or rescore_task["scorer_id"] != scorer_id:
            continue
        cases.append(case)
    cases.sort(key=lambda c: (c["adjudicated_at"], c["created_at"], c["_seq"]))
    return cases


def recompute_scorer_reliability(scorer):
    """Rolling index + status recompute after an adjudication (pinned rounding:
    the mean averages the per-case percent_agreement values exactly as stored,
    each already rounded to 2 decimals, then rounds half-up to 2 decimals)."""
    cases = rescorer_adjudicated_cases(scorer["id"])
    window = cases[-5:]
    if len(cases) >= 3:
        with_sum = sum(to_decimal(c["percent_agreement"]) for c in window)
        rolling = round_half_up(with_sum / Decimal(len(window)), 2)
        scorer["rolling_agreement_index"] = num(rolling)
    else:
        rolling = None
        scorer["rolling_agreement_index"] = None

    consecutive = scorer["consecutive_nonconcordant"]
    n = len(cases)
    if consecutive >= 2 or (n >= 3 and rolling is not None and rolling < Decimal("80.0")):
        scorer["reliability_status"] = "REMEDIATION"
    elif n >= 3 and rolling is not None and rolling >= Decimal("90.0") and consecutive < 2:
        scorer["reliability_status"] = "CONSISTENT"
    elif n >= 3 and rolling is not None and Decimal("80.0") <= rolling < Decimal("90.0") and consecutive < 2:
        scorer["reliability_status"] = "WATCH"
    else:
        scorer["reliability_status"] = "PROVISIONAL"
