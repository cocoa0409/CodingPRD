"""Calculation rules (PRD 2.6, 2.7, 2.10, 3.4, 3.8, 3.9)."""
from datetime import timedelta
from decimal import Decimal

from core import D, rhu, clock, db, parse_dt, sorted_rows

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
PROJECT_TYPES = ["NEW_CONSTRUCTION", "RETRO_COMMISSIONING"]
CERT_TARGETS = ["NONE", "STANDARD", "ENHANCED"]
DELIVERY_PHASES = [
    "PLANNING", "DESIGN", "CONSTRUCTION", "FUNCTIONAL_TESTING",
    "ACCEPTANCE", "WARRANTY", "CLOSED",
]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
CRITICALITIES = ["LIFE_SAFETY", "CRITICAL", "STANDARD"]
REQUIREMENT_STATUSES = ["DRAFT", "APPROVED", "SUPERSEDED"]
PLAN_STATUSES = ["DRAFT", "APPROVED", "SUPERSEDED"]
SUBMITTAL_KINDS = ["DESIGN_DOCUMENT", "PRODUCT_DATA", "SHOP_DRAWING", "OM_DATA"]
SUBMITTAL_STATUSES = ["RECEIVED", "APPROVED", "APPROVED_AS_NOTED", "REVISE_AND_RESUBMIT"]
REVIEW_DECISIONS = ["APPROVED", "APPROVED_AS_NOTED", "REVISE_AND_RESUBMIT"]
SYSTEM_TYPES = ["AHU", "CHILLER", "BOILER", "LIGHTING", "FIRE_ALARM", "ELEVATOR", "BAS"]
INSTALL_STATUSES = ["NOT_INSTALLED", "INSTALLED", "STARTED_UP", "REMOVED"]
VERIFICATION_STATUSES = [
    "UNVERIFIED", "PREFUNCTIONAL_VERIFIED", "FUNCTIONAL_ACCEPTED", "CONDITIONALLY_ACCEPTED",
]
VERIFIED_SET = {"PREFUNCTIONAL_VERIFIED", "FUNCTIONAL_ACCEPTED", "CONDITIONALLY_ACCEPTED"}
CHECKLIST_STATUSES = ["DRAFT", "EXECUTED", "VERIFIED", "REWORK"]
ITEM_RESULTS = ["PENDING", "PASS", "FAIL", "NA"]
ITEM_RESULT_INPUTS = ["PASS", "FAIL", "NA"]
TEST_STATUSES = [
    "SCHEDULED", "IN_PROGRESS", "PASSED", "PASSED_WITH_EXCEPTIONS", "FAILED", "CANCELLED",
]
COMPLETED_TEST_STATUSES = {"PASSED", "PASSED_WITH_EXCEPTIONS", "FAILED"}
ISSUE_ORIGINS = ["DESIGN_REVIEW", "SUBMITTAL", "PREFUNCTIONAL", "FUNCTIONAL", "SEASONAL", "RETRO_CX"]
ISSUE_SEVERITIES = ["S1", "S2", "S3", "S4"]
ISSUE_STATUSES = ["OPEN", "IN_REVIEW", "VERIFIED_CLOSED", "DEFERRED", "VOID"]
LIVE_ISSUE_STATUSES = {"OPEN", "IN_REVIEW"}
RETAINAGE_ISSUE_STATUSES = {"OPEN", "IN_REVIEW", "DEFERRED"}
SEASONS = ["HEATING", "COOLING", "SHOULDER"]
DEFERRED_STATUSES = ["PLANNED", "BLOCKED", "EXECUTED_PASS", "EXECUTED_FAIL", "MISSED"]
DEFERRED_LIVE = {"PLANNED", "BLOCKED"}
DELIVERABLE_KINDS = ["TRAINING_SESSION", "SYSTEMS_MANUAL_SECTION", "OM_DATA_PACKAGE"]
DELIVERABLE_STATUSES = ["PLANNED", "DELIVERED", "ACCEPTED", "RETURNED"]
CREDIT_STATUSES = [
    "NOT_STARTED", "IN_PREPARATION", "SUBMITTED", "AWARDED", "DENIED", "WITHDRAWN",
]
TIERS = ["NONE", "BRONZE", "SILVER", "GOLD"]
EVIDENCE_TYPES = [
    "EQUIPMENT_VERIFICATION", "FUNCTIONAL_TEST", "CHECKLIST",
    "TRAINING", "MANUAL_SECTION", "ENERGY_BASELINE",
]
BASELINE_STATUSES = ["BASELINE_SET", "POST_PERIOD_RECORDED", "CERTIFIED"]
SAVINGS_VARIANTS = ["DEEMED", "MEASURED"]
ACCEPTANCE_KINDS = ["SUBSTANTIAL", "FINAL"]
ADJUDICATION_DECISIONS = ["AWARDED", "DENIED"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SEVERITY_WEIGHT = {"S1": D("25.0"), "S2": D("12.0"), "S3": D("8.0"), "S4": D("2.0")}
BLOCKING_MULTIPLIER = D("2.0")
AGING_STEP_DAYS = 14
AGING_STEP_MULTIPLIER = D("0.25")
AGING_MULTIPLIER_CAP = D("2.00")
INDEX_CAP = D("100.00")
RESTRICTED_THRESHOLD = D("16.00")
FROZEN_THRESHOLD = D("40.00")

BASE_HOLD_RATE = {"S1": D("0.05"), "S2": D("0.02"), "S3": D("0.005"), "S4": D("0.0")}
CRITICALITY_FACTOR = {"LIFE_SAFETY": D("1.5"), "CRITICAL": D("1.2"), "STANDARD": D("1.0")}
MAX_PROJECT_HOLD_PCT = D("0.10")

AUTO_ISSUE_SEVERITY_BY_CRITICALITY = {
    "LIFE_SAFETY": "S1", "CRITICAL": "S2", "STANDARD": "S3",
}

PREFUNCTIONAL_WEIGHT = D("0.30")
FUNCTIONAL_WEIGHT = D("0.50")
CLOSEOUT_WEIGHT = D("0.20")
SUBSTANTIAL_MIN_SCORE = D("70.00")
FINAL_MIN_SCORE = D("95.00")

DEEMED_REALIZATION_FACTOR = D("0.85")
MEASURED_UNCERTAINTY_DEDUCTION_PCT = D("0.10")

TIER_COMPLETENESS_THRESHOLDS = {"GOLD": D("1.00"), "SILVER": D("0.75"), "BRONZE": D("0.50")}
TIER_QUALITY_WEIGHT = {
    "GOLD": D("1.00"), "SILVER": D("0.85"), "BRONZE": D("0.60"), "NONE": D("0.40"),
}
STALE_EVIDENCE_PENALTY_POINTS = D("15.00")
FINAL_TIER_SCORE_THRESHOLDS = {"GOLD": D("90.00"), "SILVER": D("70.00"), "BRONZE": D("50.00")}
TIER_AWARD_FRACTION = {
    "GOLD": D("1.00"), "SILVER": D("0.75"), "BRONZE": D("0.50"), "NONE": D("0.00"),
}

TRAINING_COVERAGE_MIN = D("0.80")
MAX_REVIEW_ROUNDS = 3
MOBILIZATION_BUFFER_MINUTES = 60
EXCEPTION_TOLERANCE_MULTIPLIER = 2


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def project_equipment(project_id):
    return sorted_rows([e for e in db.equipment.values() if e["project_id"] == project_id])


def project_issues(project_id):
    return sorted_rows([i for i in db.issues.values() if i["project_id"] == project_id])


def project_plans(project_id):
    return sorted_rows([p for p in db.plans.values() if p["project_id"] == project_id])


def equipment_checklists(equipment_id):
    return sorted_rows([c for c in db.checklists.values() if c["equipment_id"] == equipment_id])


def equipment_tests(equipment_id):
    return sorted_rows([t for t in db.tests.values() if t["equipment_id"] == equipment_id])


def equipment_deferred_tests(equipment_id):
    return sorted_rows(
        [d for d in db.deferred_tests.values() if d["equipment_id"] == equipment_id]
    )


def equipment_deliverables(equipment_id):
    return sorted_rows(
        [d for d in db.deliverables.values() if d.get("equipment_id") == equipment_id]
    )


def project_of_equipment(equipment_row):
    return db.projects.get(equipment_row["project_id"])


def project_of_test(test_row):
    eq = db.equipment.get(test_row["equipment_id"])
    return project_of_equipment(eq) if eq else None


def project_of_checklist(checklist_row):
    eq = db.equipment.get(checklist_row["equipment_id"])
    return project_of_equipment(eq) if eq else None


def project_of_deferred_test(row):
    eq = db.equipment.get(row["equipment_id"])
    return project_of_equipment(eq) if eq else None


def project_deferred_tests(project_id):
    rows = []
    for d in db.deferred_tests.values():
        eq = db.equipment.get(d["equipment_id"])
        if eq is not None and eq["project_id"] == project_id:
            rows.append(d)
    return sorted_rows(rows)


def project_tests(project_id):
    rows = []
    for t in db.tests.values():
        eq = db.equipment.get(t["equipment_id"])
        if eq is not None and eq["project_id"] == project_id:
            rows.append(t)
    return sorted_rows(rows)


def credit_evidence(credit_id):
    return sorted_rows([e for e in db.evidence.values() if e["credit_id"] == credit_id])


def newest_plan(project_id):
    plans = project_plans(project_id)
    return plans[-1] if plans else None


def newest_approved_plan(project_id):
    approved = [p for p in project_plans(project_id) if p["status"] == "APPROVED"]
    return approved[-1] if approved else None


def checklist_is_verified(equipment_id):
    return any(c["status"] == "VERIFIED" for c in equipment_checklists(equipment_id))


# ---------------------------------------------------------------------------
# issue_severity_index / readiness posture
# ---------------------------------------------------------------------------
def compute_issue_severity_index(project_id):
    now = clock.now()
    total = D("0.00")
    live = [i for i in project_issues(project_id) if i["status"] in LIVE_ISSUE_STATUSES]
    for issue in live:
        opened = parse_dt(issue["opened_at"])
        age_seconds = (now - opened).total_seconds()
        if age_seconds < 0:
            age_seconds = 0
        age_days = int(age_seconds // 86400)
        steps = age_days // AGING_STEP_DAYS
        aging = D("1.00") + AGING_STEP_MULTIPLIER * D(steps)
        if aging > AGING_MULTIPLIER_CAP:
            aging = AGING_MULTIPLIER_CAP
        blocking = BLOCKING_MULTIPLIER if issue["blocks_acceptance"] else D("1.0")
        contrib = rhu(SEVERITY_WEIGHT[issue["severity"]] * aging * blocking, 2)
        total = total + contrib
    total = rhu(total, 2)
    if total > INDEX_CAP:
        total = INDEX_CAP
    return total


def derive_posture(index_value):
    idx = D(index_value)
    if idx >= FROZEN_THRESHOLD:
        return "FROZEN"
    if idx >= RESTRICTED_THRESHOLD:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# Retainage
# ---------------------------------------------------------------------------
def compute_retainage_hold_cents(project, equipment_row, severity):
    if equipment_row is not None:
        base = D(equipment_row["contract_value_cents"])
        factor = CRITICALITY_FACTOR[equipment_row["criticality"]]
    else:
        base = D(project["contract_value_cents"])
        factor = CRITICALITY_FACTOR["STANDARD"]
    rate = BASE_HOLD_RATE[severity]
    return int(rhu(base * rate * factor, 0))


def retainage_cap_cents(project):
    return int(project["contract_value_cents"] * 10 // 100)


def compute_retainage_withheld(project_id):
    total = 0
    for issue in project_issues(project_id):
        if issue["status"] in RETAINAGE_ISSUE_STATUSES:
            total += issue["retainage_hold_cents"]
    return total


# ---------------------------------------------------------------------------
# Functional outcome deviation
# ---------------------------------------------------------------------------
def compute_deviation_pct(measured_value, requirement):
    target = D(requirement["target_value"])
    measured = D(measured_value)
    if target == 0:
        return D("0.00") if measured == 0 else D("100.00")
    return rhu(abs(measured - target) / target * D(100), 2)


def outcome_for_deviation(deviation, requirement):
    tol = D(requirement["tolerance_pct"])
    if deviation <= tol:
        return "PASSED"
    if deviation <= D(EXCEPTION_TOLERANCE_MULTIPLIER) * tol:
        return "PASSED_WITH_EXCEPTIONS"
    return "FAILED"


# ---------------------------------------------------------------------------
# Acceptance completion score
# ---------------------------------------------------------------------------
def _latest_completed_test(equipment_id):
    candidates = [
        t for t in equipment_tests(equipment_id)
        if t["status"] in COMPLETED_TEST_STATUSES and t.get("completed_at")
    ]
    if not candidates:
        return None
    best = None
    for t in candidates:
        if best is None:
            best = t
            continue
        if t["completed_at"] > best["completed_at"]:
            best = t
        elif t["completed_at"] == best["completed_at"] and t["_seq"] > best["_seq"]:
            best = t
    return best


def total_weight_units(project_id):
    units = [e for e in project_equipment(project_id) if e["install_status"] != "REMOVED"]
    return sum(e["weight_units"] for e in units)


def compute_acceptance_score(project_id, variant):
    units = [e for e in project_equipment(project_id) if e["install_status"] != "REMOVED"]
    total_weight = sum(e["weight_units"] for e in units)
    if total_weight == 0:
        return D("0.00")
    total = D(0)
    for eq in units:
        weight = D(eq["weight_units"])
        pf = D("1.0") if checklist_is_verified(eq["id"]) else D("0.0")
        latest = _latest_completed_test(eq["id"])
        deferred = equipment_deferred_tests(eq["id"])
        if variant == "PROVISIONAL":
            if latest is not None and latest["status"] in ("PASSED", "PASSED_WITH_EXCEPTIONS"):
                fn = D("1.0")
            elif any(d["status"] in DEFERRED_LIVE for d in deferred):
                fn = D("0.5")
            else:
                fn = D("0.0")
        else:
            if (latest is not None and latest["status"] == "PASSED"
                    and all(d["status"] == "EXECUTED_PASS" for d in deferred)):
                fn = D("1.0")
            elif (latest is not None and latest["status"] == "PASSED_WITH_EXCEPTIONS"
                    and eq["blocking_issue_count"] == 0):
                fn = D("0.5")
            else:
                fn = D("0.0")
        deliverables = equipment_deliverables(eq["id"])
        if deliverables and all(d["status"] == "ACCEPTED" for d in deliverables):
            co = D("1.0")
        else:
            co = D("0.0")
        total += weight * (
            PREFUNCTIONAL_WEIGHT * pf + FUNCTIONAL_WEIGHT * fn + CLOSEOUT_WEIGHT * co
        )
    return rhu(D(100) * total / D(total_weight), 2)


# ---------------------------------------------------------------------------
# Retro-commissioning savings
# ---------------------------------------------------------------------------
def compute_deemed_savings(baseline):
    return rhu(
        D(baseline["stipulated_kwh_per_hour"]) * D(baseline["operating_hours"])
        * DEEMED_REALIZATION_FACTOR, 2,
    )


def compute_measured_savings(baseline, post_kwh, post_hdd):
    adjusted = rhu(D(baseline["baseline_kwh"]) * (D(post_hdd) / D(baseline["baseline_hdd"])), 2)
    gross = adjusted - D(post_kwh)
    if gross < 0:
        gross = D(0)
    return rhu(gross * (D(1) - MEASURED_UNCERTAINTY_DEDUCTION_PCT), 2)


# ---------------------------------------------------------------------------
# Credit documentation score
# ---------------------------------------------------------------------------
def compute_documentation_score(required_evidence_count, fresh_count, stale_count):
    if required_evidence_count == 0:
        completeness = D("0.0")
    else:
        ratio = D(fresh_count) / D(required_evidence_count)
        if ratio > D(1):
            ratio = D(1)
        completeness = rhu(ratio, 4)

    if completeness >= TIER_COMPLETENESS_THRESHOLDS["GOLD"]:
        provisional_tier = "GOLD"
    elif completeness >= TIER_COMPLETENESS_THRESHOLDS["SILVER"]:
        provisional_tier = "SILVER"
    elif completeness >= TIER_COMPLETENESS_THRESHOLDS["BRONZE"]:
        provisional_tier = "BRONZE"
    else:
        provisional_tier = "NONE"

    raw = (D(100) * completeness * TIER_QUALITY_WEIGHT[provisional_tier]
           - STALE_EVIDENCE_PENALTY_POINTS * D(stale_count))
    if raw < 0:
        raw = D("0.0")
    score = rhu(raw, 2)

    if score >= FINAL_TIER_SCORE_THRESHOLDS["GOLD"]:
        final_tier = "GOLD"
    elif score >= FINAL_TIER_SCORE_THRESHOLDS["SILVER"]:
        final_tier = "SILVER"
    elif score >= FINAL_TIER_SCORE_THRESHOLDS["BRONZE"]:
        final_tier = "BRONZE"
    else:
        final_tier = "NONE"

    return completeness, provisional_tier, score, final_tier


# ---------------------------------------------------------------------------
# Coverage ratio
# ---------------------------------------------------------------------------
def compute_coverage_ratio(required_attendee_count, attendee_count):
    if required_attendee_count == 0:
        return D("1.0")
    ratio = D(attendee_count) / D(required_attendee_count)
    if ratio > D(1):
        ratio = D(1)
    return rhu(ratio, 4)


# ---------------------------------------------------------------------------
# Evidence freshness
# ---------------------------------------------------------------------------
def evidence_is_stale(evidence_row):
    etype = evidence_row["evidence_type"]
    ref = evidence_row["evidence_ref_id"]
    if etype == "EQUIPMENT_VERIFICATION":
        row = db.equipment.get(ref)
        return row is None or row["verification_status"] not in VERIFIED_SET
    if etype == "FUNCTIONAL_TEST":
        row = db.tests.get(ref)
        return row is None or row["status"] not in ("PASSED", "PASSED_WITH_EXCEPTIONS")
    if etype == "CHECKLIST":
        row = db.checklists.get(ref)
        return row is None or row["status"] != "VERIFIED"
    if etype in ("TRAINING", "MANUAL_SECTION"):
        row = db.deliverables.get(ref)
        return row is None or row["status"] != "ACCEPTED"
    if etype == "ENERGY_BASELINE":
        row = db.baselines.get(ref)
        return row is None or row["status"] != "CERTIFIED"
    return True


# ---------------------------------------------------------------------------
# Interval geometry
# ---------------------------------------------------------------------------
def witness_conflict_count(project_id, new_start, new_end, exclude_ids=()):
    buffer = timedelta(minutes=MOBILIZATION_BUFFER_MINUTES)
    n_start = new_start - buffer
    n_end = new_end + buffer
    count = 0
    for t in project_tests(project_id):
        if t["id"] in exclude_ids:
            continue
        if t["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        o_start = parse_dt(t["scheduled_start"]) - buffer
        o_end = parse_dt(t["scheduled_end"]) + buffer
        if o_start <= n_end and n_start <= o_end:
            count += 1
    return count


def seasonal_conflict(equipment_id, new_start, new_end):
    for d in equipment_deferred_tests(equipment_id):
        if d["status"] not in DEFERRED_LIVE:
            continue
        o_start = parse_dt(d["window_start"])
        o_end = parse_dt(d["window_end"])
        if o_start < new_end and new_start < o_end:
            return True
    return False
