"""Core business services: serialization, calculations, cascades, lazy transitions.

All monetary/decimal computation uses Decimal with ROUND_HALF_UP per PRD 2.9.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import math

import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGULATORY_BASE_CAP_BPM = {"EVISCERATION": 175, "DEBONING": 45}
REQUIRED_AT_RATED = {
    "EVISCERATION": {"shacklers": 10, "eviscerators": 20, "qa_techs": 2},
    "DEBONING": {"deboners": 12, "qa_techs": 1},
}
REDUCED_BAND_SPEED_FACTOR = Decimal("0.9")
STAFFING_BAND_REDUCED = Decimal("0.9")

WATER_LIMIT_GAL_PER_1000_BIRDS = Decimal("1500.0")
WATER_LIMIT_GAL_PER_100LB = Decimal("200.0")
CHILLER_LIMIT_GAL_PER_1000_BIRDS = Decimal("800.0")

TRIM_ALLOWANCE_PCT = Decimal("0.02")
POUNDS_PER_LABOR_HOUR = Decimal("500.0")

EVISCERATED_BASIS_ALLOWANCE = Decimal("0.88")

CHILL_TARGET_TEMP_C = Decimal("4.0")
CHILL_DEADLINE_HOURS = 8
MIN_CHILL_HOURS = 2
FRESH_YIELD_THRESHOLD_PCT = Decimal("72.0")
LOT_CHILL_HOURS = 4

D2 = Decimal("0.01")


def round2(value):
    """Round a Decimal to 2 places, half-up. Returns a float for JSON output."""
    if value is None:
        return None
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return float(d.quantize(D2, rounding=ROUND_HALF_UP))


def now_iso():
    """Current logical clock as ISO8601 UTC with three fractional digits."""
    n = db.clock_now()
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def dt_iso(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Lazy clock-driven transitions
# ---------------------------------------------------------------------------

def evaluate_waiver_clock():
    """Evaluate APPROVED->ACTIVE and ACTIVE->EXPIRED against the logical clock."""
    now = db.clock_now()
    for w in list(db.waivers.values()):
        if w["status"] == "APPROVED" and w["effective_from"] <= now < w["effective_to"]:
            w["status"] = "ACTIVE"
            _touch(w)
            # activation changes the effective cap; clamp running runs
            clamp_runs_for_line(w["line_id"])
        elif w["status"] == "ACTIVE" and now >= w["effective_to"]:
            w["status"] = "EXPIRED"
            _touch(w)
            clamp_runs_for_line(w["line_id"])
        elif w["status"] == "APPROVED" and now >= w["effective_to"]:
            # Window passed without ever activating: approve->expire is not a
            # declared transition; APPROVED stays until expiry evaluated.
            # Per the state machine, EXPIRED is from ACTIVE only. An APPROVED
            # waiver whose window elapsed never activates; leave as APPROVED.
            pass


def evaluate_lot_chill(lot):
    """Evaluate ON_LINE -> CHILLED for a single lot."""
    if lot["status"] != "ON_LINE":
        return
    runs = [r for r in db.line_runs.values() if r["flock_lot_id"] == lot["id"]]
    terminal_ok = all(r["status"] in ("COMPLETED", "RECONCILED", "CANCELLED") for r in runs)
    has_completed = any(r["status"] in ("COMPLETED", "RECONCILED") for r in runs)
    if not (terminal_ok and has_completed):
        return
    completed_runs = [r for r in runs if r["status"] in ("COMPLETED", "RECONCILED") and r.get("completed_at")]
    if not completed_runs:
        return
    latest_completed = max(r["completed_at"] for r in completed_runs)
    if db.clock_now() >= latest_completed + timedelta(hours=LOT_CHILL_HOURS):
        lot["status"] = "CHILLED"
        _touch(lot)


def evaluate_all_lot_chill():
    for lot in list(db.flock_lots.values()):
        evaluate_lot_chill(lot)


def evaluate_clock_transitions():
    """Evaluate every clock-driven system transition (called on clock-set)."""
    evaluate_waiver_clock()
    evaluate_all_lot_chill()


def lazy_lot(lot):
    """Lazy transitions evaluated whenever a flock lot is read."""
    evaluate_lot_chill(lot)


def lazy_waiver(waiver):
    """Lazy transitions evaluated whenever a waiver is read."""
    now = db.clock_now()
    if waiver["status"] == "APPROVED" and waiver["effective_from"] <= now < waiver["effective_to"]:
        waiver["status"] = "ACTIVE"
        _touch(waiver)
        clamp_runs_for_line(waiver["line_id"])
    elif waiver["status"] == "ACTIVE" and now >= waiver["effective_to"]:
        waiver["status"] = "EXPIRED"
        _touch(waiver)
        clamp_runs_for_line(waiver["line_id"])


def lazy_line(line_id):
    """Evaluate waiver transitions for a line (used before speed checks)."""
    for w in db.waivers.values():
        if w["line_id"] == line_id and w["status"] in ("APPROVED", "ACTIVE"):
            lazy_waiver(w)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def _touch(entity):
    """Refresh updated_at and bump version (lifecycle resources only)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def new_entity():
    return {
        "id": db.new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }


def new_event():
    return {
        "id": db.new_id(),
        "created_at": now_iso(),
    }


# ---------------------------------------------------------------------------
# effective_max_line_speed (calculation 1)
# ---------------------------------------------------------------------------

def effective_max_line_speed(line, shift):
    """Pinned evaluation order from the scaffold/PRD 3.1.

    Returns an integer bpm ceiling.
    """
    line_type = line["line_type"]
    rated = line["rated_speed_bpm"]

    # (1)+(2): staffing ratio from the fixed table
    req = REQUIRED_AT_RATED[line_type]
    present_map = {
        "shacklers": shift["shacklers_present"],
        "eviscerators": shift["eviscerators_present"],
        "deboners": shift["deboners_present"],
        "qa_techs": shift["qa_techs_present"],
    }
    ratio = None
    for position, required in req.items():
        present = present_map[position]
        r = Decimal(present) / Decimal(required)
        ratio = r if ratio is None else min(ratio, r)

    # (3): staffing cap
    if ratio >= Decimal("1.0"):
        staffing_cap = int(math.floor(rated * 1.0))
    elif ratio >= STAFFING_BAND_REDUCED:
        staffing_cap = int(math.floor(Decimal(rated) * REDUCED_BAND_SPEED_FACTOR))
    else:
        staffing_cap = REGULATORY_BASE_CAP_BPM[line_type]  # waiver void

    # (4): regulatory cap — ACTIVE waiver covering now, else base cap
    now = db.clock_now()
    covering = [
        w for w in db.waivers.values()
        if w["line_id"] == line["id"]
        and w["status"] == "ACTIVE"
        and w["effective_from"] <= now < w["effective_to"]
    ]
    if covering:
        # Latest effective_from wins; tie-break latest created_at
        covering.sort(key=lambda w: (w["effective_from"], w["created_at"]), reverse=True)
        regulatory_cap = covering[0]["max_speed_bpm"]
    else:
        regulatory_cap = REGULATORY_BASE_CAP_BPM[line_type]

    # (5)
    return min(rated, regulatory_cap, staffing_cap)


def clamp_runs_for_line(line_id):
    """Recompute the effective cap for RUNNING runs of this line; clamp and flag."""
    for run in db.line_runs.values():
        if run["line_id"] != line_id or run["status"] != "RUNNING":
            continue
        shift = db.shifts.get(run["shift_id"])
        line = db.lines.get(line_id)
        if not shift or not line:
            continue
        cap = effective_max_line_speed(line, shift)
        if run["current_speed_bpm"] > cap:
            run["current_speed_bpm"] = cap
            run["speed_clamped"] = True
            _touch(run)


def clamp_runs_for_shift(shift):
    """After a staffing update: clamp RUNNING runs of this shift."""
    for run in db.line_runs.values():
        if run["shift_id"] != shift["id"] or run["status"] != "RUNNING":
            continue
        line = db.lines.get(run["line_id"])
        if not line:
            continue
        cap = effective_max_line_speed(line, shift)
        if run["current_speed_bpm"] > cap:
            run["current_speed_bpm"] = cap
            run["speed_clamped"] = True
            _touch(run)


# ---------------------------------------------------------------------------
# Water intensity (calculation 3) and shift aggregates
# ---------------------------------------------------------------------------

def recompute_shift_aggregates(shift):
    """Recompute water/process aggregates and derived rates for a shift."""
    # Water totals
    process = Decimal("0")
    chiller = Decimal("0")
    for r in db.utility_readings.values():
        if r["shift_id"] != shift["id"]:
            continue
        if r["meter_type"] == "PROCESS_WATER":
            process += Decimal(str(r["gallons"]))
        elif r["meter_type"] == "CHILLER_WATER":
            chiller += Decimal(str(r["gallons"]))
    shift["process_water_gallons"] = float(process)
    shift["chiller_water_gallons"] = float(chiller)

    # Production denominators from COMPLETED/RECONCILED runs of this shift
    birds = 0
    weight = Decimal("0")
    for run in db.line_runs.values():
        if run["shift_id"] == shift["id"] and run["status"] in ("COMPLETED", "RECONCILED"):
            birds += run.get("birds_hung") or 0
            if run.get("carcass_weight_lb") is not None:
                weight += Decimal(str(run["carcass_weight_lb"]))
    shift["birds_processed"] = birds
    shift["chilled_weight_lb"] = float(weight)

    # Water rates (unrounded for breach logic; rounded for reporting)
    if birds > 0:
        rate_birds = process * Decimal(1000) / Decimal(birds)
        shift["water_rate_birds_basis"] = round2(rate_birds)
        shift["water_breach_active"] = bool(rate_birds > WATER_LIMIT_GAL_PER_1000_BIRDS)
        chiller_rate = chiller * Decimal(1000) / Decimal(birds)
        shift["chiller_limit_breached"] = bool(chiller_rate > CHILLER_LIMIT_GAL_PER_1000_BIRDS)
    else:
        shift["water_rate_birds_basis"] = None
        shift["water_breach_active"] = False
        shift["chiller_limit_breached"] = False

    if weight > 0:
        rate_weight = process * Decimal(100) / weight
        shift["water_rate_weight_basis"] = round2(rate_weight)
    else:
        shift["water_rate_weight_basis"] = None

    recompute_shift_labor(shift)


def recompute_shift_labor(shift):
    """labor_hours_remaining per the labor ledger formula."""
    budget = Decimal(str(shift["labor_hours_budget"]))
    est = Decimal("0")
    act = Decimal("0")
    for b in db.deboning_batches.values():
        if b["shift_id"] != shift["id"]:
            continue
        if b["status"] in ("SCHEDULED", "IN_PROGRESS", "ON_HOLD"):
            est += Decimal(str(b["estimated_labor_hours"]))
        elif b["status"] == "COMPLETED":
            act += Decimal(str(b["actual_labor_hours"]))
    shift["labor_hours_remaining"] = round2(budget - est - act)


# ---------------------------------------------------------------------------
# Flock-lot aggregates and yields (calculation 2 + bird accountability)
# ---------------------------------------------------------------------------

def _lot_runs(lot_id):
    return [r for r in db.line_runs.values() if r["flock_lot_id"] == lot_id]


def _run_records(run_id):
    return [c for c in db.condemnation_records.values() if c["line_run_id"] == run_id]


def recompute_lot_aggregates(lot, recompute_certified_yield=False, recompute_provisional=True):
    """Recompute birds_hung_total, condemned_accounted, carcasses_to_chill,
    carcass_weight_total_lb and (optionally) provisional yield for a flock lot.

    PRD 3.4 pins the provisional variant's recompute triggers: each run
    completion and every condemnation create, dispute, or recertify while
    condemnations remain uncertified. First certification (DRAFT->CERTIFIED)
    and settlement are NOT triggers, so callers on those paths pass
    recompute_provisional=False and the last computed value is retained.
    """
    runs = _lot_runs(lot["id"])
    counted_runs = [r for r in runs if r["status"] in ("COMPLETED", "RECONCILED")]

    birds_hung_total = sum(r.get("birds_hung") or 0 for r in counted_runs)
    carcass_total = Decimal("0")
    for r in counted_runs:
        if r.get("carcass_weight_lb") is not None:
            carcass_total += Decimal(str(r["carcass_weight_lb"]))

    condemned_accounted = 0
    provisional_condemned = 0
    certified_condemned = 0
    for r in counted_runs:
        for c in _run_records(r["id"]):
            eff = c.get("effective_count")
            if eff is None:
                eff = c["amended_carcass_count"] if c.get("amended_carcass_count") is not None else c["carcass_count"]
            if c["status"] in ("DRAFT", "CERTIFIED"):
                condemned_accounted += eff
            if c["status"] in ("DRAFT", "DISPUTED"):
                provisional_condemned += eff
            if c["status"] == "CERTIFIED":
                certified_condemned += eff

    lot["birds_hung_total"] = birds_hung_total
    lot["condemned_accounted"] = condemned_accounted
    lot["carcasses_to_chill"] = birds_hung_total - condemned_accounted
    lot["carcass_weight_total_lb"] = float(carcass_total)

    # Provisional yield: null until first run completes
    if recompute_provisional:
        if birds_hung_total > 0 and lot.get("total_live_weight_lb") is not None:
            L = Decimal(str(lot["total_live_weight_lb"]))
            N = Decimal(lot["head_count_received"])
            H = Decimal(birds_hung_total)
            P = Decimal(provisional_condemned)
            avg_live = L / N
            prov = (H - P) * (avg_live * EVISCERATED_BASIS_ALLOWANCE) / L * Decimal(100)
            lot["provisional_yield_pct"] = round2(prov)
        elif counted_runs and lot.get("total_live_weight_lb") is not None:
            L = Decimal(str(lot["total_live_weight_lb"]))
            N = Decimal(lot["head_count_received"])
            avg_live = L / N
            prov = (Decimal(0) - Decimal(provisional_condemned)) * (avg_live * EVISCERATED_BASIS_ALLOWANCE) / L * Decimal(100)
            lot["provisional_yield_pct"] = round2(prov)
        else:
            lot["provisional_yield_pct"] = None

    if recompute_certified_yield:
        recompute_certified_yield_for_lot(lot)


def lot_has_uncertified_records(lot):
    """True while any condemnation record on the lot's runs is DRAFT or DISPUTED."""
    for r in _lot_runs(lot["id"]):
        for c in _run_records(r["id"]):
            if c["status"] in ("DRAFT", "DISPUTED"):
                return True
    return False


def recompute_certified_yield_for_lot(lot):
    """Certified variant: live-basis actual using certified counts only.

    Returns (old_value, new_value) so callers can detect a decrease.
    """
    old = lot.get("certified_yield_pct")
    H = lot.get("birds_hung_total") or 0
    L = lot.get("total_live_weight_lb")
    if H == 0 or L is None:
        lot["certified_yield_pct"] = None
        return old, None
    W = Decimal(str(lot.get("carcass_weight_total_lb") or 0))
    Hd = Decimal(H)
    Ld = Decimal(str(L))
    avg_carcass = W / Hd
    C = Decimal(0)
    for r in _lot_runs(lot["id"]):
        if r["status"] not in ("COMPLETED", "RECONCILED"):
            continue
        for c in _run_records(r["id"]):
            if c["status"] == "CERTIFIED":
                C += Decimal(c.get("effective_count") if c.get("effective_count") is not None else c["carcass_count"])
    cert = (W - C * avg_carcass) / Ld * Decimal(100)
    new = round2(cert)
    lot["certified_yield_pct"] = new
    return old, new


def apply_routing_flip(lot, old_certified, new_certified):
    """On certified yield decrease, flip TRACE_LOCKED FRESH flexible lots to FROZEN."""
    if new_certified is None:
        return
    if old_certified is not None and not (Decimal(str(new_certified)) < Decimal(str(old_certified))):
        return
    if not (Decimal(str(new_certified)) < FRESH_YIELD_THRESHOLD_PCT):
        return
    # flip
    for fl in db.finished_lots.values():
        if fl["status"] != "TRACE_LOCKED" or fl["routing_status"] != "FRESH":
            continue
        batch = db.deboning_batches.get(fl["deboning_batch_id"])
        if not batch or batch["flock_lot_id"] != lot["id"]:
            continue
        order = db.orders.get(fl["order_id"])
        if not order or order["temperature_requirement"] != "FLEXIBLE":
            continue
        fl["routing_status"] = "FROZEN"
        _touch(fl)


def maybe_reconcile_run(run):
    """If every condemnation record of the run is CERTIFIED, COMPLETED -> RECONCILED.

    A run with zero records satisfies the gate vacuously and is reconciled
    automatically at completion (no certification events will ever occur).
    """
    if run["status"] != "COMPLETED":
        return False
    records = _run_records(run["id"])
    if all(c["status"] == "CERTIFIED" for c in records):
        run["status"] = "RECONCILED"
        _touch(run)
        return True
    return False


def refresh_shift_for_run(run):
    shift = db.shifts.get(run["shift_id"])
    if shift:
        recompute_shift_aggregates(shift)
        _touch(shift)
    return shift
