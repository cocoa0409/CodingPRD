"""Domain logic: three parallel boiler status dimensions, lead/lag selector,
compensating fuel & water ledgers, combustion efficiency variants, steam-trap
loss variants, the pinned 7-step blowdown chain, certificate/license expiry,
trip cascades (depth 3), posture derivation, and the operations checkpoint.

Constants the PRD leaves to configuration (SULFITE_MIN_PPM, the phosphate band,
CHEMISTRY_CRITICAL_COUNT, CRITICAL_CYCLES_FACTOR, CHEMISTRY_RECOVERY_COUNT,
CONDITIONAL_FOLLOWUP_DAYS) are chosen so every worked example in the PRD and
design fixtures holds: sulfite 30 ppm and phosphate 40 ppm are in-spec, and a
cycles reading of exactly 15.0 is out-of-spec but not yet critical.
"""
from datetime import timedelta
from decimal import Decimal

import clock
import store
from errors import (
    raise_err,
    ERR_FUEL_INVENTORY_UNDERFLOW,
    ERR_OPERATOR_LICENSE_INVALID,
    ERR_LICENSE_WRONG_STATE,
)
from util import (
    new_record,
    new_journal_record,
    round2,
    round4,
    serialize,
    touch,
)

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
MAX_CYCLES = 10.0
SULFITE_MIN_PPM = 20.0
PHOSPHATE_MIN_PPM = 20.0
PHOSPHATE_MAX_PPM = 60.0
CHEMISTRY_CRITICAL_COUNT = 3
CRITICAL_CYCLES_FACTOR = 1.5
CHEMISTRY_RECOVERY_COUNT = 2
CONDITIONAL_FOLLOWUP_DAYS = 30

CERT_EXPIRING_WINDOW_SECONDS = 30 * 86400      # 30 days, inclusive (<=)
LICENSE_EXPIRING_WINDOW_SECONDS = 60 * 86400   # 60 days, inclusive (<=)

ENTHALPY_STEAM_BTU_PER_LB = 1190.0
ENTHALPY_FEEDWATER_BTU_PER_LB = 180.0
FUEL_HHV_BTU_PER_GAL = 140000.0
DRY_GAS_LOSS_PCT = 6.5
MOISTURE_LOSS_PCT = 4.0
BLOWDOWN_ENTHALPY_PCT = 100.0
RADIATION_LOSS_PCT = 1.5
EPSILON = 0.000001

NAPIER_COEFF = 51.45
GRASHOF_COEFF = 24.24
HOURS_PER_YEAR = 8760
DEFAULT_FUEL_COST_PER_GAL = 3.50

TARGET_CYCLES = 10.0
LB_PER_GAL_WATER = 8.345
BLOWDOWN_MIN_GAL_DAY = 5.0
BLOWDOWN_MAX_GAL_DAY = 5000.0

CYCLES_PENALTY_WEIGHT = 0.15
LEAD_BONUS = 5000.0

DRIFT_TOLERANCE_GAL = 25.0

INSPECTION_DURATION_HOURS = 4
INSPECTION_BUFFER_HOURS = 2

LAG_REEVAL_WINDOW_SECONDS = 900  # 15 minutes, cascade depth 3

TRIP_SEVERITIES = ("HIGH", "CRITICAL")
TRIP_KINDS = ("OVERPRESSURE", "LOW_WATER", "FLAME_FAILURE", "RELIEF_VALVE_LIFT")
ANNUAL_KINDS = ("ANNUAL_INTERNAL", "ANNUAL_EXTERNAL")

STATE_CODES = ("MA", "NY", "CA", "TX")
LICENSE_CLASSES = ("CLASS_1", "CLASS_2", "CLASS_3")
INSPECTION_KINDS = ("ANNUAL_INTERNAL", "ANNUAL_EXTERNAL", "RELIEF_VALVE_POP", "POST_INCIDENT")
OUTCOMES = ("PASSED", "FAILED", "CONDITIONAL")
TRAP_CONDITIONS = ("UNKNOWN", "OK", "LEAKING", "FAILED_OPEN", "FAILED_CLOSED", "COLD")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
INCIDENT_KINDS = ("OVERPRESSURE", "LOW_WATER", "FLAME_FAILURE", "RELIEF_VALVE_LIFT", "CHEMISTRY_EXCURSION", "OTHER")

# ---------------------------------------------------------------------------
# serializers (exact field surfaces per scaffold entity table)
# ---------------------------------------------------------------------------
PLANT_FIELDS = [
    "id", "name", "state_code", "header_pressure_psi", "header_pressure_actual_psi",
    "fuel_inventory_gal", "total_fuel_received_gal", "total_fuel_consumed_gal",
    "posture", "lead_boiler_id", "ops_run_index",
    "created_at", "updated_at", "version",
]
BOILER_FIELDS = [
    "id", "plant_id", "tag", "rated_capacity_lb_hr", "relief_valve_setpoint_psi",
    "relief_valve_tolerance_pct", "ops_status", "cert_status", "water_status",
    "cycles_of_concentration", "total_steam_lb", "total_fuel_burned_gal",
    "total_blowdown_gal", "total_feedwater_gal", "efficiency_pct",
    "created_at", "updated_at", "version",
]
OPERATOR_FIELDS = [
    "id", "plant_id", "full_name", "license_class", "license_state",
    "license_expires_on", "license_status", "is_lead_qualified",
    "created_at", "updated_at", "version",
]
LOG_ENTRY_FIELDS = [
    "id", "boiler_id", "recorded_by_operator_id", "recorded_at",
    "header_pressure_reading_psi", "steam_generated_lb", "fuel_burned_gal",
    "feedwater_intake_gal", "blowdown_gal", "status", "created_at",
]
CHEMISTRY_FIELDS = [
    "id", "boiler_id", "recorded_by_operator_id", "recorded_at",
    "conductivity_boiler_umho", "conductivity_feedwater_umho",
    "sulfite_residual_ppm", "phosphate_residual_ppm", "status", "created_at",
]
INSPECTION_FIELDS = [
    "id", "boiler_id", "inspection_kind", "scheduled_on", "inspector_name",
    "inspector_license_no", "relief_valve_lift_pressure_psi", "outcome",
    "certificate_number", "certificate_expires_on", "posted_at",
    "created_at", "updated_at", "version",
]
TRAP_FIELDS = [
    "id", "plant_id", "tag", "location", "orifice_diameter_in",
    "design_pressure_psi", "last_surveyed_at", "condition", "leak_rate_lb_hr",
    "status", "created_at", "updated_at", "version",
]
DISPATCH_FIELDS = [
    "id", "plant_id", "window_start_at", "window_end_at", "target_steam_lb_hr",
    "assigned_boiler_ids", "expected_lead_boiler_id", "status",
    "created_at", "updated_at", "version",
]
INCIDENT_FIELDS = [
    "id", "plant_id", "raised_by_operator_id", "severity", "kind",
    "triggered_boiler_id", "raised_at", "status", "resolution_notes",
    "created_at", "updated_at", "version",
]
DELIVERY_FIELDS = [
    "id", "plant_id", "delivered_at", "quantity_gal", "supplier", "created_at",
]


def plant_json(rec):
    return serialize(rec, PLANT_FIELDS)


def boiler_json(rec):
    return serialize(rec, BOILER_FIELDS)


def operator_json(rec):
    return serialize(rec, OPERATOR_FIELDS)


def log_entry_json(rec):
    return serialize(rec, LOG_ENTRY_FIELDS)


def chemistry_json(rec):
    return serialize(rec, CHEMISTRY_FIELDS)


def inspection_json(rec):
    return serialize(rec, INSPECTION_FIELDS)


def trap_json(rec):
    return serialize(rec, TRAP_FIELDS)


def dispatch_json(rec):
    return serialize(rec, DISPATCH_FIELDS)


def incident_json(rec):
    return serialize(rec, INCIDENT_FIELDS)


def delivery_json(rec):
    return serialize(rec, DELIVERY_FIELDS)


# ---------------------------------------------------------------------------
# collection lookups
# ---------------------------------------------------------------------------
def boilers_of(plant_id):
    return [b for b in store.boilers.values() if b["plant_id"] == plant_id]


def operators_of(plant_id):
    return [o for o in store.operators.values() if o["plant_id"] == plant_id]


def entries_of(boiler_id):
    return [e for e in store.log_entries.values() if e["boiler_id"] == boiler_id]


def chemlogs_of(boiler_id):
    return [c for c in store.chemistry_logs.values() if c["boiler_id"] == boiler_id]


def inspections_of(boiler_id):
    return [i for i in store.inspections.values() if i["boiler_id"] == boiler_id]


def traps_of(plant_id):
    return [t for t in store.steam_traps.values() if t["plant_id"] == plant_id]


def dispatches_of(plant_id):
    return [d for d in store.dispatches.values() if d["plant_id"] == plant_id]


def incidents_of(plant_id):
    return [i for i in store.incidents.values() if i["plant_id"] == plant_id]


def deliveries_of(plant_id):
    return [f for f in store.fuel_deliveries.values() if f["plant_id"] == plant_id]


# ---------------------------------------------------------------------------
# operator gates (pipeline stages 8 and 9)
# ---------------------------------------------------------------------------
def require_active_operator(uid):
    """Stage 8: calling operator must exist and hold an ACTIVE license."""
    op = store.operators.get(uid)
    if op is None or op["license_status"] != "ACTIVE":
        raise_err(ERR_OPERATOR_LICENSE_INVALID,
                  "Calling operator does not hold an ACTIVE license")
    return op


def require_license_class(op, classes):
    if op["license_class"] not in classes:
        raise_err(ERR_OPERATOR_LICENSE_INVALID,
                  "Operator license_class %s is inadequate for this action" % op["license_class"])


def require_jurisdiction(op, plant):
    """Stage 9: calling operator's license_state must equal plant state_code."""
    if op["license_state"] != plant["state_code"]:
        raise_err(ERR_LICENSE_WRONG_STATE,
                  "Operator license_state does not match plant state_code")


# ---------------------------------------------------------------------------
# header pressure (Plant.header_pressure_actual_psi: latest VERIFIED reading
# across ONLINE boilers, else 0)
# ---------------------------------------------------------------------------
def set_header_pressure(plant):
    best_key = None
    best_val = 0
    for b in boilers_of(plant["id"]):
        if b["ops_status"] != "ONLINE":
            continue
        for e in entries_of(b["id"]):
            if e["status"] != "VERIFIED":
                continue
            key = (e["recorded_at"], e["_seq"])
            if best_key is None or key > best_key:
                best_key = key
                best_val = e["header_pressure_reading_psi"]
    if best_key is None:
        best_val = 0
    if plant["header_pressure_actual_psi"] != best_val:
        plant["header_pressure_actual_psi"] = best_val
        return True
    return False


# ---------------------------------------------------------------------------
# posture: derived from active HIGH/CRITICAL incidents and TRIPPED boilers
# (PRD 3.9); EMERGENCY when no boiler remains ONLINE, DEGRADED otherwise.
# ---------------------------------------------------------------------------
def set_posture(plant):
    open_hi = any(
        i["status"] in ("OPEN", "ACKNOWLEDGED") and i["severity"] in TRIP_SEVERITIES
        for i in incidents_of(plant["id"])
    )
    tripped = any(b["ops_status"] == "TRIPPED" for b in boilers_of(plant["id"]))
    if open_hi or tripped:
        online = any(b["ops_status"] == "ONLINE" for b in boilers_of(plant["id"]))
        new = "DEGRADED" if online else "EMERGENCY"
    else:
        new = "NORMAL"
    if plant["posture"] != new:
        plant["posture"] = new
        return True
    return False


# ---------------------------------------------------------------------------
# lead/lag selector (PRD 3.4)
# ---------------------------------------------------------------------------
def _eligible(b):
    return (b["ops_status"] == "ONLINE"
            and b["cert_status"] == "VALID"
            and b["water_status"] != "CRITICAL")


def _score(b, current_lead_id):
    eff = 1.0 if b["efficiency_pct"] is None else b["efficiency_pct"] / 100.0
    penalty = 1.0 - min(b["cycles_of_concentration"] / MAX_CYCLES, 1.0) * CYCLES_PENALTY_WEIGHT
    bonus = LEAD_BONUS if b["id"] == current_lead_id else 0.0
    return round4(b["rated_capacity_lb_hr"] * eff * penalty + bonus)


def _rank(cands, current_lead_id):
    return sorted(
        cands,
        key=lambda b: (
            -_score(b, current_lead_id),
            -b["rated_capacity_lb_hr"],
            b["created_at"],
            b["_seq"],
        ),
    )


def compute_lead(plant, prefer_id=None):
    if prefer_id is not None:
        pref = store.boilers.get(prefer_id)
        if (pref is not None and pref["plant_id"] == plant["id"]
                and pref["ops_status"] == "ONLINE"):
            return prefer_id
    cands = [b for b in boilers_of(plant["id"]) if _eligible(b)]
    if not cands:
        return None
    return _rank(cands, plant["lead_boiler_id"])[0]["id"]


def set_lead(plant, prefer_id=None):
    new = compute_lead(plant, prefer_id=prefer_id)
    if plant["lead_boiler_id"] != new:
        plant["lead_boiler_id"] = new
        return True
    return False


# ---------------------------------------------------------------------------
# combustion efficiency (PRD 3.5): dual variant selected by plant state_code
# ---------------------------------------------------------------------------
def recompute_efficiency(plant, boiler):
    verified = [e for e in entries_of(boiler["id"]) if e["status"] == "VERIFIED"]
    if not verified:
        boiler["efficiency_pct"] = None
        return
    ts = boiler["total_steam_lb"]
    tf = boiler["total_fuel_burned_gal"]
    tb = boiler["total_blowdown_gal"]
    tfw = boiler["total_feedwater_gal"]
    if plant["state_code"] == "MA":
        # ASME PTC 4.1 heat-loss method
        denom = tfw if tfw >= EPSILON else EPSILON
        l_blowdown = (tb / denom) * BLOWDOWN_ENTHALPY_PCT
        eff = 100.0 - (DRY_GAS_LOSS_PCT + MOISTURE_LOSS_PCT + l_blowdown + RADIATION_LOSS_PCT)
        boiler["efficiency_pct"] = round2(eff)
    else:
        # input-output method (default)
        if tf == 0:
            boiler["efficiency_pct"] = None
            return
        eff = ((ts * (ENTHALPY_STEAM_BTU_PER_LB - ENTHALPY_FEEDWATER_BTU_PER_LB))
               / (tf * FUEL_HHV_BTU_PER_GAL)) * 100.0
        boiler["efficiency_pct"] = round2(eff)


# ---------------------------------------------------------------------------
# fuel ledger (PRD 2.10): compensating, 2dp half-up, never negative
# ---------------------------------------------------------------------------
def plant_fuel_receive(plant, qty):
    plant["total_fuel_received_gal"] = round2(plant["total_fuel_received_gal"] + qty)
    plant["fuel_inventory_gal"] = round2(
        plant["total_fuel_received_gal"] - plant["total_fuel_consumed_gal"])


def check_verify_underflow(plant, entry):
    """Pipeline stage 18 applied to verify as well: inventory may never go negative."""
    new_consumed = round2(plant["total_fuel_consumed_gal"] + entry["fuel_burned_gal"])
    if round2(plant["total_fuel_received_gal"] - new_consumed) < 0:
        raise_err(ERR_FUEL_INVENTORY_UNDERFLOW,
                  "Verifying this entry would drive fuel_inventory_gal negative")


def check_void_underflow(plant, entry):
    new_consumed = round2(plant["total_fuel_consumed_gal"] - entry["fuel_burned_gal"])
    if round2(plant["total_fuel_received_gal"] - new_consumed) < 0:
        raise_err(ERR_FUEL_INVENTORY_UNDERFLOW,
                  "Voiding this entry would drive fuel_inventory_gal negative")


def apply_entry_verify(plant, boiler, entry, actor_id):
    entry["status"] = "VERIFIED"
    plant["total_fuel_consumed_gal"] = round2(
        plant["total_fuel_consumed_gal"] + entry["fuel_burned_gal"])
    plant["fuel_inventory_gal"] = round2(
        plant["total_fuel_received_gal"] - plant["total_fuel_consumed_gal"])
    boiler["total_steam_lb"] = round2(boiler["total_steam_lb"] + entry["steam_generated_lb"])
    boiler["total_fuel_burned_gal"] = round2(boiler["total_fuel_burned_gal"] + entry["fuel_burned_gal"])
    boiler["total_blowdown_gal"] = round2(boiler["total_blowdown_gal"] + entry["blowdown_gal"])
    boiler["total_feedwater_gal"] = round2(boiler["total_feedwater_gal"] + entry["feedwater_intake_gal"])
    recompute_efficiency(plant, boiler)
    set_header_pressure(plant)
    check_water_drift(plant, boiler, actor_id)
    touch(boiler)
    touch(plant)


def apply_entry_void(plant, boiler, entry, actor_id):
    """Compensating reversal of a VERIFIED entry (PRD 2.10 / 3.5)."""
    entry["status"] = "VOIDED"
    plant["total_fuel_consumed_gal"] = round2(
        plant["total_fuel_consumed_gal"] - entry["fuel_burned_gal"])
    plant["fuel_inventory_gal"] = round2(
        plant["total_fuel_received_gal"] - plant["total_fuel_consumed_gal"])
    boiler["total_steam_lb"] = round2(boiler["total_steam_lb"] - entry["steam_generated_lb"])
    boiler["total_fuel_burned_gal"] = round2(boiler["total_fuel_burned_gal"] - entry["fuel_burned_gal"])
    boiler["total_blowdown_gal"] = round2(boiler["total_blowdown_gal"] - entry["blowdown_gal"])
    boiler["total_feedwater_gal"] = round2(boiler["total_feedwater_gal"] - entry["feedwater_intake_gal"])
    recompute_efficiency(plant, boiler)
    set_header_pressure(plant)
    check_water_drift(plant, boiler, actor_id)
    touch(boiler)
    touch(plant)


# ---------------------------------------------------------------------------
# water mass balance (PRD 2.10): drift beyond 25 gal raises a MEDIUM incident
# ---------------------------------------------------------------------------
def check_water_drift(plant, boiler, actor_id):
    lhs = round2(boiler["total_feedwater_gal"])
    rhs = round2(boiler["total_blowdown_gal"] + boiler["total_steam_lb"] / LB_PER_GAL_WATER)
    drift = round2(abs(lhs - rhs))
    if drift > DRIFT_TOLERANCE_GAL:
        create_incident_record(
            plant,
            severity="MEDIUM",
            kind="CHEMISTRY_EXCURSION",
            triggered_boiler_id=boiler["id"],
            raised_by=actor_id,
            raised_at=clock.now(),
        )


# ---------------------------------------------------------------------------
# incidents
# ---------------------------------------------------------------------------
def create_incident_record(plant, severity, kind, triggered_boiler_id, raised_by, raised_at):
    rec = new_record()
    rec.update({
        "plant_id": plant["id"],
        "raised_by_operator_id": raised_by,
        "severity": severity,
        "kind": kind,
        "triggered_boiler_id": triggered_boiler_id,
        "raised_at": raised_at,
        "status": "OPEN",
        "resolution_notes": None,
    })
    store.incidents[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# trip cascade (PRD 3.9): depth 1 trip/lead/posture, depth 2 dispatch cancel,
# depth 3 lag-dispatch re-evaluation with auto-created replacement window
# ---------------------------------------------------------------------------
def create_dispatch_record(plant, start, end, target, assigned):
    rec = new_record()
    rec.update({
        "plant_id": plant["id"],
        "window_start_at": start,
        "window_end_at": end,
        "target_steam_lb_hr": target,
        "assigned_boiler_ids": list(assigned),
        "expected_lead_boiler_id": compute_lead(plant),
        "status": "SCHEDULED",
    })
    store.dispatches[rec["id"]] = rec
    return rec


def trip_boiler(plant, boiler, suspend_cert=False):
    changed = False
    if boiler["ops_status"] in ("STANDBY", "WARMING", "ONLINE", "BANKING"):
        boiler["ops_status"] = "TRIPPED"
        boiler["_tripped_event"] = store.next_event()
        changed = True
    if suspend_cert and boiler["cert_status"] != "SUSPENDED":
        boiler["cert_status"] = "SUSPENDED"
        boiler["_suspended_event"] = store.next_event()
        changed = True
    if changed:
        touch(boiler)
    plant_dirty = set_lead(plant)
    plant_dirty |= set_header_pressure(plant)
    plant_dirty |= set_posture(plant)
    if plant_dirty:
        touch(plant)
    now = clock.now()
    for d in dispatches_of(plant["id"]):
        if (d["status"] == "SCHEDULED" and boiler["id"] in d["assigned_boiler_ids"]
                and d["window_start_at"] > now):
            d["status"] = "CANCELLED"
            touch(d)
            # depth 3: lag-dispatch re-evaluation within a 15-minute horizon
            if (d["window_start_at"] - now).total_seconds() <= LAG_REEVAL_WINDOW_SECONDS:
                cands = [b for b in boilers_of(plant["id"]) if _eligible(b)]
                if cands:
                    ranked = _rank(cands, plant["lead_boiler_id"])
                    create_dispatch_record(
                        plant, d["window_start_at"], d["window_end_at"],
                        d["target_steam_lb_hr"], [b["id"] for b in ranked])


# ---------------------------------------------------------------------------
# water chemistry (PRD 3.3)
# ---------------------------------------------------------------------------
def _log_cycles(log):
    return round2(log["conductivity_boiler_umho"] / log["conductivity_feedwater_umho"])


def _log_in_spec(log):
    cyc = _log_cycles(log)
    return (cyc <= MAX_CYCLES
            and log["sulfite_residual_ppm"] >= SULFITE_MIN_PPM
            and PHOSPHATE_MIN_PPM <= log["phosphate_residual_ppm"] <= PHOSPHATE_MAX_PPM)


def apply_chemistry_log(plant, boiler, log, actor_id):
    """Recompute cycles_of_concentration and drive the water_status dimension,
    including the ONLINE->BANKING load shed, the CRITICAL forced standby, and
    the auto-created HIGH CHEMISTRY_EXCURSION incident."""
    boiler["cycles_of_concentration"] = _log_cycles(log)
    in_spec = _log_in_spec(log)
    severe = _log_cycles(log) > MAX_CYCLES * CRITICAL_CYCLES_FACTOR
    ops_changed = False
    if not in_spec:
        boiler["_oos_streak"] = boiler.get("_oos_streak", 0) + 1
        boiler["_recovery_streak"] = 0
        if boiler["water_status"] == "IN_SPEC":
            boiler["water_status"] = "OUT_OF_SPEC"
            if boiler["ops_status"] == "ONLINE":
                boiler["ops_status"] = "BANKING"
                ops_changed = True
        if boiler["water_status"] == "OUT_OF_SPEC" and (
                severe or boiler["_oos_streak"] >= CHEMISTRY_CRITICAL_COUNT):
            boiler["water_status"] = "CRITICAL"
            if boiler["ops_status"] in ("ONLINE", "BANKING", "WARMING"):
                boiler["ops_status"] = "STANDBY"
                ops_changed = True
            create_incident_record(
                plant, severity="HIGH", kind="CHEMISTRY_EXCURSION",
                triggered_boiler_id=boiler["id"], raised_by=actor_id,
                raised_at=clock.now())
    else:
        if boiler["water_status"] == "OUT_OF_SPEC":
            boiler["water_status"] = "IN_SPEC"
            boiler["_oos_streak"] = 0
            boiler["_recovery_streak"] = 0
        elif boiler["water_status"] == "CRITICAL":
            boiler["_recovery_streak"] = boiler.get("_recovery_streak", 0) + 1
            if boiler["_recovery_streak"] >= CHEMISTRY_RECOVERY_COUNT:
                boiler["water_status"] = "IN_SPEC"
                boiler["_oos_streak"] = 0
                boiler["_recovery_streak"] = 0
        else:
            boiler["_oos_streak"] = 0
    plant_dirty = False
    if ops_changed:
        plant_dirty |= set_lead(plant)
        plant_dirty |= set_header_pressure(plant)
    plant_dirty |= set_posture(plant)
    touch(boiler)
    if plant_dirty:
        touch(plant)
    # 7-step blowdown recommendation chain (internal; not a serialized field)
    log["_blowdown_rec"] = compute_blowdown(boiler, log)


def compute_blowdown(boiler, log):
    """PRD 3.3 pinned chain. Step 5 rounds the flow to 2dp half-up and step 6
    multiplies the ROUNDED value by 24; step 7 clamps to [5.0, 5000.0]."""
    cond_b = log["conductivity_boiler_umho"]
    cond_f = log["conductivity_feedwater_umho"]
    cycles = cond_b / cond_f                                   # step 1
    if cycles <= TARGET_CYCLES:
        bd_pct = 0.0                                           # step 2 (floor at 0)
    else:
        bd_pct = max(0.0, (cycles - TARGET_CYCLES) / (cycles - 1.0)) * 100.0
    ref = log["recorded_at"]
    cutoff = ref - timedelta(hours=24)
    steam24 = sum(                                             # step 3
        e["steam_generated_lb"]
        for e in entries_of(boiler["id"])
        if e["status"] == "VERIFIED" and cutoff <= e["recorded_at"] <= ref
    )
    steam_rate = steam24 / 24.0
    frac = bd_pct / 100.0
    denom = 1.0 - frac
    if denom <= 0:
        bd_flow = float("inf")                                 # step 4 (degenerate)
    else:
        bd_flow = frac * steam_rate * LB_PER_GAL_WATER / denom
    bd_flow = round2(bd_flow)                                  # step 5
    bd_vol = bd_flow * 24.0                                    # step 6 (rounded input)
    bd_vol = min(max(bd_vol, BLOWDOWN_MIN_GAL_DAY), BLOWDOWN_MAX_GAL_DAY)  # step 7
    return round2(bd_vol)


def recompute_water_from_logs(boiler):
    """Void path (PRD 3.3): replay remaining non-VOIDED logs without side
    effects; zero remaining logs resets water_status to IN_SPEC outright."""
    logs = sorted(
        (l for l in chemlogs_of(boiler["id"]) if l["status"] != "VOIDED"),
        key=lambda l: (l["recorded_at"], l["_seq"]),
    )
    if not logs:
        boiler["cycles_of_concentration"] = 1.0
        boiler["water_status"] = "IN_SPEC"
        boiler["_oos_streak"] = 0
        boiler["_recovery_streak"] = 0
        return
    boiler["cycles_of_concentration"] = _log_cycles(logs[-1])
    water = "IN_SPEC"
    oos = 0
    rec = 0
    for l in logs:
        if not _log_in_spec(l):
            oos += 1
            rec = 0
            if water == "IN_SPEC":
                water = "OUT_OF_SPEC"
            if water == "OUT_OF_SPEC" and (
                    _log_cycles(l) > MAX_CYCLES * CRITICAL_CYCLES_FACTOR
                    or oos >= CHEMISTRY_CRITICAL_COUNT):
                water = "CRITICAL"
        else:
            if water == "OUT_OF_SPEC":
                water = "IN_SPEC"
                oos = 0
                rec = 0
            elif water == "CRITICAL":
                rec += 1
                if rec >= CHEMISTRY_RECOVERY_COUNT:
                    water = "IN_SPEC"
                    oos = 0
                    rec = 0
            else:
                oos = 0
    boiler["water_status"] = water
    boiler["_oos_streak"] = oos
    boiler["_recovery_streak"] = rec


# ---------------------------------------------------------------------------
# steam-trap loss (PRD 3.7): Napier default; Grashof for NY
# ---------------------------------------------------------------------------
def trap_method(plant):
    return "grashof_empirical" if plant["state_code"] == "NY" else "napier_theoretical"


def trap_leak_rate(plant, trap):
    d = trap["orifice_diameter_in"]
    p = trap["design_pressure_psi"]
    if plant["state_code"] == "NY":
        return round2(GRASHOF_COEFF * d * d * (p ** 0.5))
    return round2(NAPIER_COEFF * d * d * p)


def fuel_price_per_gal(plant):
    deliveries = deliveries_of(plant["id"])
    priced = [f for f in deliveries if f.get("_price_per_gal") is not None]
    if not priced:
        return DEFAULT_FUEL_COST_PER_GAL
    latest = max(priced, key=lambda f: (f["delivered_at"], f["_seq"]))
    return latest["_price_per_gal"]


def trap_loss_projection(plant, trap):
    leak = trap["leak_rate_lb_hr"]
    annual = round2(leak * HOURS_PER_YEAR)
    cost = round2(annual * (fuel_price_per_gal(plant) / FUEL_HHV_BTU_PER_GAL)
                  * (ENTHALPY_STEAM_BTU_PER_LB - ENTHALPY_FEEDWATER_BTU_PER_LB))
    return {
        "leak_rate_lb_hr": leak,
        "annual_steam_loss_lb": annual,
        "annual_cost_usd": cost,
        "method": trap_method(plant),
    }


# ---------------------------------------------------------------------------
# certificate & license expiry rules (PRD 3.2 / 3.6; second precision)
# ---------------------------------------------------------------------------
def certificate_status_for(boiler, now):
    """Boundary-precise: expiry == now is NOT lapsed (strict <); remaining
    exactly 30 days IS expiring (inclusive <=). A latest-FAILED annual lapses
    at the checkpoint; a PASSED with null expiry (pop test, post-incident)
    also lapses per the literal any-kind rule of PRD 3.6."""
    annuals = [i for i in inspections_of(boiler["id"])
               if i["inspection_kind"] in ANNUAL_KINDS and i["outcome"] in ("PASSED", "FAILED")]
    latest_annual = None
    for i in annuals:
        if latest_annual is None or i.get("_outcome_event", 0) > latest_annual.get("_outcome_event", 0):
            latest_annual = i
    if latest_annual is not None and latest_annual["outcome"] == "FAILED":
        return "LAPSED"
    passed = [i for i in inspections_of(boiler["id"]) if i["outcome"] == "PASSED"]
    latest_passed = None
    for i in passed:
        if latest_passed is None or i.get("_outcome_event", 0) > latest_passed.get("_outcome_event", 0):
            latest_passed = i
    if latest_passed is None:
        return "LAPSED"
    exp = latest_passed["certificate_expires_on"]
    if exp is None:
        return "LAPSED"
    if exp < now:
        return "LAPSED"
    if (exp - now).total_seconds() <= CERT_EXPIRING_WINDOW_SECONDS:
        return "EXPIRING"
    return "VALID"


def license_status_for(op, now):
    exp = op["license_expires_on"]
    if exp < now:
        return "EXPIRED"
    if (exp - now).total_seconds() <= LICENSE_EXPIRING_WINDOW_SECONDS:
        return "EXPIRING"
    return "ACTIVE"


# ---------------------------------------------------------------------------
# operations checkpoint (PRD 2.4): five effects, in effect together
# ---------------------------------------------------------------------------
def run_ops(plant):
    now = clock.now()
    plant["ops_run_index"] += 1

    # 1. operator licenses (REVOKED is terminal and never recomputed)
    for op in operators_of(plant["id"]):
        if op["license_status"] == "REVOKED":
            continue
        new = license_status_for(op, now)
        if new != op["license_status"]:
            op["license_status"] = new
            touch(op)

    # 2. boiler certificates (SUSPENDED runs on its own track: only a PASSED
    #    POST_INCIDENT inspection restores it, never the checkpoint)
    plant_dirty = False
    for b in boilers_of(plant["id"]):
        if b["cert_status"] == "SUSPENDED":
            continue
        new = certificate_status_for(b, now)
        if new != b["cert_status"]:
            b["cert_status"] = new
            if new == "LAPSED" and b["ops_status"] in ("WARMING", "ONLINE", "BANKING"):
                # emergency auto-shutdown on lapse
                b["ops_status"] = "STANDBY"
            touch(b)
            plant_dirty |= set_lead(plant)
            plant_dirty |= set_header_pressure(plant)

    # 3. dispatch windows: activate on clock entering [start, end); a window
    #    whose boilers fail the readiness test CANCELS instead; complete ACTIVE
    #    windows whose end the clock has reached or passed
    for d in dispatches_of(plant["id"]):
        if d["status"] == "SCHEDULED" and d["window_start_at"] <= now < d["window_end_at"]:
            ready = all(
                store.boilers.get(bid) is not None
                and store.boilers[bid]["ops_status"] in ("ONLINE", "BANKING", "WARMING")
                for bid in d["assigned_boiler_ids"]
            )
            if ready:
                d["status"] = "ACTIVE"
                touch(d)
                prefer = d["assigned_boiler_ids"][0] if d["assigned_boiler_ids"] else None
                plant_dirty |= set_lead(plant, prefer_id=prefer)
            else:
                d["status"] = "CANCELLED"
                touch(d)
                plant_dirty |= set_lead(plant)
        elif d["status"] == "ACTIVE" and now >= d["window_end_at"]:
            d["status"] = "COMPLETED"
            touch(d)

    # 4. posture
    plant_dirty |= set_posture(plant)

    # 5. ops_run_index always advanced above -> exactly one plant version bump
    touch(plant)
    return plant


# ---------------------------------------------------------------------------
# inspection outcome application (PRD 3.6)
# ---------------------------------------------------------------------------
def apply_outcome(plant, boiler, insp, outcome, certificate_number,
                  certificate_expires_on, lift_pressure):
    """Returns nothing; mutates. A pop test recorded PASSED whose lift falls
    outside the closed envelope is FORCED to FAILED (with the two cascades);
    an explicit FAILED pop test carries the same cascades."""
    now = clock.now()
    insp["_outcome_event"] = store.next_event()
    final = outcome

    forced_fail = False
    if outcome == "PASSED" and insp["inspection_kind"] == "RELIEF_VALVE_POP":
        setpoint = Decimal(repr(boiler["relief_valve_setpoint_psi"]))
        tol = Decimal(repr(boiler["relief_valve_tolerance_pct"]))
        upper = setpoint * (Decimal(1) + tol / Decimal(100))
        lift = Decimal(repr(float(lift_pressure)))
        if lift < setpoint or lift > upper:
            forced_fail = True
            final = "FAILED"

    insp["outcome"] = final
    if lift_pressure is not None and insp["inspection_kind"] == "RELIEF_VALVE_POP":
        insp["relief_valve_lift_pressure_psi"] = float(lift_pressure)
    if final == "PASSED" and insp["inspection_kind"] in ANNUAL_KINDS:
        insp["certificate_number"] = certificate_number
        insp["certificate_expires_on"] = certificate_expires_on
    touch(insp)

    boiler_changed = False
    if final == "PASSED":
        if insp["inspection_kind"] in ANNUAL_KINDS:
            exp = insp["certificate_expires_on"]
            if exp is not None and exp > now:
                if insp["inspection_kind"] == "ANNUAL_EXTERNAL":
                    # external restores from VALID/EXPIRING/LAPSED alike
                    if boiler["cert_status"] in ("VALID", "EXPIRING", "LAPSED"):
                        if boiler["cert_status"] != "VALID":
                            boiler["cert_status"] = "VALID"
                            boiler_changed = True
                else:
                    # internal restores EXPIRING only; never LAPSED, never SUSPENDED
                    if boiler["cert_status"] == "EXPIRING":
                        boiler["cert_status"] = "VALID"
                        boiler_changed = True
        elif insp["inspection_kind"] == "POST_INCIDENT":
            if (boiler["cert_status"] == "SUSPENDED"
                    and insp["_outcome_event"] > boiler.get("_suspended_event", -1)):
                boiler["cert_status"] = "VALID"
                boiler_changed = True
        # a passed RELIEF_VALVE_POP by itself never moves the cert dimension
    if forced_fail or (final == "FAILED" and insp["inspection_kind"] == "RELIEF_VALVE_POP"):
        # depth 1: cert SUSPENDED; depth 2: ops forced TRIPPED (+trip cascade)
        trip_boiler(plant, boiler, suspend_cert=True)
        boiler_changed = False  # trip_boiler already touched the boiler
    if final == "CONDITIONAL":
        # auto-schedule a same-kind follow-up CONDITIONAL_FOLLOWUP_DAYS out
        follow = new_record()
        follow.update({
            "boiler_id": boiler["id"],
            "inspection_kind": insp["inspection_kind"],
            "scheduled_on": now + timedelta(days=CONDITIONAL_FOLLOWUP_DAYS),
            "inspector_name": insp["inspector_name"],
            "inspector_license_no": insp["inspector_license_no"],
            "relief_valve_lift_pressure_psi": None,
            "outcome": "PENDING",
            "certificate_number": None,
            "certificate_expires_on": None,
            "posted_at": None,
            "_outcome_event": None,
        })
        store.inspections[follow["id"]] = follow
    if boiler_changed:
        touch(boiler)
    # FAILED annual kinds leave the certificate to lapse at the next checkpoint
    # (handled by certificate_status_for); nothing immediate here.
    if set_posture(plant):
        touch(plant)
    return insp
