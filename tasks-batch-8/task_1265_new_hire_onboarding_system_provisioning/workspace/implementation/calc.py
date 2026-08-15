"""Calculation rules (SCAFFOLD §1.3 / PRD §2.9-2.10, §3).

Every formula here mirrors the scaffold exactly: constants, rounding order,
boundary inclusivity, and dual variants.
"""

from datetime import datetime, time as dtime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store, clock

# ---- case_health_score constants ----
OVERDUE_TRAINING_PENALTY = 15
MISSED_CHECKIN_PENALTY = 10
PROBATION_OVERDUE_PENALTY = 25
PROBATION_OVERDUE_GRACE_DAYS = 7
PROVISIONING_ATTENTION_PENALTY = 20
NO_SHOW_PENALTY = 30
AT_RISK_THRESHOLD = 70
SCORE_FLOOR = 0

# ---- time_to_productivity constants ----
OVERDUE_TRAINING_SLIP_DAYS = 3
MISSED_CHECKIN_SLIP_DAYS = 5

# ---- survey weights ----
W_EXPERIENCE = Decimal("0.4")
W_MANAGER = Decimal("0.3")
W_RESOURCES = Decimal("0.3")


def case_health_score(case):
    """100 - penalties, floored at 0. CANCELLED children never count."""
    cid = case["id"]
    now = clock.current
    ot = sum(1 for t in store["trainings"].values()
             if t["case_id"] == cid and t["status"] == "OVERDUE")
    mc = sum(1 for c in store["checkins"].values()
             if c["case_id"] == cid and c["status"] == "MISSED")
    peo = 0
    for cy in store["cycles"].values():
        if cy["case_id"] == cid and cy["status"] == "EVALUATION_DUE" and \
                now > cy["_eval_due_dt"] + timedelta(days=PROBATION_OVERDUE_GRACE_DAYS):
            peo = 1
            break
    par = 0
    for o in store["orders"].values():
        if o["case_id"] == cid and o["status"] == "ATTENTION_REQUIRED":
            par = 1
            break
    ns = 1 if case.get("orientation_rsvp") == "NO_SHOW" else 0
    score = (100
             - OVERDUE_TRAINING_PENALTY * ot
             - MISSED_CHECKIN_PENALTY * mc
             - PROBATION_OVERDUE_PENALTY * peo
             - PROVISIONING_ATTENTION_PENALTY * par
             - NO_SHOW_PENALTY * ns)
    return max(SCORE_FLOOR, score)


def health_label(score):
    return "AT_RISK" if score < AT_RISK_THRESHOLD else "ON_TRACK"


def estimated_ttp_days(case):
    """Forward-looking variant: profile base + slip penalties."""
    prof = case["_profile"]
    train_offsets = [m["due_offset_days"] for m in prof["training_modules"]]
    mgr_offsets = list(prof["manager_checkin_offsets_days"])
    base_days = max(max(train_offsets) if train_offsets else 0,
                    max(mgr_offsets) if mgr_offsets else 0)
    cid = case["id"]
    ot = sum(1 for t in store["trainings"].values()
             if t["case_id"] == cid and t["status"] == "OVERDUE")
    mc = sum(1 for c in store["checkins"].values()
             if c["case_id"] == cid and c["status"] == "MISSED")
    return (base_days
            + OVERDUE_TRAINING_SLIP_DAYS * ot
            + MISSED_CHECKIN_SLIP_DAYS * mc)


def actual_ttp_days(case):
    """Chronological variant: null until every training and every MANAGER
    check-in is COMPLETED; then calendar-day difference start_date -> date of
    the latest completion."""
    cid = case["id"]
    trainings = [t for t in store["trainings"].values() if t["case_id"] == cid]
    managers = [c for c in store["checkins"].values()
                if c["case_id"] == cid and c["kind"] == "MANAGER"]
    if not all(t["status"] == "COMPLETED" for t in trainings):
        return None
    if not all(c["status"] == "COMPLETED" for c in managers):
        return None
    stamps = [t["_completed_dt"] for t in trainings] + \
             [c["_completed_dt"] for c in managers]
    stamps = [s for s in stamps if s is not None]
    if not stamps:
        return 0
    last = max(stamps).date()
    return (last - case["_start_d"]).days


def _round1(x):
    return float(Decimal(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def business_seconds(start, end):
    """Seconds of [start, end) whose UTC weekday is Monday-Friday."""
    if end <= start:
        return 0
    total = 0
    t = start
    while t < end:
        nxt_hour = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        nxt = min(end, nxt_hour)
        if t.weekday() < 5:  # Mon-Fri; weekday changes only at hour-aligned midnight
            total += (nxt - t).total_seconds()
        t = nxt
    return total


def sla_fields(order):
    """Elapsed calendar/business hours (1 dp, half-up) + strict breach flags.
    The interval is [submitted_at, min(now, fulfilled_at)]; 0 before submit.
    Breach comparisons are exact (strictly greater; equality is not a breach)."""
    sla = order["sla_hours"]
    submitted = order["_submitted_dt"]
    if submitted is None:
        return {
            "elapsed_calendar_hours": 0.0,
            "elapsed_business_hours": 0.0,
            "sla_breached_calendar": False,
            "sla_breached_business": False,
        }
    end = clock.current
    if order["_fulfilled_dt"] is not None and order["_fulfilled_dt"] < end:
        end = order["_fulfilled_dt"]
    cal_secs = max(0, (end - submitted).total_seconds())
    biz_secs = business_seconds(submitted, end)
    cal_hours = Decimal(cal_secs) / Decimal(3600)
    biz_hours = Decimal(biz_secs) / Decimal(3600)
    return {
        "elapsed_calendar_hours": _round1(cal_hours),
        "elapsed_business_hours": _round1(biz_hours),
        "sla_breached_calendar": cal_hours > sla,
        "sla_breached_business": biz_hours > sla,
    }


def _rhu_cents(x):
    """Round half-up to whole cents (integer)."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def first_period_gross_cents(case, fp_start, fp_end):
    """Per-component round-then-sum proration (sum-then-round is forbidden)."""
    days_in_period = (fp_end - fp_start).days + 1
    employed_start = max(case["_start_d"], fp_start)
    days_employed = max(0, (fp_end - employed_start).days + 1)
    ratio = Decimal(days_employed) / Decimal(days_in_period)
    comp_base = _rhu_cents(Decimal(case["base_salary_cents"]) * ratio)
    comp_bonus = _rhu_cents(Decimal(case["signing_bonus_cents"]) * ratio)
    comp_reloc = _rhu_cents(Decimal(case["relocation_stipend_cents"]) * ratio)
    return comp_base + comp_bonus + comp_reloc


def survey_overall_score(experience, manager, resources):
    val = (W_EXPERIENCE * experience
           + W_MANAGER * manager
           + W_RESOURCES * resources)
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def shift_off_weekend(d):
    """Shift a date forward past Saturday/Sunday to Monday."""
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d = d + timedelta(days=1)
    return d


def checkin_cadence(case):
    """Return the cadence plan as a list of dicts:
    {kind, owner_employee_id, _sched_dt} in generation order —
    MANAGER entries first (offset ASC), then BUDDY (date ASC)."""
    prof = case["_profile"]
    start = case["_start_d"]
    plan = []
    for m in sorted(prof["manager_checkin_offsets_days"]):
        d = shift_off_weekend(start + timedelta(days=m))
        plan.append({
            "kind": "MANAGER",
            "owner_employee_id": case["manager_id"],
            "_sched_dt": datetime.combine(d, dtime(9, 0, 0),
                                          tzinfo=timezone.utc),
        })
    interval = prof["buddy_checkin_interval_days"]
    for k in range(prof["buddy_checkin_count"]):
        d = shift_off_weekend(start + timedelta(days=1 + k * interval))
        plan.append({
            "kind": "BUDDY",
            "owner_employee_id": case["buddy_id"],
            "_sched_dt": datetime.combine(d, dtime(9, 0, 0),
                                          tzinfo=timezone.utc),
        })
    return plan
