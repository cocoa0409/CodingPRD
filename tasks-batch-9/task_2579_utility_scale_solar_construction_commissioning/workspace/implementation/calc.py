"""Domain constants, derived-field rollups, cascades and calculations."""

from datetime import timedelta
from decimal import Decimal

import clock
import store
from clock import dec, money, num, rhu

# --- civil / stormwater ---------------------------------------------------
RAIN_TRIGGER_INCHES = Decimal("0.25")
RAIN_BLACKOUT_HOURS = 48
MIN_COMPACTION_PCT = Decimal("95.0")

# --- laydown yard / deliveries -------------------------------------------
MAX_DAMAGE_RATIO = Decimal("0.05")

# --- outage windows -------------------------------------------------------
OUTAGE_SWITCHING_BUFFER_MINUTES = 120

# --- piles ----------------------------------------------------------------
REFUSAL_MIN_EMBEDMENT_RATIO = Decimal("0.90")
PLUMB_TOLERANCE_MM = Decimal("12.0")
TORQUE_TUBE_TOLERANCE_MM = Decimal("25.0")

# --- string testing -------------------------------------------------------
IR_MIN_MOHM = Decimal("40.0")
MODULE_VOC_STC_V = Decimal("49.50")
VOC_TEMP_COEFF_PER_C = Decimal("-0.0028")
STC_TEMP_C = Decimal("25")
VOC_TOLERANCE_PCT = Decimal("0.03")

# --- commissioning --------------------------------------------------------
MIN_IRRADIANCE_W_M2 = Decimal("600")
MAX_WIND_M_S = Decimal("8.0")
AMBIENT_MIN_C = Decimal("-10")
AMBIENT_MAX_C = Decimal("45")
G_REF_W_M2 = Decimal("1000")
CELL_TEMP_RISE_PER_W = Decimal("0.025")
PMAX_TEMP_COEFF_PER_C = Decimal("-0.0035")
CAPACITY_PASS_RATIO = Decimal("0.98")

# --- labor ----------------------------------------------------------------
DEFAULT_APPRENTICE_MIN_PCT = Decimal("15.00")
PW_LD_RATE = Decimal("0.20")

# --- commercial -----------------------------------------------------------
CHANGE_ORDER_CAP_PCT = Decimal("0.20")
PUNCH_HOLDBACK_MULTIPLIER = Decimal("1.5")

OPEN_PUNCH_STATES = ("OPEN", "CLOSURE_SUBMITTED")
LIVE_DELIVERY_STATES = ("RESERVED", "ARRIVED", "ACCEPTED")


# =========================================================================
# Yard zone pallet ledger
# =========================================================================

def recompute_yard_zone(zone):
    reserved = 0
    for delivery in store.deliveries.values():
        if delivery["yard_zone_id"] == zone["id"] and delivery["status"] in LIVE_DELIVERY_STATES:
            reserved += delivery["pallets"]
    zone["reserved_pallets"] = reserved
    zone["available_pallets"] = zone["pallet_capacity"] - reserved


def laydown_occupied(zone, window_start, window_end, exclude_id=None):
    """Half-open pairwise overlap with the candidate; aggregate capacity."""
    occupied = 0
    for delivery in store.deliveries.values():
        if delivery["yard_zone_id"] != zone["id"]:
            continue
        if delivery["id"] == exclude_id:
            continue
        if delivery["status"] not in LIVE_DELIVERY_STATES:
            continue
        if delivery["laydown_window_start"] < window_end and delivery["laydown_window_end"] > window_start:
            occupied += delivery["pallets"]
    return occupied


# =========================================================================
# Interval conventions
# =========================================================================

def outage_conflict(substation_id, start_at, end_at, exclude_id=None):
    """Closed intervals padded by the switching buffer on BOTH sides."""
    buffer_delta = timedelta(minutes=OUTAGE_SWITCHING_BUFFER_MINUTES)
    for window in store.outage_windows.values():
        if window["substation_id"] != substation_id or window["id"] == exclude_id:
            continue
        if window["status"] not in ("REQUESTED", "APPROVED", "EXECUTED"):
            continue
        if start_at <= window["end_at"] + buffer_delta and end_at + buffer_delta >= window["start_at"]:
            return True
    return False


def earthwork_conflict(area, start_at, end_at):
    """Closed intervals, exclusive crew occupancy, no buffer."""
    for record in area["earthwork_windows"]:
        if start_at <= record["work_end_at"] and end_at >= record["work_start_at"]:
            return True
    return False


def recompute_area_acreage(area):
    total = Decimal("0")
    for record in area["earthwork_windows"]:
        total += dec(record["acreage_disturbed_delta"])
    area["disturbed_acreage_current"] = num(total, 2)


# =========================================================================
# Pile disposition and string testing
# =========================================================================

def pile_disposition(refusal, actual_embedment_mm, plumb_deviation_mm, design_embedment_mm):
    floor_mm = dec(design_embedment_mm) * REFUSAL_MIN_EMBEDMENT_RATIO
    actual = dec(actual_embedment_mm)
    plumb_ok = dec(plumb_deviation_mm) <= PLUMB_TOLERANCE_MM
    if refusal:
        if actual < floor_mm:
            return "REFUSED"
        return "ACCEPTED" if plumb_ok else "OUT_OF_TOLERANCE"
    if actual >= dec(design_embedment_mm) and plumb_ok:
        return "ACCEPTED"
    return "OUT_OF_TOLERANCE"


def remediation_clears(actual_embedment_mm, plumb_deviation_mm, design_embedment_mm):
    floor_mm = dec(design_embedment_mm) * REFUSAL_MIN_EMBEDMENT_RATIO
    return dec(actual_embedment_mm) >= floor_mm and dec(plumb_deviation_mm) <= PLUMB_TOLERANCE_MM


def expected_voc(modules_in_series, ambient_c):
    raw = dec(modules_in_series) * MODULE_VOC_STC_V * (
        Decimal("1") + VOC_TEMP_COEFF_PER_C * (dec(ambient_c) - STC_TEMP_C)
    )
    return num(raw, 2)


def string_test_disposition(modules_in_series, insulation, measured_voc, ambient_c, polarity_ok):
    """Pinned order: INSULATION > VOC_DEVIATION > POLARITY."""
    expected = expected_voc(modules_in_series, ambient_c)
    allowed = rhu(dec(expected) * VOC_TOLERANCE_PCT, 4)
    if dec(insulation) < IR_MIN_MOHM:
        return expected, False, "INSULATION"
    if abs(dec(measured_voc) - dec(expected)) > allowed:
        return expected, False, "VOC_DEVIATION"
    if not polarity_ok:
        return expected, False, "POLARITY"
    return expected, True, None


def module_availability(block):
    """(delivered accepted MODULE units, units already installed elsewhere)."""
    project_id = block["project_id"]
    delivered = 0
    for delivery in store.deliveries.values():
        if (
            delivery["project_id"] == project_id
            and delivery["component_type"] == "MODULE"
            and delivery["status"] == "ACCEPTED"
        ):
            delivered += delivery["accepted_unit_qty"] or 0
    installed = 0
    for other in store.blocks.values():
        if other["project_id"] != project_id or other["id"] == block["id"]:
            continue
        if other["modules_installed_qty"] is not None:
            installed += other["modules_installed_qty"]
    return delivered, installed


# =========================================================================
# Block / project readiness rollup
# =========================================================================

BLOCK_DERIVED = (
    "piles_accepted_count",
    "piles_refused_count",
    "circuits_wired_count",
    "circuits_tested_count",
    "circuits_failed_count",
    "mechanical_status",
    "electrical_status",
    "mc_ready",
)

PROJECT_DERIVED = (
    "blocks_total",
    "blocks_mc_ready_count",
    "mc_readiness",
    "open_punch_item_count",
    "open_critical_punch_count",
    "milestone_state",
    "last_milestone_rejection_reason",
    "mc_claimed_by_user_id",
)


def sync_block(block, force=False):
    """Recompute counters and both parallel dimensions. Bumps only on change."""
    before = tuple(block[key] for key in BLOCK_DERIVED)
    piles = [p for p in store.piles.values() if p["block_id"] == block["id"]]
    accepted = sum(1 for p in piles if p["status"] == "ACCEPTED")
    refused = sum(1 for p in piles if p["status"] == "REFUSED")
    circuits = [c for c in store.circuits.values() if c["block_id"] == block["id"]]
    wired = sum(1 for c in circuits if c["status"] in ("WIRED", "TESTED", "FAILED"))
    tested = sum(1 for c in circuits if c["status"] == "TESTED")
    failed = sum(1 for c in circuits if c["status"] == "FAILED")
    block["piles_accepted_count"] = accepted
    block["piles_refused_count"] = refused
    block["circuits_wired_count"] = wired
    block["circuits_tested_count"] = tested
    block["circuits_failed_count"] = failed

    mech = block["mechanical_status"]
    if refused >= 1:
        if mech in ("PLANNED", "PILES_COMPLETE", "MECH_COMPLETE"):
            mech = "HOLD"
    else:
        if mech == "HOLD":
            mech = "PILES_COMPLETE" if accepted >= block["planned_pile_count"] else "PLANNED"
        elif mech == "PLANNED" and accepted >= block["planned_pile_count"]:
            mech = "PILES_COMPLETE"
    block["mechanical_status"] = mech

    planned_strings = block["planned_string_count"]
    elec = block["electrical_status"]
    if failed >= 1:
        if elec in ("WIRED", "TESTED"):
            elec = "REWORK"
    else:
        if elec == "REWORK":
            if tested >= planned_strings:
                elec = "TESTED"
            elif wired >= planned_strings:
                elec = "WIRED"
            else:
                elec = "PLANNED"
        elif elec == "PLANNED" and wired >= planned_strings:
            elec = "WIRED"
        if elec == "WIRED" and tested >= planned_strings:
            elec = "TESTED"
    block["electrical_status"] = elec

    block["mc_ready"] = mech == "MECH_COMPLETE" and elec == "TESTED"
    changed = before != tuple(block[key] for key in BLOCK_DERIVED)
    if changed or force:
        store.touch(block)
    return changed


def sync_project(project, force=False):
    """Recompute project rollups; apply the readiness-loss consequence set."""
    before = tuple(project[key] for key in PROJECT_DERIVED)
    was_ready = project["mc_readiness"] == "READY"
    project_id = project["id"]

    blocks = [b for b in store.blocks.values() if b["project_id"] == project_id]
    areas = [a for a in store.grading_areas.values() if a["project_id"] == project_id]
    project["blocks_total"] = len(blocks)
    project["blocks_mc_ready_count"] = sum(1 for b in blocks if b["mc_ready"])
    ready = (
        len(blocks) >= 1
        and project["blocks_mc_ready_count"] == len(blocks)
        and all(a["status"] == "ACCEPTED" for a in areas)
    )
    project["mc_readiness"] = "READY" if ready else "BLOCKED"

    items = [p for p in store.punch_items.values() if p["project_id"] == project_id]
    project["open_punch_item_count"] = sum(1 for p in items if p["status"] in OPEN_PUNCH_STATES)
    project["open_critical_punch_count"] = sum(
        1 for p in items if p["status"] in OPEN_PUNCH_STATES and p["severity"] == "CRITICAL"
    )

    if was_ready and project["mc_readiness"] == "BLOCKED":
        if project["milestone_state"] == "MC_CLAIMED":
            project["milestone_state"] = "PRECONSTRUCTION"
            project["last_milestone_rejection_reason"] = "AUTO_MC_READINESS_LOST"
            project["mc_claimed_by_user_id"] = None
        for test in store.ordered(
            [t for t in store.tests.values() if t["project_id"] == project_id]
        ):
            if test["status"] in ("SCHEDULED", "IN_PROGRESS"):
                test["status"] = "SUSPENDED"
                test["suspend_reason"] = "MC_READINESS_LOST"
                store.touch(test)

    changed = before != tuple(project[key] for key in PROJECT_DERIVED)
    if changed or force:
        store.touch(project)
    return changed


def cascade_from_block(block):
    """Single ordered pass: block -> project -> readiness consequences."""
    sync_block(block)
    project = store.projects.get(block["project_id"])
    if project is not None:
        sync_project(project)


# =========================================================================
# Commissioning measurement intervals
# =========================================================================

def interval_is_valid(irradiance_w_m2, wind_speed_m_s, ambient_c):
    return (
        dec(irradiance_w_m2) >= MIN_IRRADIANCE_W_M2
        and dec(wind_speed_m_s) <= MAX_WIND_M_S
        and AMBIENT_MIN_C <= dec(ambient_c) <= AMBIENT_MAX_C
    )


def corrected_kw_ac(measured_kw_ac, irradiance_w_m2, ambient_c):
    """Irradiance + cell-temperature translation, rounded to 2 decimals."""
    irradiance = dec(irradiance_w_m2)
    cell_temp = dec(ambient_c) + irradiance * CELL_TEMP_RISE_PER_W
    factor = Decimal("1") + PMAX_TEMP_COEFF_PER_C * (cell_temp - STC_TEMP_C)
    raw = dec(measured_kw_ac) * (G_REF_W_M2 / irradiance) / factor
    return num(raw, 2)


def test_intervals(test):
    return store.ordered([i for i in store.intervals.values() if i["commissioning_test_id"] == test["id"]])


def valid_intervals(test):
    return [i for i in test_intervals(test) if i["is_valid"]]


def capacity_outcome(test, project):
    """(pass_threshold_kw_ac, reported_kw_ac, passed) for a CAPACITY test."""
    threshold = num(dec(project["guaranteed_capacity_kw_ac"]) * CAPACITY_PASS_RATIO, 2)
    rows = valid_intervals(test)
    total = Decimal("0")
    for row in rows:
        if test["correction_variant"] == "AS_MEASURED":
            total += dec(row["measured_kw_ac"])
        else:
            total += dec(row["corrected_kw_ac"])
    reported = num(total / Decimal(len(rows)), 2)
    return threshold, reported, dec(reported) >= dec(threshold)


def performance_ratio_outcome(test, project):
    """(reported_performance_ratio, passed) for a PERFORMANCE_RATIO test."""
    rows = valid_intervals(test)
    numerator = Decimal("0")
    denominator = Decimal("0")
    dc_capacity = dec(project["dc_capacity_kw"])
    for row in rows:
        numerator += dec(row["measured_kw_ac"])
        denominator += dc_capacity * dec(row["irradiance_w_m2"]) / G_REF_W_M2
    reported = num(numerator / denominator, 4)
    return reported, dec(reported) >= dec(project["guaranteed_performance_ratio"])


def passed_test_exists(project_id, test_type):
    for test in store.tests.values():
        if (
            test["project_id"] == project_id
            and test["test_type"] == test_type
            and test["status"] == "PASSED"
        ):
            return True
    return False


# =========================================================================
# Payroll ledgers
# =========================================================================

def recompute_week_ledger(week):
    posted = [
        e
        for e in store.labor_entries.values()
        if e["payroll_week_id"] == week["id"] and e["status"] == "POSTED"
    ]
    total = Decimal("0")
    apprentice = Decimal("0")
    journey = Decimal("0")
    for entry in posted:
        hours = dec(entry["hours"])
        total += hours
        if entry["is_apprentice"]:
            apprentice += hours
        else:
            journey += hours
    week["total_hours"] = num(total, 2)
    week["apprentice_hours"] = num(apprentice, 2)
    week["journeyworker_hours"] = num(journey, 2)
    week["entry_count"] = len(posted)
    if total > 0:
        week["apprentice_pct"] = num(apprentice / total * Decimal("100"), 2)
    else:
        week["apprentice_pct"] = 0.0


def recompute_project_hours(project):
    weeks = [w for w in store.payroll_weeks.values() if w["project_id"] == project["id"]]
    total = Decimal("0")
    apprentice = Decimal("0")
    for week in weeks:
        total += dec(week["total_hours"])
        apprentice += dec(week["apprentice_hours"])
    project["total_labor_hours"] = num(total, 2)
    project["apprentice_labor_hours"] = num(apprentice, 2)


def project_posted_entries(project_id):
    week_ids = {
        w["id"] for w in store.payroll_weeks.values() if w["project_id"] == project_id
    }
    return [
        e
        for e in store.labor_entries.values()
        if e["payroll_week_id"] in week_ids and e["status"] == "POSTED"
    ]


def apprenticeship_pct(project, method):
    """PROJECT_AGGREGATE pools all posted hours; WEEKLY_WORST_CASE takes the min."""
    project_id = project["id"]
    if method == "WEEKLY_WORST_CASE":
        worst = None
        for week in store.payroll_weeks.values():
            if week["project_id"] != project_id:
                continue
            if dec(week["total_hours"]) <= 0:
                continue
            pct = dec(
                num(dec(week["apprentice_hours"]) / dec(week["total_hours"]) * Decimal("100"), 2)
            )
            if worst is None or pct < worst:
                worst = pct
        return 0.0 if worst is None else float(worst)
    total = Decimal("0")
    apprentice = Decimal("0")
    for entry in project_posted_entries(project_id):
        hours = dec(entry["hours"])
        total += hours
        if entry["is_apprentice"]:
            apprentice += hours
    if total <= 0:
        return 0.0
    return num(apprentice / total * Decimal("100"), 2)


def entry_shortfall(paid_rate_cents, fringe_rate_cents, prevailing_rate_cents):
    shortfall = prevailing_rate_cents - (paid_rate_cents + fringe_rate_cents)
    return shortfall if shortfall > 0 else 0


def entry_restitution(shortfall_cents_per_hour, hours):
    """Rounded PER ENTRY to whole cents before any summation."""
    return money(dec(shortfall_cents_per_hour) * dec(hours))


def wage_restitution(project):
    """Sum of the per-entry rounded figures; then the 20% PW penalty."""
    owed = 0
    for entry in project_posted_entries(project["id"]):
        owed += entry["restitution_cents"]
    penalty = money(dec(owed) * PW_LD_RATE)
    return owed, penalty


# =========================================================================
# Commercial waterfall
# =========================================================================

def change_order_cap(project):
    return money(dec(project["contract_value_cents"]) * CHANGE_ORDER_CAP_PCT)


def adjusted_contract(project):
    return project["contract_value_cents"] + project["approved_change_order_cents"]


def ld_cap(project):
    return money(dec(adjusted_contract(project)) * dec(project["ld_cap_pct"]))


def punch_holdback(project, retainage_held_cents):
    exposure = Decimal("0")
    for item in store.punch_items.values():
        if item["project_id"] != project["id"]:
            continue
        if item["status"] not in OPEN_PUNCH_STATES:
            continue
        exposure += dec(item["estimated_cost_cents"])
    holdback = money(exposure * PUNCH_HOLDBACK_MULTIPLIER)
    return min(holdback, retainage_held_cents)


def substantial_completion_settlement(project):
    """The seven pinned waterfall steps, in order."""
    adjusted = adjusted_contract(project)
    cap = money(dec(adjusted) * dec(project["ld_cap_pct"]))
    today = clock.now().date()
    delay_days = (today - project["sc_deadline_date"]).days
    if delay_days < 0:
        delay_days = 0
    assessed = min(delay_days * project["ld_per_day_cents"], cap)
    retainage_held = money(dec(adjusted) * dec(project["retainage_pct"]))
    holdback = punch_holdback(project, retainage_held)
    payment_due = adjusted - retainage_held - assessed - holdback
    if payment_due < 0:
        payment_due = 0
    return {
        "adjusted_contract_cents": adjusted,
        "ld_cap_cents": cap,
        "ld_delay_days": delay_days,
        "ld_assessed_cents": assessed,
        "retainage_held_cents": retainage_held,
        "punchlist_holdback_cents": holdback,
        "sc_payment_due_cents": payment_due,
    }
