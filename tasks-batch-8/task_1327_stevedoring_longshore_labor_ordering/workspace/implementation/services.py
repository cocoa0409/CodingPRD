"""Business logic: derived fields, cascades, selection algorithms, calculations."""
import math
from decimal import Decimal, ROUND_HALF_UP

import errors
from db import STORE, all_of, get, new_resource, save, touch

# ---------------------------------------------------------------------------
# Constants (PRD §3)
# ---------------------------------------------------------------------------
BONUS_PER_EXCESS_MOVE_CENTS = 1500
OT_START_MINUTES = 480
DT_START_MINUTES = 720
MEAL_THRESHOLD_MINUTES = 300
MEAL_PENALTY_MINUTES = 60
PERIOD_MULTIPLIER = {"DAY": Decimal("1.00"), "NIGHT": Decimal("1.10"), "GRAVEYARD": Decimal("1.20")}

PROVISIONAL_SHARE_PCT = Decimal("0.50")
STEVEDORE_CAP_CENTS = 25000000
DEDUCTIBLE_CENTS = 50000

BUFFER_MINUTES = 30

TIER1_MOVES = 500
TIER1_RATE_CENTS = 4500
TIER2_MOVES = 1000
TIER2_RATE_CENTS = 4200
TIER3_RATE_CENTS = 3900
TON_RATE_CENTS = 620
MANHOUR_RATE_CENTS = 6500
EQUIP_RATE_CENTS = {"SHIP_CRANE": 25000, "RTG": 12000, "FORKLIFT": 6000, "TRACTOR": 5500}
DOWN_BILLING_FACTOR = Decimal("0.5")
STOPPAGE_CREDIT_PER_SUSPENSION_CENTS = 9000
DISCOUNT_TIER1_SUBTOTAL_CENTS = 3000000
DISCOUNT_TIER2_SUBTOTAL_CENTS = 6000000
DISCOUNT_TIER1_RATE = Decimal("0.05")
DISCOUNT_TIER2_RATE = Decimal("0.08")

GANG_TERMINAL = ("COMPLETED", "CANCELLED")
ASSIGNMENT_NONTERMINAL = ("OFFERED", "CHECKED_IN", "WORKING")


def rhu(dec):
    """Round half up to integer cents."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _num(v):
    """Emit an integral Decimal as int, else float."""
    d = Decimal(str(v))
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Graph traversal helpers
# ---------------------------------------------------------------------------

def gang_shift(gang):
    return get("shift_windows", gang["shift_window_id"])


def shift_vessel(shift):
    return get("vessel_calls", shift["vessel_call_id"])


def gang_vessel(gang):
    return shift_vessel(gang_shift(gang))


def gangs_of_shift(shift_id):
    return [g for g in all_of("gang_orders") if g["shift_window_id"] == shift_id]


def shifts_of_vessel(vessel_id):
    return [s for s in all_of("shift_windows") if s["vessel_call_id"] == vessel_id]


def gangs_of_vessel(vessel_id):
    shift_ids = {s["id"] for s in shifts_of_vessel(vessel_id)}
    return [g for g in all_of("gang_orders") if g["shift_window_id"] in shift_ids]


def assignments_of_gang(gang_id):
    return [a for a in all_of("dispatch_assignments") if a["gang_order_id"] == gang_id]


def eas_of_gang(gang_id):
    return [e for e in all_of("equipment_assignments") if e["gang_order_id"] == gang_id]


def eas_of_unit(unit_id):
    return [e for e in all_of("equipment_assignments") if e["equipment_unit_id"] == unit_id]


def window_minutes(ea):
    s = ea["_ws"]
    e = ea["_we"]
    return Decimal(str((e - s).total_seconds())) / Decimal(60)


# ---------------------------------------------------------------------------
# Seniority (calculation seniority_rank)
# ---------------------------------------------------------------------------

def recompute_seniority(classification=None):
    """1-based rank within classification: registered_on ASC, created_at ASC.
    All workers regardless of status; rank retained while SUSPENDED."""
    classes = {classification} if classification else {w["classification"] for w in all_of("workers")}
    for c in classes:
        ws = [w for w in all_of("workers") if w["classification"] == c]
        ws.sort(key=lambda w: (w["registered_on"], w["_seq"]))
        for i, w in enumerate(ws, 1):
            if w.get("seniority_rank") != i:
                w["seniority_rank"] = i
                touch(w)


# ---------------------------------------------------------------------------
# Gang order derived fields (calculation filled_headcount / manning)
# ---------------------------------------------------------------------------

def recompute_manning(gang, _touch=True):
    filled = sum(1 for a in assignments_of_gang(gang["id"]) if a["status"] in ("CHECKED_IN", "WORKING"))
    offered = sum(1 for a in assignments_of_gang(gang["id"]) if a["status"] == "OFFERED")
    changed = filled != gang["filled_headcount"] or offered != gang["offered_count"]
    gang["filled_headcount"] = filled
    gang["offered_count"] = offered
    if gang["status"] in ("DISPATCHING", "SHORT_MANNED", "MANNED"):
        if filled >= gang["required_headcount"]:
            new = "MANNED"
        elif filled + offered >= gang["required_headcount"]:
            new = "DISPATCHING"
        elif gang.get("_pool_exhausted"):
            new = "SHORT_MANNED"
        else:
            new = "DISPATCHING"
        if new != gang["status"]:
            gang["status"] = new
            changed = True
    if changed and _touch:
        touch(gang)
    return changed


def derive_manning_status(gang):
    """Pure derivation used by the dispatch batch before its single version bump."""
    filled = gang["filled_headcount"]
    offered = gang["offered_count"]
    if filled >= gang["required_headcount"]:
        return "MANNED"
    if filled + offered >= gang["required_headcount"]:
        return "DISPATCHING"
    if gang.get("_pool_exhausted"):
        return "SHORT_MANNED"
    return "DISPATCHING"


def recompute_equipment_ok(gang, _touch=True):
    count = 0
    for ea in eas_of_gang(gang["id"]):
        if ea["status"] in ("RESERVED", "ACTIVE"):
            unit = get("equipment_units", ea["equipment_unit_id"])
            if unit and unit["equipment_type"] == gang["required_equipment_type"]:
                count += 1
    ok = count >= gang["required_equipment_count"]
    if ok != gang["assigned_equipment_ok"]:
        gang["assigned_equipment_ok"] = ok
        if _touch:
            touch(gang)


# ---------------------------------------------------------------------------
# Vessel derived fields
# ---------------------------------------------------------------------------

def recompute_vessel_actuals(vessel):
    gang_ids = {g["id"] for g in gangs_of_vessel(vessel["id"])}
    moves = 0
    tons = Decimal("0")
    for r in all_of("move_records"):
        if r["status"] == "RECORDED" and r["gang_order_id"] in gang_ids:
            moves += r["moves_count"]
            tons += Decimal(str(r["tons_lifted"]))
    tons_val = _num(tons)
    if moves != vessel["actual_moves"] or tons_val != vessel["actual_tons"]:
        vessel["actual_moves"] = moves
        vessel["actual_tons"] = tons_val
        touch(vessel)


# ---------------------------------------------------------------------------
# Safety posture (calculation work_posture_derivation) + stoppage cascade
# ---------------------------------------------------------------------------

def compute_posture(vessel):
    open_incidents = [
        i for i in all_of("safety_incidents")
        if i["vessel_call_id"] == vessel["id"] and i["status"] == "REPORTED"
    ]
    for i in open_incidents:
        if i["severity"] == "CRITICAL" or (i["severity"] == "MAJOR" and i["scope"] in ("VESSEL", "TERMINAL")):
            return "FULL_STOPPAGE"
    for i in open_incidents:
        if i["severity"] == "MAJOR" and i["scope"] == "GANG":
            return "PARTIAL_STOPPAGE"
    return "NORMAL"


def suspend_gang(gang):
    """WORKING -> SUSPENDED: cascade hop 3 of the safety-stoppage chain."""
    gang["status"] = "SUSPENDED"
    gang["suspension_count"] += 1
    for ea in eas_of_gang(gang["id"]):
        if ea["status"] in ("RESERVED", "ACTIVE"):
            release_equipment_assignment(ea)
    recompute_equipment_ok(gang)
    touch(gang)


def recompute_posture(vessel):
    new = compute_posture(vessel)
    if new != vessel["work_posture"]:
        vessel["work_posture"] = new
        touch(vessel)
    if new == "FULL_STOPPAGE":
        for gang in gangs_of_vessel(vessel["id"]):
            if gang["status"] == "WORKING":
                suspend_gang(gang)


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

def windows_conflict(ns, ne, s, e):
    """30-minute buffered rule; strict inequalities, exactly-30-minute gap allowed."""
    from datetime import timedelta
    buf = timedelta(minutes=BUFFER_MINUTES)
    return ns < e + buf and ne > s - buf


def release_equipment_assignment(ea):
    ea["status"] = "RELEASED"
    touch(ea)
    unit = get("equipment_units", ea["equipment_unit_id"])
    if unit is not None and unit["status"] == "ASSIGNED":
        still_held = any(
            o["status"] in ("RESERVED", "ACTIVE")
            for o in eas_of_unit(unit["id"])
        )
        if not still_held:
            unit["status"] = "AVAILABLE"
            touch(unit)


def unit_utilization(unit_id):
    return sum(1 for e in eas_of_unit(unit_id) if e["status"] in ("RESERVED", "ACTIVE"))


def select_replacement_unit(failed_ea):
    """calculation equipment_replacement_selection."""
    failed_unit = get("equipment_units", failed_ea["equipment_unit_id"])
    ns, ne = failed_ea["_ws"], failed_ea["_we"]
    cands = []
    for u in all_of("equipment_units"):
        if u["equipment_type"] != failed_unit["equipment_type"]:
            continue
        if u["status"] != "AVAILABLE":
            continue
        ok = True
        for ea in eas_of_unit(u["id"]):
            if ea["status"] in ("RESERVED", "ACTIVE"):
                if windows_conflict(ns, ne, ea["_ws"], ea["_we"]):
                    ok = False
                    break
        if ok:
            cands.append(u)
    cands.sort(key=lambda u: (unit_utilization(u["id"]), u["_seq"]))
    return cands[0] if cands else None


# ---------------------------------------------------------------------------
# Dispatch (calculation dispatch_selection)
# ---------------------------------------------------------------------------

def _half_open_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def eligibility_failures(worker, gang):
    """Returns the set of failed eligibility clauses for dispatch_selection."""
    fails = set()
    if worker["status"] != "ACTIVE":
        fails.add("status")
    if worker["classification"] != gang["required_classification"]:
        fails.add("classification")
    this_shift = gang_shift(gang)
    for a in all_of("dispatch_assignments"):
        if a["worker_id"] != worker["id"]:
            continue
        if a["gang_order_id"] == gang["id"]:
            # retry exclusion: NO_SHOW / BUMPED on this order bar re-offer forever
            if a["status"] in ("OFFERED", "CHECKED_IN", "WORKING", "NO_SHOW", "BUMPED"):
                fails.add("same_order")
        else:
            if a["status"] in ASSIGNMENT_NONTERMINAL:
                g2 = get("gang_orders", a["gang_order_id"])
                if g2 is None:
                    continue
                s2 = gang_shift(g2)
                if _half_open_overlap(this_shift["_start"], this_shift["_end"], s2["_start"], s2["_end"]):
                    fails.add("overlap")
    return fails


def run_dispatch_selection(gang, slots, forced_ids=None):
    """Creates OFFERED assignments for the top min(slots, |eligible|) candidates.
    Returns the number created. Forced lists raise on ineligibility."""
    if forced_ids is not None:
        # Validate forced eligibility; ERR_WORKER_DOUBLE_BOOKED (tier 9) beats
        # ERR_WORKER_INELIGIBLE (tier 10) when both would fire.
        any_fail = False
        double_only = False
        for wid in forced_ids:
            w = get("workers", wid)
            fails = eligibility_failures(w, gang)
            if fails:
                any_fail = True
                if fails == {"overlap"}:
                    double_only = True
        if double_only:
            raise errors.worker_double_booked()
        if any_fail:
            raise errors.worker_ineligible()
        candidates = [get("workers", wid) for wid in forced_ids]
    else:
        candidates = [w for w in all_of("workers") if not eligibility_failures(w, gang)]
    candidates.sort(key=lambda w: (w["seniority_rank"], w["_seq"]))
    chosen = candidates[:max(slots, 0)]
    created = 0
    for w in chosen:
        rec = new_resource("dispatch_assignments")
        rec.update({
            "gang_order_id": gang["id"],
            "worker_id": w["id"],
            "status": "OFFERED",
            "seniority_rank_at_dispatch": w["seniority_rank"],
        })
        save("dispatch_assignments", rec)
        created += 1
    gang["_pool_exhausted"] = created < slots
    return created


def auto_offer(gang):
    """Single-slot auto-offer after no-show / bump / suspension cascade."""
    run_dispatch_selection(gang, 1)
    recompute_manning(gang)


def maybe_close_shift(shift):
    """Bubble-up: IN_PROGRESS -> CLOSED once every gang order is terminal (>=1 exists)."""
    if shift["status"] != "IN_PROGRESS":
        return
    gangs = gangs_of_shift(shift["id"])
    if gangs and all(g["status"] in GANG_TERMINAL for g in gangs):
        shift["status"] = "CLOSED"
        touch(shift)


# ---------------------------------------------------------------------------
# Moves / productivity (calculations moves_per_hour, productivity_bonus)
# ---------------------------------------------------------------------------

def move_aggregates(gang):
    total_moves = 0
    productive = Decimal("0")
    for r in all_of("move_records"):
        if r["gang_order_id"] == gang["id"] and r["status"] == "RECORDED":
            total_moves += r["moves_count"]
            period = Decimal(str((r["_pend"] - r["_pstart"]).total_seconds())) / Decimal(60)
            productive += period - Decimal(r["stoppage_minutes"])
    if productive <= 0:
        mph = Decimal("0")
    else:
        mph = (Decimal(total_moves * 60) / productive).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return total_moves, productive, mph


def finalize_productivity(gang):
    """Freeze actual_mph, bonus_eligible, bonus_pool_cents, bonus_per_worker_cents."""
    vessel = gang_vessel(gang)
    total_moves, productive, mph = move_aggregates(gang)
    target = Decimal(str(vessel["contracted_mph_target"]))
    gang["actual_mph"] = float(mph)
    gang["bonus_eligible"] = mph >= target
    productive_hours = productive / Decimal(60)
    target_moves_raw = target * productive_hours
    target_moves = int(target_moves_raw.to_integral_value(rounding="ROUND_CEILING")) if target_moves_raw > 0 else 0
    excess_moves = max(0, total_moves - target_moves)
    pool = excess_moves * BONUS_PER_EXCESS_MOVE_CENTS
    gang["bonus_pool_cents"] = pool
    workers_at_completion = sum(1 for a in assignments_of_gang(gang["id"]) if a["status"] == "COMPLETED")
    if pool == 0:
        gang["bonus_per_worker_cents"] = 0
    else:
        gang["bonus_per_worker_cents"] = rhu(Decimal(pool) / Decimal(max(1, workers_at_completion)))


# ---------------------------------------------------------------------------
# Payroll (calculation payroll_gross_pay)
# ---------------------------------------------------------------------------

def compute_payroll(ts, gang):
    shift = gang_shift(gang)
    mult = PERIOD_MULTIPLIER[shift["period"]]
    wm = ts["work_minutes"]
    straight = min(wm, OT_START_MINUTES)
    ot = min(max(wm - OT_START_MINUTES, 0), DT_START_MINUTES - OT_START_MINUTES)
    dt = max(wm - DT_START_MINUTES, 0)
    meal = MEAL_PENALTY_MINUTES if (wm > MEAL_THRESHOLD_MINUTES and not ts["meal_break_taken"]) else 0
    eff_base = Decimal(ts["rate_cents_snapshot"]) * mult  # unrounded
    paid_minutes = (
        Decimal(straight) * Decimal("1.0")
        + Decimal(ot) * Decimal("1.5")
        + Decimal(dt) * Decimal("2.0")
        + Decimal(meal) * Decimal("1.0")
    )
    gross = rhu(paid_minutes * eff_base / Decimal(60))
    return straight, ot, dt, meal, gross


# ---------------------------------------------------------------------------
# Damage claims (calculation damage_liability)
# ---------------------------------------------------------------------------

def provisional_share(estimated_amount_cents):
    return rhu(Decimal(estimated_amount_cents) * PROVISIONAL_SHARE_PCT)


def final_liability(estimated_amount_cents, fault_pct):
    raw = rhu(Decimal(estimated_amount_cents) * Decimal(fault_pct) / Decimal(100))
    capped = min(raw, STEVEDORE_CAP_CENTS)
    return max(0, capped - DEDUCTIBLE_CENTS)


# ---------------------------------------------------------------------------
# Invoice (calculation invoice_calculation)
# ---------------------------------------------------------------------------

def container_line(moves):
    t1 = min(moves, TIER1_MOVES) * TIER1_RATE_CENTS
    t2 = min(max(moves - TIER1_MOVES, 0), TIER2_MOVES - TIER1_MOVES) * TIER2_RATE_CENTS
    t3 = max(moves - TIER2_MOVES, 0) * TIER3_RATE_CENTS
    return t1 + t2 + t3


def tonnage_line(tons):
    return rhu(Decimal(str(tons)) * Decimal(TON_RATE_CENTS))


def _vessel_approved_work_minutes(vessel):
    gang_ids = {g["id"] for g in gangs_of_vessel(vessel["id"])}
    total = 0
    for ts in all_of("timesheet_entries"):
        if ts["status"] == "APPROVED" and ts["gang_order_id"] in gang_ids:
            total += ts["work_minutes"]
    return total


def _vessel_equipment_line(vessel):
    gang_ids = {g["id"] for g in gangs_of_vessel(vessel["id"])}
    total = 0
    for etype, rate in EQUIP_RATE_CENTS.items():
        billable = Decimal("0")
        for ea in all_of("equipment_assignments"):
            if ea["gang_order_id"] not in gang_ids:
                continue
            unit = get("equipment_units", ea["equipment_unit_id"])
            if unit is None or unit["equipment_type"] != etype:
                continue
            if ea["status"] in ("ACTIVE", "RELEASED"):
                billable += window_minutes(ea)
            elif ea["status"] == "DOWN":
                billable += DOWN_BILLING_FACTOR * window_minutes(ea)
        total += rhu(billable * Decimal(rate) / Decimal(60))
    return total


def compute_invoice_lines(vessel, variant):
    """Per-line round half up to integer cents, THEN sum (pinned rounding order)."""
    gangs = gangs_of_vessel(vessel["id"])
    if variant == "PROVISIONAL":
        container = container_line(vessel["planned_moves"])
        tonnage = tonnage_line(vessel["planned_tons"])
        planned_minutes = sum(
            g["required_headcount"] for g in gangs if g["status"] != "CANCELLED"
        ) * 480
        manhour = rhu(Decimal(planned_minutes) * Decimal(MANHOUR_RATE_CENTS) / Decimal(60))
        equipment = 0
        stoppage = 0
    else:
        container = container_line(vessel["actual_moves"])
        tonnage = tonnage_line(vessel["actual_tons"])
        total_wm = _vessel_approved_work_minutes(vessel)
        manhour = rhu(Decimal(total_wm) * Decimal(MANHOUR_RATE_CENTS) / Decimal(60))
        equipment = _vessel_equipment_line(vessel)
        stoppage = -STOPPAGE_CREDIT_PER_SUSPENSION_CENTS * sum(g["suspension_count"] for g in gangs)
    subtotal = container + tonnage + manhour + equipment + stoppage
    if subtotal > 0:
        if subtotal >= DISCOUNT_TIER2_SUBTOTAL_CENTS:
            rate = DISCOUNT_TIER2_RATE
        elif subtotal >= DISCOUNT_TIER1_SUBTOTAL_CENTS:
            rate = DISCOUNT_TIER1_RATE
        else:
            rate = Decimal("0")
        discount = rhu(Decimal(subtotal) * rate)
    else:
        discount = 0
    return {
        "container_line_cents": container,
        "tonnage_line_cents": tonnage,
        "manhour_line_cents": manhour,
        "equipment_line_cents": equipment,
        "stoppage_credit_cents": stoppage,
        "subtotal_cents": subtotal,
        "discount_cents": discount,
    }


def recompute_invoice_totals(inv):
    inv["total_cents"] = inv["subtotal_cents"] - inv["discount_cents"] + inv["adjustment_total_cents"]
    inv["remaining_balance_cents"] = inv["total_cents"] - inv["amount_paid_cents"]
