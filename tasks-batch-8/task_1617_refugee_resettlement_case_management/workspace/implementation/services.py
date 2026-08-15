"""Business logic: calculations, derived fields, cascades, and snapshots."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, clock_date, new_id, stamp_new, touch

REQUIRED_FURNISHINGS = ["BED", "LINENS", "TABLE", "CHAIRS", "COOKWARE", "CLEANING_SUPPLIES"]
ALL_TOPICS = [
    "US_LAWS",
    "HEALTHCARE_ACCESS",
    "EDUCATION_SYSTEM",
    "EMPLOYMENT_RIGHTS",
    "HOUSING_SAFETY",
    "BUDGETING",
]

DUE_RULE_OFFSETS = {"DAYS_30": 30, "DAYS_90": 90}
AT_RISK_WINDOW_DAYS = 7

FPG_MONTHLY_BASE_CENTS = 130000
FPG_MONTHLY_INCREMENT_CENTS = 45000
EARNED_DISREGARD_MONTHLY_CENTS = 20000

PER_CAPITA_ANNUAL_CENTS = 1250000
SIZE_CAP = 8

NON_TERMINAL_SETUP_STATUSES = ("PREPARING", "READY", "OCCUPIED")


# ---------------------------------------------------------------------------
# Lookups (insertion order == created_at ascending order)
# ---------------------------------------------------------------------------

def members_of(case_id):
    return [m for m in store.members.values() if m["case_id"] == case_id]


def setups_of_case(case_id):
    return [s for s in store.housing_setups.values() if s["case_id"] == case_id]


def setups_of_unit(unit_id):
    return [s for s in store.housing_setups.values() if s["housing_unit_id"] == unit_id]


def benchmarks_of_case(case_id):
    return [b for b in store.benchmarks.values() if b["case_id"] == case_id]


def sessions_of_case(case_id):
    return [s for s in store.orientation_sessions.values() if s["case_id"] == case_id]


def plans_of_case(case_id):
    return [p for p in store.employment_plans.values() if p["case_id"] == case_id]


def applications_of_case(case_id):
    return [a for a in store.benefit_applications.values() if a["case_id"] == case_id]


def notes_of_case(case_id):
    return [n for n in store.case_notes.values() if n["case_id"] == case_id]


def transfers_of_case(case_id):
    return [t for t in store.case_transfers.values() if t["case_id"] == case_id]


def sorted_records(records):
    return sorted(records, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Derived fields (computed on read against the logical clock)
# ---------------------------------------------------------------------------

def compute_posture(case):
    today = clock_date()
    pending = [b for b in benchmarks_of_case(case["id"]) if b["status"] == "PENDING"]
    if any(b["due_date"] < today for b in pending):
        return "OVERDUE"
    if any(b["due_date"] <= today + timedelta(days=AT_RISK_WINDOW_DAYS) for b in pending):
        return "AT_RISK"
    return "ON_TRACK"


def compute_topics(case_id):
    return sorted(
        {s["topic"] for s in sessions_of_case(case_id) if s["status"] == "COMPLETED"}
    )


def compute_unit_status(unit_id):
    today = clock_date()
    active = [
        s
        for s in setups_of_unit(unit_id)
        if s["status"] in NON_TERMINAL_SETUP_STATUSES
    ]
    if any(s["occupancy_start"] <= today < s["occupancy_end"] for s in active):
        return "OCCUPIED"
    if active:
        return "RESERVED"
    return "AVAILABLE"


def age_in_years(dob, on):
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


# ---------------------------------------------------------------------------
# Arrival cascade (Case PRE_ARRIVAL -> ARRIVED)
# ---------------------------------------------------------------------------

def arrive_cascade(case, arrival_date):
    case["status"] = "ARRIVED"
    case["actual_arrival_date"] = arrival_date
    case["airport_pickup_completed"] = True

    members = members_of(case["id"])
    for m in members:
        age = age_in_years(m["date_of_birth"], arrival_date)
        m["age_at_arrival"] = age
        m["school_age_at_arrival"] = (5 <= age <= 17)
        touch(m)

    for s in setups_of_case(case["id"]):
        if s["status"] == "READY":
            s["status"] = "OCCUPIED"
            touch(s)

    specs = [
        ("HOME_VISIT", "DAYS_30"),
        ("HEALTH_SCREENING", "DAYS_30"),
        ("SSN_APPLICATION", "DAYS_30"),
        ("BENEFITS_ENROLLMENT", "DAYS_30"),
        ("CULTURAL_ORIENTATION", "DAYS_90"),
    ]
    if any(m["work_eligible"] and m["age_at_arrival"] is not None and m["age_at_arrival"] >= 18
           for m in members):
        specs.append(("EMPLOYMENT_PLAN", "DAYS_90"))
    if any(m["school_age_at_arrival"] for m in members):
        specs.append(("SCHOOL_ENROLLMENT", "DAYS_30"))

    for service_type, due_rule in specs:
        offset = DUE_RULE_OFFSETS[due_rule]
        bm = {
            "id": new_id(),
            "case_id": case["id"],
            "service_type": service_type,
            "due_rule": due_rule,
            "planned_due_date": case["scheduled_arrival_date"] + timedelta(days=offset),
            "due_date": arrival_date + timedelta(days=offset),
            "fulfilled_on": None,
            "evidence_note_id": None,
            "on_time": None,
            "status": "PENDING",
            "waived_reason": None,
        }
        stamp_new(bm)
        store.benchmarks[bm["id"]] = bm

    touch(case)


# ---------------------------------------------------------------------------
# Transfer-out cascade (Case ARRIVED -> TRANSFERRED_OUT)
# ---------------------------------------------------------------------------

def transfer_out_cascade(case):
    cid = case["id"]
    case["status"] = "TRANSFERRED_OUT"
    case["open_transfer_id"] = None

    for s in setups_of_case(cid):
        if s["status"] in NON_TERMINAL_SETUP_STATUSES:
            s["status"] = "VACATED"
            touch(s)

    for p in plans_of_case(cid):
        if p["status"] == "ACTIVE":
            p["status"] = "CLOSED_TRANSFERRED"
            touch(p)

    for a in applications_of_case(cid):
        if a["status"] in ("DRAFT", "FILED", "DENIED", "APPEALED"):
            a["status"] = "WITHDRAWN"
            touch(a)

    for s in sessions_of_case(cid):
        if s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)

    # All PENDING benchmarks are waived with reason TRANSFER (the
    # CULTURAL_ORIENTATION one because its sessions were cancelled, the rest
    # directly because the case transferred out).
    for b in benchmarks_of_case(cid):
        if b["status"] == "PENDING":
            b["status"] = "WAIVED"
            b["waived_reason"] = "TRANSFER"
            touch(b)

    touch(case)


# ---------------------------------------------------------------------------
# Self-sufficiency determination (integer cents, inclusive >= boundary)
# ---------------------------------------------------------------------------

def self_sufficiency_threshold_cents(household_size):
    return FPG_MONTHLY_BASE_CENTS + (household_size - 1) * FPG_MONTHLY_INCREMENT_CENTS


def determine_self_sufficient(plan, household_size, variant):
    threshold = self_sufficiency_threshold_cents(household_size)
    if variant == "MONTHLY":
        income = plan["monthly_income_cents"]
        effective = income - min(income, EARNED_DISREGARD_MONTHLY_CENTS)
        return effective >= threshold
    income3 = plan["trailing_3m_income_cents"]
    effective3 = income3 - min(income3, 3 * EARNED_DISREGARD_MONTHLY_CENTS)
    return effective3 >= 3 * threshold


# ---------------------------------------------------------------------------
# Federal report snapshot calculations
# ---------------------------------------------------------------------------

def covered_months(start, end):
    """Calendar months whose [month_start, next_month_start) overlaps [start, end).

    end is exclusive. Caller guarantees start < end.
    """
    last = end - timedelta(days=1)
    return (last.year * 12 + last.month) - (start.year * 12 + start.month) + 1


def per_case_allocation_cents(case, period_start, period_end):
    """Round the per-case allocation half-up to integer cents BEFORE summing."""
    window_start = max(case["actual_arrival_date"], period_start)
    months = covered_months(window_start, period_end)
    size_capped = min(case["household_size"], SIZE_CAP)
    raw = Decimal(PER_CAPITA_ANNUAL_CENTS * size_capped * months) / Decimal(12)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def included_cases(period_start, period_end):
    return [
        c
        for c in store.cases.values()
        if c["actual_arrival_date"] is not None
        and period_start <= c["actual_arrival_date"] < period_end
    ]


def generate_report_snapshot(period_start, period_end):
    cases = included_cases(period_start, period_end)
    case_ids = {c["id"] for c in cases}
    counted = [
        b
        for b in store.benchmarks.values()
        if b["case_id"] in case_ids and period_start <= b["due_date"] < period_end
    ]
    met = [b for b in counted if b["status"] == "MET"]
    snapshot = {
        "cases_arrived_count": len(cases),
        "benchmarks_met_count": len(met),
        "benchmarks_met_on_time_count": len([b for b in met if b["on_time"] is True]),
        "benchmarks_pending_count": len([b for b in counted if b["status"] == "PENDING"]),
        "benchmarks_waived_count": len([b for b in counted if b["status"] == "WAIVED"]),
        "per_capita_allocation_cents": sum(
            per_case_allocation_cents(c, period_start, period_end) for c in cases
        ),
    }
    return snapshot, sorted(c["id"] for c in cases)
