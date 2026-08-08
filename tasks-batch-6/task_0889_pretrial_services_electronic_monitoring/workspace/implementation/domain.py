"""Business logic: scoring, fee calculation, ledger/device conservation, and
cascading side-effects (violation escalation, auto-created violations)."""

from decimal import Decimal, ROUND_HALF_UP

from clock import LOGICAL_CLOCK, add_days, add_minutes
from store import DB, base_record, touch

# ---- calculation constants --------------------------------------------------
W_PF = 4
W_PC = 2
W_EMP = 3
W_RES = 3
W_SUB = 5
T_MED = 8
T_MAX = 16

DAILY_SUPERVISION_CENTS = 300
EM_DAILY_CENTS = 650
PER_TEST_CENTS = 2500
ADMIN_FEE = Decimal("1.075")

VIOLATION_WINDOW_DAYS = 90
ESCALATION_THRESHOLD = 10
ESCALATED_CHECKIN_DAYS = 7
TEST_SLOT_MINUTES = 30
FTA_GRACE_HOURS = 2

SEVERITY_POINTS = {"MINOR": 3, "MODERATE": 6, "MAJOR": 10}
LEVEL_LADDER = {"MINIMUM": "MEDIUM", "MEDIUM": "MAXIMUM", "MAXIMUM": "MAXIMUM"}
LEVEL_TO_TIER = {"MINIMUM": "LOW", "MEDIUM": "MODERATE", "MAXIMUM": "HIGH"}


# ---- risk scoring -----------------------------------------------------------
def risk_score(a):
    base = a["prior_failures"] * W_PF + a["pending_charges_count"] * W_PC
    if a["instrument_type"] == "FULL":
        if a.get("employment_status") == "UNEMPLOYED":
            base += W_EMP
        if a.get("residence_stability") == "UNSTABLE":
            base += W_RES
        if a.get("substance_flag"):
            base += W_SUB
    return base


def recommended_level(a, raw):
    if a["pending_violent_charge"]:
        return "MAXIMUM"
    if raw >= T_MAX:
        return "MAXIMUM"
    if raw >= T_MED:
        return "MEDIUM"
    return "MINIMUM"


# ---- supervision fee --------------------------------------------------------
def _round_line(rate, qty):
    raw = Decimal(rate) * Decimal(qty) * ADMIN_FEE
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def supervision_fee(indigent, supervision_days, em_days, scheduled_test_count):
    sup_line = _round_line(DAILY_SUPERVISION_CENTS, supervision_days)
    em_line = _round_line(EM_DAILY_CENTS, em_days)
    test_line = _round_line(PER_TEST_CENTS, scheduled_test_count)
    if indigent:
        return test_line  # ADJUSTED: supervision & EM lines waived
    return sup_line + em_line + test_line  # ASSESSED


# ---- ledger conservation ----------------------------------------------------
def recompute_balance(defendant):
    total = sum(le["amount_cents"] for le in DB.ledger_entries.values()
                if le["defendant_id"] == defendant["id"])
    defendant["balance_owed_cents"] = total


# ---- device conservation ----------------------------------------------------
def bump_device_units(device, delta):
    device["available_units"] += delta
    touch(device)


# ---- cumulative violation score + escalation --------------------------------
def recompute_cumulative_score(defendant):
    now = LOGICAL_CLOCK.now()
    window_start = add_days(now, -VIOLATION_WINDOW_DAYS)
    total = 0
    for v in DB.violations.values():
        if (v["defendant_id"] == defendant["id"]
                and v["status"] == "ADJUDICATED_SANCTION"
                and v["adjudicated_at"] is not None
                and v["adjudicated_at"] >= window_start):
            total += v["severity_points"]
    defendant["cumulative_violation_score"] = total
    return total


def escalate_if_needed(defendant, score):
    """After a sanction: if the score crossed the threshold, escalate the
    supervision level one step and spawn the AUTO_ESCALATION LevelAdjustment
    plus an ESCALATION check-in."""
    if score < ESCALATION_THRESHOLD:
        return
    current = defendant["supervision_level"]
    if current is None:
        return
    new_level = LEVEL_LADDER[current]
    if new_level == current:
        return
    defendant["supervision_level"] = new_level

    adj = base_record(versioned=False)
    adj.update({
        "defendant_id": defendant["id"],
        "from_level": current,
        "to_level": new_level,
        "source": "AUTO_ESCALATION",
        "reason": None,
        "adjusted_by_user_id": None,
    })
    DB.level_adjustments[adj["id"]] = adj

    ci = base_record(versioned=True)
    ci.update({
        "defendant_id": defendant["id"],
        "due_at": add_days(LOGICAL_CLOCK.now(), ESCALATED_CHECKIN_DAYS),
        "completed_at": None,
        "origin": "ESCALATION",
        "status": "SCHEDULED",
    })
    DB.check_ins[ci["id"]] = ci


# ---- auto-created (cascade) violation ---------------------------------------
def create_cascade_violation(defendant_id, violation_type, severity, source_ref):
    v = base_record(versioned=True)
    v.update({
        "defendant_id": defendant_id,
        "violation_type": violation_type,
        "severity": severity,
        "severity_points": 0,
        "status": "REPORTED",
        "reported_by_user_id": None,
        "adjudicated_by_user_id": None,
        "adjudicated_at": None,
        "source_ref": source_ref,
    })
    DB.violations[v["id"]] = v
    return v


# ---- helpers ----------------------------------------------------------------
def defendant_has_ordered_condition(defendant_id, condition):
    for o in DB.release_orders.values():
        if (o["defendant_id"] == defendant_id
                and o["status"] == "ORDERED"
                and condition in o["ordered_conditions"]):
            return True
    return False
