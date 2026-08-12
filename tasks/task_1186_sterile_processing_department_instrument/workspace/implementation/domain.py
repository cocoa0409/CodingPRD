"""Domain services: lazy sweeps, cascades, competency scoring, calculations.

Implements SCAFFOLD.yaml calculation rules:
  - tray_availability_projection (in api_templates.py, uses projected_release_at)
  - sterility_expiry_assignment (SHELF_HOURS by packaging_type)
  - repair_vs_replace_recommendation (decision ladder, exact decimals)
  - load_reprocessing_chargeback (per-tray round-half-up, then sum)
  - iuss_rolling_window_rate (168h window; supervisor gate at prospective >= 4)
  - technician_competency_score (rolling 90d decay + lifetime variants)
  - loaner_intake_deadline (24h / 48h tiered lead)
"""
from datetime import timedelta
from decimal import Decimal

import store
from common import D, logical_now, rhu_int

# --- calculation constants (SCAFFOLD Table 3) ---
SHELF_HOURS = {"WRAPPED": 720, "RIGID_CONTAINER": 2160}
BI_INCUBATION_HOURS = 3
TURNOVER_BUFFER = timedelta(minutes=45)
BASE_FEE_CENTS = 1000
METHOD_MULTIPLIER = {
    "STEAM_GRAVITY": Decimal("1.0"),
    "STEAM_PREVAC": Decimal("1.2375"),
    "LOW_TEMP_H2O2": Decimal("1.7625"),
}
IUSS_WINDOW = timedelta(hours=168)
CASE_WINDOW = timedelta(hours=720)
SUPERVISOR_THRESHOLD = 4
H2O2_COMPETENCY_GATE = Decimal("70")
FAIL_VERIFY_PTS = 2
CYCLE_FAIL_PTS = 8
MAX_REPAIRS = 3
REPAIR_COUNT_FACTOR = Decimal("0.25")
CRITICAL_REMAINING_CYCLES = 10
CRITICAL_FACTOR = Decimal("1.5")
REPLACE_RATIO_LIMIT = Decimal("0.6")
STANDARD_LEAD_HOURS = 24
BULK_LEAD_HOURS = 48
BULK_THRESHOLD = 10

STERILIZER_METHODS = ("STEAM_GRAVITY", "STEAM_PREVAC", "LOW_TEMP_H2O2")


# --------------------------------------------------------------------------
# Lazy sweeps (PRD section 2.4)
# --------------------------------------------------------------------------


def sweep_tray(tray):
    """STERILE -> AWAITING_DECONTAMINATION when now >= sterility_expires_at."""
    now = logical_now()
    if (tray["status"] == "STERILE"
            and tray["sterility_expires_at"] is not None
            and now >= tray["sterility_expires_at"]):
        tray["status"] = "AWAITING_DECONTAMINATION"
        tray["sterility_expires_at"] = None
        store.touch(tray)
        for res in list(store.TRAY_RESERVATIONS.values()):
            if res["tray_id"] == tray["id"] and res["status"] == "RESERVED":
                res["status"] = "RELEASED"
                store.touch(res)
                recompute_case_after_release(res["case_id"])


def sweep_all_trays():
    for tray in list(store.TRAYS.values()):
        sweep_tray(tray)


def sweep_technician(tech):
    """ACTIVE -> CERTIFICATION_EXPIRED only when now is strictly past expiry."""
    if (tech["status"] == "ACTIVE"
            and logical_now() > tech["certification_expires_at"]):
        tech["status"] = "CERTIFICATION_EXPIRED"
        store.touch(tech)


def sweep_all_technicians():
    for tech in list(store.TECHNICIANS.values()):
        sweep_technician(tech)


def recompute_case_after_release(case_id):
    """0 RESERVED remaining and case TRAYS_RESERVED/AT_RISK -> SCHEDULED."""
    case = store.OR_CASES.get(case_id)
    if case is None or case["status"] not in ("TRAYS_RESERVED", "AT_RISK"):
        return
    remaining = [r for r in store.TRAY_RESERVATIONS.values()
                 if r["case_id"] == case_id and r["status"] == "RESERVED"]
    if len(remaining) == 0:
        case["status"] = "SCHEDULED"
        store.touch(case)


# --------------------------------------------------------------------------
# Competency scoring (technician_competency_score)
# --------------------------------------------------------------------------


def add_competency_event(technician_id, points):
    store.COMPETENCY_EVENTS.append({
        "technician_id": technician_id,
        "points": points,
        "at": logical_now(),
    })


def competency_scores(technician_id):
    """Return (rolling_90d, lifetime) scores; each max(0, 100 - weighted sum)."""
    now = logical_now()
    rolling = Decimal(100)
    lifetime = Decimal(100)
    for ev in store.COMPETENCY_EVENTS:
        if ev["technician_id"] != technician_id:
            continue
        lifetime -= ev["points"]
        age = now - ev["at"]
        if age <= timedelta(days=90):
            if age <= timedelta(days=30):
                weight = Decimal("1")
            elif age <= timedelta(days=60):
                weight = Decimal("0.5")
            else:
                weight = Decimal("0.25")
            rolling -= weight * ev["points"]
    if rolling < 0:
        rolling = Decimal(0)
    if lifetime < 0:
        lifetime = Decimal(0)
    return rolling, lifetime


def score_number(d):
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# --------------------------------------------------------------------------
# Repair vs replace (repair_vs_replace_recommendation)
# --------------------------------------------------------------------------


def repair_recommendation(instrument, actual_cost_cents):
    if instrument["usage_cycles"] >= instrument["max_cycles"]:
        return "CONDEMNED"
    if instrument["repair_count"] >= MAX_REPAIRS:
        return "CONDEMNED"
    base = D(actual_cost_cents) / D(instrument["replacement_cost_cents"])
    adjusted = base * (Decimal(1) + REPAIR_COUNT_FACTOR * instrument["repair_count"])
    remaining = instrument["max_cycles"] - instrument["usage_cycles"]
    if (instrument["criticality"] == "CRITICAL"
            and remaining <= CRITICAL_REMAINING_CYCLES):
        adjusted = adjusted * CRITICAL_FACTOR
    return "CONDEMNED" if adjusted >= REPLACE_RATIO_LIMIT else "FIXED"


# --------------------------------------------------------------------------
# Tray / load cascades
# --------------------------------------------------------------------------


def demote_tray_for_instrument_repair(instrument):
    """Send-for-repair / retire cascade: owning tray demotes to IN_ASSEMBLY."""
    tray_id = instrument["assigned_tray_id"]
    if tray_id is None:
        return
    tray = store.TRAYS.get(tray_id)
    if tray is not None and tray["status"] in ("IN_ASSEMBLY", "ASSEMBLED", "IN_LOAD"):
        if tray["status"] == "IN_LOAD":
            load = store.STERILIZATION_LOADS.get(tray["current_load_id"])
            if load is not None and tray_id in load["member_tray_ids"]:
                load["member_tray_ids"].remove(tray_id)
                store.touch(load)
            tray["current_load_id"] = None
        if tray["status"] != "IN_ASSEMBLY":
            tray["status"] = "IN_ASSEMBLY"
            store.touch(tray)
    instrument["assigned_tray_id"] = None


def release_member_trays(load, to_status):
    """fail-cycle / abort / failed-BI: member trays leave the load."""
    for tray_id in list(load["member_tray_ids"]):
        tray = store.TRAYS.get(tray_id)
        if tray is not None and tray["status"] == "IN_LOAD":
            tray["status"] = to_status
            tray["current_load_id"] = None
            store.touch(tray)
        load["member_tray_ids"].remove(tray_id)


def recall_load(load, reason):
    """RELEASED -> RECALLED with the full quarantine/cancel/at-risk cascade."""
    load["status"] = "RECALLED"
    load["recall_reason"] = reason
    load["recalled_at"] = logical_now()
    store.touch(load)
    for tray_id in list(load["member_tray_ids"]):
        tray = store.TRAYS.get(tray_id)
        if tray is None or tray["status"] != "STERILE":
            continue
        tray["status"] = "QUARANTINED"
        tray["quarantine_reason"] = reason
        tray["sterility_expires_at"] = None
        store.touch(tray)
        for res in list(store.TRAY_RESERVATIONS.values()):
            if res["tray_id"] == tray_id and res["status"] == "RESERVED":
                res["status"] = "CANCELLED"
                store.touch(res)
                case = store.OR_CASES.get(res["case_id"])
                if case is not None and case["status"] == "TRAYS_RESERVED":
                    case["status"] = "AT_RISK"
                    store.touch(case)


# --------------------------------------------------------------------------
# Load helpers
# --------------------------------------------------------------------------


def tray_count(load):
    """Computed: number of member trays currently IN_LOAD on this load."""
    return sum(1 for t in store.TRAYS.values()
               if t["current_load_id"] == load["id"])


def chargeback_cents(sterilizer, member_count):
    """Per-tray round-half-up FIRST, then integer sum (pinned order)."""
    mult = METHOD_MULTIPLIER[sterilizer["method"]]
    total = 0
    for _ in range(member_count):
        total += rhu_int(BASE_FEE_CENTS * mult)
    return total


def projected_release_at(load, sterilizer):
    base = None
    if load["status"] == "LOADING":
        base = load["planned_start_at"] + timedelta(minutes=sterilizer["cycle_minutes"])
    elif load["status"] == "RUNNING":
        base = load["started_at"] + timedelta(minutes=sterilizer["cycle_minutes"])
    elif load["status"] == "COMPLETED":
        base = load["completed_at"]
    if base is None:
        return None
    return base + timedelta(hours=BI_INCUBATION_HOURS)


# --------------------------------------------------------------------------
# IUSS rolling window
# --------------------------------------------------------------------------


def iuss_count_7d():
    """Exceptions with logged_at in (now - 168h, now] — start exclusive."""
    now = logical_now()
    start = now - IUSS_WINDOW
    return sum(1 for e in store.IUSS_EXCEPTIONS.values()
               if e["logged_at"] > start and e["logged_at"] <= now)
