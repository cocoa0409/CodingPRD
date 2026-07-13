"""Domain calculations: rounding, coverage, reimbursement, rollups, currency."""
from decimal import Decimal, ROUND_HALF_UP

import store

# Constants (PRD §2.9, §3.3, §3.8)
MILEAGE_TIER1_LIMIT_MI = 50
MILEAGE_RATE_TIER1_CPM = 65
MILEAGE_RATE_TIER2_CPM = 40
MEAL_PER_DIEM_CENTS = 1500
MEAL_MAX_COUNT = 6
LODGING_RATE_CENTS = 9000
COVERAGE_RATE_SQKM_PER_HOUR = Decimal("0.5")
MI_PER_KM = Decimal("0.621371")
MEMBER_REST_BUFFER_MIN = 60


def _d(value):
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places. Returns a Decimal."""
    q = Decimal(1).scaleb(-places)  # 10 ** -places
    return _d(value).quantize(q, rounding=ROUND_HALF_UP)


# --- Certification currency (§3.2) --------------------------------------
def cert_status(cert):
    expires = store.parse_dt(cert["expires_date"])
    return "EXPIRED" if store.get_clock() >= expires else "VALID"


# --- Reimbursement (§3.8) ------------------------------------------------
def reimbursement_cents(mileage, meal_count, lodging_nights):
    mileage_reimb = (
        min(mileage, MILEAGE_TIER1_LIMIT_MI) * MILEAGE_RATE_TIER1_CPM
        + max(mileage - MILEAGE_TIER1_LIMIT_MI, 0) * MILEAGE_RATE_TIER2_CPM
    )
    meal_reimb = min(meal_count, MEAL_MAX_COUNT) * MEAL_PER_DIEM_CENTS
    lodging_reimb = lodging_nights * LODGING_RATE_CENTS
    return int(mileage_reimb + meal_reimb + lodging_reimb)


def reconciled_mileage_miles(member_id, incident_id):
    """Sum GroundTrack.distance_km for the member on tasks of the incident,
    convert km->mi, round half up to whole miles."""
    incident_task_ids = {
        t["id"] for t in store.tasks.values() if t.get("incident_id") == incident_id
    }
    total_km = Decimal(0)
    for gt in store.ground_tracks.values():
        if gt.get("member_id") == member_id and gt.get("task_id") in incident_task_ids:
            total_km += _d(gt["distance_km"])
    miles = rhu(total_km * MI_PER_KM, 0)
    return int(miles)


# --- Task coverage (§3.3) ------------------------------------------------
def coverage_estimate_pct(task):
    area = _d(task["segment_area_sqkm"])
    swept = _d(task["planned_searcher_hours"]) * COVERAGE_RATE_SQKM_PER_HOUR
    ratio = swept / area if area != 0 else Decimal(0)
    capped = min(Decimal(1), ratio)
    pct = rhu(capped * 100, 2)
    return float(pct)


def coverage_actual_pct(task):
    area = _d(task["segment_area_sqkm"])
    total_frac = Decimal(0)
    for gt in store.ground_tracks.values():
        if gt.get("task_id") == task["id"]:
            frac = rhu(_d(gt["coverage_area_sqkm"]) / area, 4) if area != 0 else Decimal(0)
            total_frac += frac
    capped = min(Decimal(1), total_frac)
    pct = rhu(capped * 100, 2)
    return float(pct)


# --- Incident effort rollups (§3.1) --------------------------------------
def incident_rollups(incident_id):
    incident_task_ids = {
        t["id"] for t in store.tasks.values() if t.get("incident_id") == incident_id
    }
    total_min = 0
    total_km = Decimal(0)
    for gt in store.ground_tracks.values():
        if gt.get("task_id") in incident_task_ids:
            total_min += gt["duration_min"]
            total_km += _d(gt["distance_km"])
    total_logged_hours = float(rhu(_d(total_min) / Decimal(60), 2))
    total_mileage_miles = int(rhu(total_km * MI_PER_KM, 0))
    active_statuses = {"DRAFT", "ASSIGNED", "IN_PROGRESS", "SUSPENDED"}
    active_task_count = sum(
        1
        for t in store.tasks.values()
        if t.get("incident_id") == incident_id and t["status"] in active_statuses
    )
    return {
        "total_logged_hours": total_logged_hours,
        "total_mileage_miles": total_mileage_miles,
        "active_task_count": active_task_count,
    }


# --- Resource status (§3.5) ----------------------------------------------
def resource_status(resource):
    if resource.get("out_of_service"):
        return "OUT_OF_SERVICE"
    return "ASSIGNED" if resource.get("active_assignment_count", 0) > 0 else "AVAILABLE"
