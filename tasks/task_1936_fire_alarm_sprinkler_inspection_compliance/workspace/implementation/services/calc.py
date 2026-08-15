"""Calculation rules (SCAFFOLD §1.3) and derived-state helpers.

Every formula here traces literally to the scaffold/PRD: precision, rounding
points, window boundaries, and variant selection are pinned by the spec.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from services.core import set_fields, touch

# ---- code tables ----

FREQ_BY_DEVICE_TYPE = {
    "FIRE_PUMP_CONTROLLER": "MONTHLY",
    "GAUGE_VALVE": "QUARTERLY",
    "SUPERVISORY_SWITCH": "QUARTERLY",
    "SMOKE_DETECTOR": "ANNUAL",
    "PULL_STATION": "ANNUAL",
    "NOTIFICATION_APPLIANCE": "ANNUAL",
    "SPRINKLER_HEAD": "ANNUAL",
    "BACKFLOW_ASSEMBLY": "ANNUAL",
}

INTERVAL_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3, "ANNUAL": 12}
EVENTS_PER_FREQ = {"MONTHLY": 12, "QUARTERLY": 4, "ANNUAL": 1}

BASE_FEE_CENTS = {
    "FIRE_ALARM": 120000,
    "SPRINKLER": 180000,
    "BACKFLOW": 9000,
    "FIRE_PUMP": 240000,
}

LICENSE_CLASS_FOR_CATEGORY = {
    "FIRE_ALARM": "ALARM",
    "SPRINKLER": "SPRINKLER",
    "BACKFLOW": "BACKFLOW",
    "FIRE_PUMP": "PUMP",
}

# ---- correction / notification windows ----
CRITICAL_CORRECTION_DAYS = 1
NONCRITICAL_CORRECTION_DAYS = 30
MARSHAL_REPORT_WINDOW_DAYS = 7
PERMIT_VALIDITY_DAYS = 90
IMPAIRMENT_OUT_OF_SERVICE_HOURS = 10
IMPAIRMENT_BUFFER_HOURS = 4
PLANNED_NOTIFY_BEFORE_HOURS = 8
UNPLANNED_NOTIFY_AFTER_HOURS = 2
DEFICIENCY_EXTENSION_DAYS = 30

# ---- late fees / money ----
CRITICAL_LATE_PER_DAY_CENTS = 20000
NONCRITICAL_LATE_PER_DAY_CENTS = 5000
LATE_FEE_CAP_DAYS = 30
BACKFLOW_TEST_FEE_CENTS = 40000
BACKFLOW_PAYMENT_DUE_DAYS = 30
MIN_PERMIT_FEE_CENTS = 7500

# ---- false alarm fee schedule ----
CHARGEABLE_CAUSES = {"NEGLIGENCE", "EQUIPMENT_FAULT", "UNKNOWN"}
HABITUAL_SURCHARGE_CENTS = 25000
FALSE_ALARM_WINDOW_DAYS = 365  # trailing window [alarm-364d, alarm)

# ---- compliance score deductions ----
DEDUCT_CRITICAL_OVERDUE = 40
DEDUCT_NONCRITICAL_OVERDUE = 10
DEDUCT_LATE_REPORT = 25
DEDUCT_LATE_IMPAIRMENT_NOTICE = 60
DEDUCT_NEGLIGENCE_ALARM = 15
DEDUCT_FAILED_SPECIALTY_TEST = 30
DEDUCT_LAPSED_PLAN = 75
DEDUCT_NO_ACCESS = 20
DEDUCT_WAIVER = 5
DEDUCT_UNPERMITTED_WORK = 100
AUDIT_ONTIME_EVENT_BONUS = 2
AUDIT_BONUS_CAP = 50
AUDIT_LICENSE_DEDUCTION = 100
AUDIT_WINDOW_DAYS = 90

SUSPEND_SCORE_LT = 600
PROBATION_SCORE_LT = 850
SUSPEND_CRITICAL_GTE = 3
PROBATION_CRITICAL_GTE = 1

TECH_CAPACITY_MAX = 3


def round_cents(d):
    """Round a Decimal to whole cents, half-up."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_calendar_months(d, months):
    """Add calendar months with month-end clamping: 2026-01-31 + 1 -> 2026-02-28."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def whole_months_between(start, end):
    """Max k >= 0 such that add_calendar_months(start, k) <= end."""
    if end < start:
        return 0
    k = (end.year - start.year) * 12 + (end.month - start.month)
    while k > 0 and add_calendar_months(start, k) > end:
        k -= 1
    return max(0, k)


# ---------------------------------------------------------------------
# Device frequency / next due
# ---------------------------------------------------------------------

def interval_for(device):
    return INTERVAL_MONTHS[device["frequency_code"]]


def device_next_due_from_base(base_date, frequency_code):
    return add_calendar_months(base_date, INTERVAL_MONTHS[frequency_code])


def covered_devices_of_event(event):
    """Devices an inspection event covers: IN_SERVICE devices on its system."""
    return [d for d in store.devices.values()
            if d["system_id"] == event["system_id"] and d["status"] == "IN_SERVICE"]


# ---------------------------------------------------------------------
# Plan requirement counts and posture
# ---------------------------------------------------------------------

def child_events(plan):
    return [e for e in store.events.values() if e["plan_id"] == plan["id"]]


def recompute_plan_totals(plan):
    """plan_requirement_count: device-derived requirement + completed count."""
    prop = store.properties.get(plan["property_id"])
    total = 0
    if prop is not None:
        for sys in store.systems.values():
            if sys["property_id"] != prop["id"] or sys["status"] != "IN_SERVICE":
                continue
            for dev in store.devices.values():
                if dev["system_id"] == sys["id"] and dev["status"] == "IN_SERVICE":
                    total += EVENTS_PER_FREQ[dev["frequency_code"]]
    completed = sum(1 for e in child_events(plan) if e["status"] == "COMPLETED")
    set_fields(plan, total_events_required=total, events_completed=completed)


def recompute_property_plan_totals(property_id):
    """Refresh totals on the property's non-terminal plans."""
    for plan in store.plans.values():
        if plan["property_id"] == property_id and plan["plan_posture"] not in ("FULFILLED", "LAPSED"):
            recompute_plan_totals(plan)


def derive_plan_posture(plan):
    """plan_posture_derive: LAPSED first when out of year, then FULFILLED, then
    IN_PROGRESS. Terminal postures never move."""
    posture = plan["plan_posture"]
    if posture in ("FULFILLED", "LAPSED"):
        return
    today = store.today()
    children = child_events(plan)
    out_of_year = today > date(plan["plan_year"], 12, 31)
    if out_of_year and posture in ("SCHEDULED", "IN_PROGRESS"):
        plan["plan_posture"] = "LAPSED"
        touch(plan)
        for ev in children:
            if ev["status"] == "SCHEDULED":
                ev["status"] = "CANCELLED"
                touch(ev)
        con = _contractor_of_plan(plan)
        if con is not None:
            recompute_contractor(con)
        return
    completed = sum(1 for e in children if e["status"] == "COMPLETED")
    all_terminal = all(e["status"] in ("COMPLETED", "CANCELLED", "NO_ACCESS") for e in children)
    any_no_access = any(e["status"] == "NO_ACCESS" for e in children)
    if (completed == plan["total_events_required"] and completed > 0
            and all_terminal and not any_no_access
            and posture in ("SCHEDULED", "IN_PROGRESS")):
        changed = plan["plan_posture"] != "FULFILLED" or plan["events_completed"] != completed
        plan["plan_posture"] = "FULFILLED"
        plan["events_completed"] = completed
        if changed:
            touch(plan)
        con = _contractor_of_plan(plan)
        if con is not None:
            recompute_contractor(con)
        return
    if posture == "SCHEDULED" and any(e["status"] in ("IN_PROGRESS", "COMPLETED") for e in children):
        plan["plan_posture"] = "IN_PROGRESS"
        touch(plan)


def _contractor_of_plan(plan):
    prop = store.properties.get(plan["property_id"])
    if prop is None:
        return None
    return store.contractors.get(prop["contractor_id"])


# ---------------------------------------------------------------------
# Plan fees (fee_proration)
# ---------------------------------------------------------------------

def covered_systems_of_property(property_id):
    return [s for s in store.systems.values()
            if s["property_id"] == property_id and s["status"] == "IN_SERVICE"]


def _service_start(property_id, creation_date):
    systems = covered_systems_of_property(property_id)
    latest_install = max((s["install_date"] for s in systems), default=None)
    if latest_install is not None and latest_install > creation_date:
        return latest_install
    return creation_date


def provisional_fee_cents(property_id, plan_year, creation_date):
    """Calendar-day proration: BASE * days(service_start..Dec 31 inclusive)/365,
    round half-up per system line, then sum."""
    start = _service_start(property_id, creation_date)
    year_end = date(plan_year, 12, 31)
    days = max(0, (year_end - start).days + 1)
    total = 0
    for sys in covered_systems_of_property(property_id):
        base = Decimal(BASE_FEE_CENTS[sys["system_category"]])
        total += round_cents(base * Decimal(days) / Decimal(365))
    return total


def final_fee_cents(property_id, plan_year, creation_date):
    """Remaining-full-month proration: whole months strictly after the service
    start's month through December of plan_year (12 when service start predates
    the plan year); round half-up per system line, then sum."""
    start = _service_start(property_id, creation_date)
    if start.year == plan_year:
        months = 12 - start.month
    elif start < date(plan_year, 1, 1):
        months = 12
    else:
        months = 0
    total = 0
    for sys in covered_systems_of_property(property_id):
        base = Decimal(BASE_FEE_CENTS[sys["system_category"]])
        total += round_cents(base * Decimal(months) / Decimal(12))
    return total


# ---------------------------------------------------------------------
# Deficiency late fees
# ---------------------------------------------------------------------

def correction_window_days(classification):
    return CRITICAL_CORRECTION_DAYS if classification == "CRITICAL" else NONCRITICAL_CORRECTION_DAYS


def deficiency_late_fee_cents(deficiency, relevant_date):
    """days late clamped to [0, 30], times the per-day rate for the class."""
    deadline = deficiency["correction_deadline"]
    if deadline is None:
        return 0
    days_late = max(0, (relevant_date - deadline).days)
    days_late = min(days_late, LATE_FEE_CAP_DAYS)
    rate = CRITICAL_LATE_PER_DAY_CENTS if deficiency["classification"] == "CRITICAL" \
        else NONCRITICAL_LATE_PER_DAY_CENTS
    return days_late * rate


# ---------------------------------------------------------------------
# False alarm fees
# ---------------------------------------------------------------------

def false_alarm_sequence_number(prop, alarm_date, exclude_id=None):
    """1 + count of the property's OTHER chargeable, non-WAIVED cases whose
    alarm dates fall in [alarm_date - 364d, alarm_date)."""
    window_start = alarm_date - timedelta(days=FALSE_ALARM_WINDOW_DAYS - 1)
    prior = 0
    for case in store.false_alarm_cases.values():
        if case["property_id"] != prop["id"] or case["id"] == exclude_id:
            continue
        if not case["chargeable"] or case["status"] == "WAIVED":
            continue
        case_date = case["alarm_occurred_at"].date()
        if window_start <= case_date < alarm_date:
            prior += 1
    return prior + 1


def false_alarm_fee_cents(occupancy_class, sequence_number):
    """Tier by sequence number; RESIDENTIAL halves each tier (round half-up);
    habitual surcharge 25000 added at sequence >= 7 in both variants."""
    n = sequence_number
    if n <= 2:
        tier = 0
    elif n <= 4:
        tier = 15000
    elif n <= 6:
        tier = 30000
    else:
        tier = 50000
    if occupancy_class == "RESIDENTIAL":
        tier = round_cents(Decimal(tier) / Decimal(2))
    surcharge = HABITUAL_SURCHARGE_CENTS if n >= 7 else 0
    return tier + surcharge


# ---------------------------------------------------------------------
# Permit fee tiers
# ---------------------------------------------------------------------

def permit_fee_cents(valuation_cents):
    """Marginal tiers: first 200000 at 3%, next 300000 at 2.5%, remainder at
    1.5%; floored at 7500; a single round-half-up at the very end."""
    v = Decimal(valuation_cents)
    fee = Decimal(0)
    t1 = min(v, Decimal(200000))
    fee += t1 * Decimal("0.03")
    v -= t1
    if v > 0:
        t2 = min(v, Decimal(300000))
        fee += t2 * Decimal("0.025")
        v -= t2
    if v > 0:
        fee += v * Decimal("0.015")
    fee = max(fee, Decimal(MIN_PERMIT_FEE_CENTS))
    return round_cents(fee)


# ---------------------------------------------------------------------
# Backflow late penalty (compounds monthly, rounding per step)
# ---------------------------------------------------------------------

def backflow_penalty_balance_cents(months_late):
    balance = Decimal(BACKFLOW_TEST_FEE_CENTS)
    for _ in range(months_late):
        balance = Decimal(round_cents(balance * Decimal("1.05")))
    return int(balance)


# ---------------------------------------------------------------------
# Impairment status derivation
# ---------------------------------------------------------------------

def derive_impairment_status(sys):
    """impairment_status_derive: DECOMMISSIONED always OUT_OF_SERVICE; any
    OPEN/NOTIFIED impairment past planned_start + 10h -> OUT_OF_SERVICE; any
    open -> IMPAIRED; else NORMAL."""
    if sys["status"] == "DECOMMISSIONED":
        set_fields(sys, impairment_status="OUT_OF_SERVICE")
        return
    now = store.now()
    open_rows = [i for i in store.impairments.values()
                 if i["system_id"] == sys["id"] and i["status"] in ("OPEN", "NOTIFIED")]
    out_of_service = any(
        now > (i["planned_start"] + timedelta(hours=IMPAIRMENT_OUT_OF_SERVICE_HOURS))
        for i in open_rows
    )
    if out_of_service:
        status = "OUT_OF_SERVICE"
    elif open_rows:
        status = "IMPAIRED"
    else:
        status = "NORMAL"
    set_fields(sys, impairment_status=status)


# ---------------------------------------------------------------------
# Compliance scoring and posture
# ---------------------------------------------------------------------

def _contractor_ledger(con):
    """Yield every entity whose FK chain reaches this contractor."""
    props = [p for p in store.properties.values() if p["contractor_id"] == con["id"]]
    plans, events, deficiencies, reports = [], [], [], []
    systems, impairments, bts, pts, permits, devices = [], [], [], [], [], []
    alarms = []
    for prop in props:
        alarms.extend(c for c in store.false_alarm_cases.values() if c["property_id"] == prop["id"])
        for plan in [p for p in store.plans.values() if p["property_id"] == prop["id"]]:
            plans.append(plan)
            for ev in [e for e in store.events.values() if e["plan_id"] == plan["id"]]:
                events.append(ev)
                deficiencies.extend(d for d in store.deficiencies.values() if d["event_id"] == ev["id"])
                reports.extend(r for r in store.reports.values() if r["event_id"] == ev["id"])
        for sys in [s for s in store.systems.values() if s["property_id"] == prop["id"]]:
            systems.append(sys)
            devices.extend(d for d in store.devices.values() if d["system_id"] == sys["id"])
            impairments.extend(i for i in store.impairments.values() if i["system_id"] == sys["id"])
            bts.extend(b for b in store.backflow_tests.values() if b["system_id"] == sys["id"])
            pts.extend(t for t in store.pump_tests.values() if t["system_id"] == sys["id"])
            permits.extend(m for m in store.permits.values() if m["system_id"] == sys["id"])
    technicians = [t for t in store.technicians.values() if t["contractor_id"] == con["id"]]
    return {
        "properties": props, "plans": plans, "events": events,
        "deficiencies": deficiencies, "reports": reports, "systems": systems,
        "devices": devices, "impairments": impairments, "backflow_tests": bts,
        "pump_tests": pts, "permits": permits, "alarms": alarms,
        "technicians": technicians,
    }


def provisional_score(con, ledger=None):
    """compliance_score_recompute, provisional variant: base formula exactly —
    no bonuses, no license deduction; floored at 0."""
    if ledger is None:
        ledger = _contractor_ledger(con)
    today = store.today()
    score = 1000
    open_critical_overdue = 0
    for d in ledger["deficiencies"]:
        deadline = d["correction_deadline"]
        overdue = deadline is not None and today > deadline
        if d["status"] == "OPEN" and overdue:
            if d["classification"] == "CRITICAL":
                score -= DEDUCT_CRITICAL_OVERDUE
                open_critical_overdue += 1
            else:
                score -= DEDUCT_NONCRITICAL_OVERDUE
        if d["status"] == "WAIVED":
            score -= DEDUCT_WAIVER
    for r in ledger["reports"]:
        if r["status"] == "SUBMITTED" and r["is_late"]:
            score -= DEDUCT_LATE_REPORT
    for i in ledger["impairments"]:
        if i["status"] in ("NOTIFIED", "RESTORED", "CLOSED") and i["notification_late"]:
            score -= DEDUCT_LATE_IMPAIRMENT_NOTICE
    for c in ledger["alarms"]:
        if c["status"] in ("ASSESSED", "PAID") and c["cause_code"] == "NEGLIGENCE":
            score -= DEDUCT_NEGLIGENCE_ALARM
    for t in ledger["backflow_tests"]:
        if t["status"] == "FAILED_OPEN":
            score -= DEDUCT_FAILED_SPECIALTY_TEST
    for t in ledger["pump_tests"]:
        if t["status"] == "FAILED_OPEN":
            score -= DEDUCT_FAILED_SPECIALTY_TEST
    for p in ledger["plans"]:
        if p["plan_posture"] == "LAPSED":
            score -= DEDUCT_LAPSED_PLAN
    for e in ledger["events"]:
        if e["status"] == "NO_ACCESS":
            score -= DEDUCT_NO_ACCESS
    for m in ledger["permits"]:
        if m["status"] == "FINED":
            score -= DEDUCT_UNPERMITTED_WORK
    return max(0, score), open_critical_overdue


def derive_posture(score, open_critical_overdue):
    """posture_derive: threshold table with >= / < exactly as written."""
    if score < SUSPEND_SCORE_LT or open_critical_overdue >= SUSPEND_CRITICAL_GTE:
        return "SUSPENDED"
    if score < PROBATION_SCORE_LT or open_critical_overdue >= PROBATION_CRITICAL_GTE:
        return "PROBATION"
    return "GOOD_STANDING"


def recompute_contractor(con):
    """Recompute and persist the provisional score + derived posture."""
    score, open_critical_overdue = provisional_score(con)
    posture = derive_posture(score, open_critical_overdue)
    set_fields(con, compliance_score=score, posture=posture)


def audited_score(con):
    """Audited variant: provisional base + on-time-event bonus (2 per event,
    cap 50, completed within trailing 90 days) - 100 when any technician holds
    an EXPIRED/REVOKED license; floored at 0. Computed on demand, not persisted."""
    ledger = _contractor_ledger(con)
    prov, _ = provisional_score(con, ledger)
    today = store.today()
    window_start = today - timedelta(days=AUDIT_WINDOW_DAYS)
    on_time = 0
    for ev in ledger["events"]:
        if ev["status"] != "COMPLETED" or not ev.get("_on_time"):
            continue
        completed_date = ev["completed_at"].date()
        if window_start <= completed_date <= today:
            on_time += 1
    bonus = min(AUDIT_BONUS_CAP, AUDIT_ONTIME_EVENT_BONUS * on_time)
    license_deduction = 0
    for tech in ledger["technicians"]:
        if any(lr["technician_id"] == tech["id"] and lr["status"] in ("EXPIRED", "REVOKED")
               for lr in store.license_records.values()):
            license_deduction = AUDIT_LICENSE_DEDUCTION
            break
    return max(0, prov + bonus - license_deduction), prov


# ---------------------------------------------------------------------
# License validity
# ---------------------------------------------------------------------

def technician_has_valid_license(technician_id, license_class, relevant_date):
    """ACTIVE LicenseRecord of the required class with expires_on strictly
    after the relevant date."""
    for lr in store.license_records.values():
        if (lr["technician_id"] == technician_id
                and lr["license_class"] == license_class
                and lr["status"] == "ACTIVE"
                and lr["expires_on"] > relevant_date):
            return True
    return False
