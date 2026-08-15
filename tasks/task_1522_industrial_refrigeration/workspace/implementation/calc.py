"""Calculation rules (SCAFFOLD 1.3) and the computed-field derivations.

Everything time-dependent is computed live against the logical clock, so a
read always observes the current clock (PRD 2.4: time-dependent derived fields
refresh when the clock is observed on a read) and the checkpoint never has to
repair stored posture data.
"""
from datetime import timedelta
from decimal import Decimal

from store import db
from util import add_days, round_tenth

# -- calculation constants ---------------------------------------------------
RQ_LBS = Decimal("100.0")
NOTIFY_WINDOW_MINUTES = 15
DRILL_QUIET_GAP = timedelta(hours=24)
W_OVERDUE_INSPECTION = 5
W_OPEN_INCIDENT = 3
W_EXPIRED_TRAINING = 2
NONCOMPLIANT_FLOOR = 10
CONDITION_EXTENSION_NUM = 3  # floor(interval * 1.5) == (interval*3)//2
CONDITION_EXTENSION_DEN = 2
MAX_INTERVAL_DAYS = 1095
FAIL_RECHECK_DAYS = 30
TRAINING_VALID_DAYS = 1095
DUE_SOON_DAYS = 30
EXPIRING_SOON_DAYS = 90

AMMONIA_SAT_PSIG_TABLE = {
    50: Decimal("74.5"),
    60: Decimal("92.9"),
    70: Decimal("114.1"),
    80: Decimal("138.8"),
    90: Decimal("166.4"),
    100: Decimal("196.6"),
}

OPEN_INCIDENT_STATES = ("REPORTED", "UNDER_INVESTIGATION", "ACTIONS_ASSIGNED", "REOPENED")
ACTIVE_PERMIT_STATES = ("REQUESTED", "ISSUED", "IN_PROGRESS")


# ---------------------------------------------------------------------------
# facility_charge_rollup (book variant is authoritative for the Facility)
# ---------------------------------------------------------------------------
def book_total(facility_id):
    """Sum of rounded_lbs over ADD lines minus REMOVE lines, per-line rounding
    pinned at posting; unbounded ledger."""
    total = Decimal("0.0")
    for adj in db.charge_adjustments.values():
        if adj["facility_id"] != facility_id:
            continue
        if adj["adjustment_type"] == "ADD":
            total += adj["rounded_lbs"]
        else:
            total -= adj["rounded_lbs"]
    return total


def system_book_total(system_id):
    """Signed net book charge attributed to one system (decommission gate)."""
    total = Decimal("0.0")
    for adj in db.charge_adjustments.values():
        if adj["system_id"] != system_id:
            continue
        if adj["adjustment_type"] == "ADD":
            total += adj["rounded_lbs"]
        else:
            total -= adj["rounded_lbs"]
    return total


def gauge_total(facility_id):
    """Gauge variant: over IN_SERVICE systems only, each contributing its
    latest physical reading, or design_charge_lbs when never gauged."""
    total = Decimal("0.0")
    for system in db.systems.values():
        if system["facility_id"] != facility_id:
            continue
        if system["status"] != "IN_SERVICE":
            continue
        reading = system["last_gauge_reading_lbs"]
        total += reading if reading is not None else system["design_charge_lbs"]
    return total


def charge_posture(total, threshold):
    return "AT_OR_ABOVE_THRESHOLD" if total >= threshold else "BELOW_THRESHOLD"


# ---------------------------------------------------------------------------
# compliance_posture_score
# ---------------------------------------------------------------------------
def _system_facility_id(system_id):
    system = db.systems.get(system_id)
    return system["facility_id"] if system else None


def overdue_inspection_count(facility_id):
    count = 0
    for insp in db.inspections.values():
        if insp["status"] != "OVERDUE":
            continue
        equipment = db.equipment.get(insp["equipment_id"])
        if equipment is None:
            continue
        if _system_facility_id(equipment["system_id"]) == facility_id:
            count += 1
    return count


def open_incident_count(facility_id):
    return sum(
        1
        for inc in db.incidents.values()
        if inc["facility_id"] == facility_id and inc["status"] in OPEN_INCIDENT_STATES
    )


def expired_training_count(facility_id):
    now = db.now()
    count = 0
    for record in db.training_records.values():
        employee = db.employees.get(record["employee_id"])
        if employee is None:
            continue
        if employee["facility_id"] != facility_id:
            continue
        if employee["employment_status"] != "ACTIVE":
            continue
        if now >= record["expires_at"]:
            count += 1
    return count


def posture(facility_id):
    """Returns (overdue, open_incidents, expired_training, score, posture)."""
    overdue = overdue_inspection_count(facility_id)
    open_inc = open_incident_count(facility_id)
    expired = expired_training_count(facility_id)
    score = (
        W_OVERDUE_INSPECTION * overdue
        + W_OPEN_INCIDENT * open_inc
        + W_EXPIRED_TRAINING * expired
    )
    if score == 0:
        band = "COMPLIANT"
    elif score < NONCOMPLIANT_FLOOR:
        band = "DEGRADED"
    else:
        band = "NONCOMPLIANT"
    return overdue, open_inc, expired, score, band


# ---------------------------------------------------------------------------
# inspection_due_date + Equipment.integrity_status
# ---------------------------------------------------------------------------
def next_due_at(equipment, completed_at, result):
    interval = equipment["inspection_interval_days"]
    if equipment["inspection_method"] == "FIXED":
        return add_days(completed_at, interval)
    # CONDITION_BASED
    if result == "PASS":
        extended = (interval * CONDITION_EXTENSION_NUM) // CONDITION_EXTENSION_DEN
        return add_days(completed_at, min(extended, MAX_INTERVAL_DAYS))
    return add_days(completed_at, FAIL_RECHECK_DAYS)


def integrity_status(equipment):
    """FAILED > OVERDUE > DUE_SOON > CURRENT (SCAFFOLD entities.Equipment)."""
    if equipment["last_result"] == "FAIL":
        return "FAILED"
    now = db.now()
    linked_overdue = any(
        insp["equipment_id"] == equipment["id"] and insp["status"] == "OVERDUE"
        for insp in db.inspections.values()
    )
    due = equipment["next_due_at"]
    if linked_overdue or (due is not None and now > due):
        return "OVERDUE"
    if due is not None and due - now <= timedelta(days=DUE_SOON_DAYS):
        return "DUE_SOON"
    return "CURRENT"


def system_has_failed_equipment(system_id):
    return any(
        eq["system_id"] == system_id and integrity_status(eq) == "FAILED"
        for eq in db.equipment.values()
    )


# ---------------------------------------------------------------------------
# TrainingRecord.currency
# ---------------------------------------------------------------------------
def training_currency(record):
    now = db.now()
    expires = record["expires_at"]
    if now >= expires:
        return "EXPIRED"
    if expires - now <= timedelta(days=EXPIRING_SOON_DAYS):
        return "EXPIRING_SOON"
    return "CURRENT"


def has_current_ammonia_training(employee_id):
    for record in db.training_records.values():
        if record["employee_id"] != employee_id:
            continue
        if record["topic"] != "AMMONIA_OPERATOR":
            continue
        if training_currency(record) != "EXPIRED":
            return True
    return False


# ---------------------------------------------------------------------------
# floating_head_pressure_target
# ---------------------------------------------------------------------------
def _saturation_psig(temp_f):
    """Piecewise-linear interpolation of the ammonia saturation table; the end
    segments extend linearly outside the tabulated range."""
    points = sorted(AMMONIA_SAT_PSIG_TABLE.items())
    (t0, p0), (t1, p1) = points[0], points[1]
    for i in range(len(points) - 1):
        lo, hi = points[i], points[i + 1]
        if lo[0] <= temp_f <= hi[0]:
            t0, p0, t1, p1 = lo[0], lo[1], hi[0], hi[1]
            break
    else:
        if temp_f > points[-1][0]:
            (t0, p0), (t1, p1) = points[-2], points[-1]
    fraction = (temp_f - Decimal(t0)) / Decimal(t1 - t0)
    return p0 + fraction * (p1 - p0)


def head_pressure_target(system, wet_bulb_f, condenser_load_pct):
    if condenser_load_pct >= 90:
        derate = Decimal("5.0")
    elif condenser_load_pct >= 75:
        derate = Decimal("2.5")
    else:
        derate = Decimal("0.0")
    effective_approach_f = system["condenser_approach_f"] + derate
    condensing_temp_f = wet_bulb_f + effective_approach_f
    raw_psig = round_tenth(_saturation_psig(condensing_temp_f))
    if not system["float_head_enabled"]:
        return {
            "effective_approach_f": effective_approach_f,
            "condensing_temp_f": condensing_temp_f,
            "raw_psig": raw_psig,
            "target_psig": system["max_head_psig"],
            "variant": "fixed_design",
        }
    target = min(max(raw_psig, system["min_head_psig"]), system["max_head_psig"])
    return {
        "effective_approach_f": effective_approach_f,
        "condensing_temp_f": condensing_temp_f,
        "raw_psig": raw_psig,
        "target_psig": target,
        "variant": "floating",
    }


# ---------------------------------------------------------------------------
# notification_deadline
# ---------------------------------------------------------------------------
def notification_required(final_release_lbs):
    return final_release_lbs >= RQ_LBS  # exactly 100.0 qualifies (>=)


def incident_severity_for_release(final_release_lbs):
    return "REPORTABLE" if final_release_lbs >= RQ_LBS else "RECORDABLE"


# ---------------------------------------------------------------------------
# drill_gap_check / permit window overlap
# ---------------------------------------------------------------------------
def drill_gap_conflicts(facility_id, start, end):
    """Buffer semantics: conflict unless the new drill begins at least 24h
    after the existing drill's end, or ends at least 24h before its start;
    exactly 24h of separation is allowed (>= / <=)."""
    for drill in db.drill_events.values():
        if drill["facility_id"] != facility_id:
            continue
        if drill["status"] not in ("PLANNED", "CONDUCTED"):
            continue
        if start >= drill["scheduled_end_at"] + DRILL_QUIET_GAP:
            continue
        if end <= drill["scheduled_start_at"] - DRILL_QUIET_GAP:
            continue
        return True
    return False


def permit_window_conflicts(system_id, valid_from, valid_until, exclude_id=None):
    """Half-open [valid_from, valid_until) overlap against permits standing
    REQUESTED / ISSUED / IN_PROGRESS on the same system; touching endpoints
    do not overlap."""
    for permit in db.hot_work_permits.values():
        if permit["system_id"] != system_id:
            continue
        if permit["id"] == exclude_id:
            continue
        if permit["status"] not in ACTIVE_PERMIT_STATES:
            continue
        if valid_from < permit["valid_until"] and valid_until > permit["valid_from"]:
            return True
    return False
