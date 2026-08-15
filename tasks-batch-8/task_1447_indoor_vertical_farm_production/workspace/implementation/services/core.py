"""Core domain services: constants, entity helpers, serializers, derived state."""

import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import raise_error
from util import fmt_dt, fmt_date, q2, q4, q0

# ------------------------------------------------------------------ constants
STRESS_EXTENSION_CAP = 5
HARVEST_READY_EARLY_HOURS = 48
GERMINATION_REPLANT_THRESHOLD = Decimal("75.0")

FIXTURE_KW_PER_TOWER = Decimal("0.6")
ENERGY_RATE_CENTS_PER_KWH = Decimal("11")
DEMAND_TIER1_LIMIT_KW = Decimal("500")
DEMAND_RATE_T1_CENTS_PER_KW = Decimal("900")
DEMAND_RATE_T2_CENTS_PER_KW = Decimal("1400")

SANITATION_INTERVAL_HOURS = 168
SANITATION_BUFFER_HOURS = 4
MIN_CYCLE_HOURS = 2
MAX_CYCLE_HOURS = 12
SANITATION_EARLY_START_MINUTES = 30
FOOD_SAFETY_RECENCY_HOURS = 72

ESCALATION_MULTIPLIER = Decimal("1.25")

PRODUCTIVITY = {"LEAFY_GREEN": Decimal("60"), "HERB": Decimal("40"), "FRUITING": Decimal("25")}
SHIFT_LENGTH_HOURS = Decimal("8")
OT_MULTIPLIER = Decimal("1.5")

REGULAR_HOURS_PER_WEEK = Decimal("40.0")
WEEKLY_HOURS_HARD_CAP = Decimal("48.00")

DOCK_MAX_SHIPMENTS_PER_DAY = 3

CROP_CATEGORIES = {"LEAFY_GREEN", "HERB", "FRUITING"}
ROLE_TYPES = {"HARVEST_CREW", "PACK_CREW", "SANITATION_CREW"}
CAUSE_CATEGORIES = {"PATHOGEN", "EQUIPMENT", "NUTRIENT", "CLIMATE", "HUMAN_ERROR"}
WEEKDAYS = {"MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
            "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6}
SCOPE_TYPES = {"FACILITY", "ZONE"}
SANITATION_RESULTS = {"PASSED", "FAILED"}
SAFETY_DECISIONS = {"RELEASED", "CONDEMNED"}

BATCH_GROW_STATES = {"SEEDED", "GROWING", "AT_RISK", "HARVEST_READY"}
BATCH_NONTERMINAL_FOR_RETIRE = {"PLANNED", "SEEDED", "GROWING", "AT_RISK", "HARVEST_READY", "HARVESTED"}


# ------------------------------------------------------------------ entity helpers
def new_id():
    return str(uuid.uuid4())


def stamp_new(entity, with_version=True):
    ts = fmt_dt(datetime.now(timezone.utc))
    entity["id"] = new_id()
    entity["created_at"] = ts
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = fmt_dt(datetime.now(timezone.utc))
    entity["version"] = entity.get("version", 0) + 1


def logical_now():
    return store.clock


# ------------------------------------------------------------------ lookups
def get_crop(cid):
    c = store.crops.get(cid)
    if c is None:
        raise_error("ERR_NOT_FOUND", "Crop not found")
    return c


def get_recipe(rid):
    r = store.recipes.get(rid)
    if r is None:
        raise_error("ERR_NOT_FOUND", "GrowRecipe not found")
    return r


def get_loop(lid):
    l = store.water_loops.get(lid)
    if l is None:
        raise_error("ERR_NOT_FOUND", "WaterLoop not found")
    return l


def get_rack(rid):
    r = store.racks.get(rid)
    if r is None:
        raise_error("ERR_NOT_FOUND", "Rack not found")
    return r


def get_tower(tid):
    t = store.towers.get(tid)
    if t is None:
        raise_error("ERR_NOT_FOUND", "Tower not found")
    return t


def get_batch(bid):
    b = store.batches.get(bid)
    if b is None:
        raise_error("ERR_NOT_FOUND", "GrowBatch not found")
    return b


def get_allocation(aid):
    a = store.allocations.get(aid)
    if a is None:
        raise_error("ERR_NOT_FOUND", "TowerAllocation not found")
    return a


def get_cycle(cid):
    c = store.sanitation_cycles.get(cid)
    if c is None:
        raise_error("ERR_NOT_FOUND", "SanitationCycle not found")
    return c


def get_contract(cid):
    c = store.contracts.get(cid)
    if c is None:
        raise_error("ERR_NOT_FOUND", "RetailContract not found")
    return c


def get_shipment(sid):
    s = store.shipments.get(sid)
    if s is None:
        raise_error("ERR_NOT_FOUND", "Shipment not found")
    return s


def get_line(lid):
    l = store.shipment_lines.get(lid)
    if l is None:
        raise_error("ERR_NOT_FOUND", "ShipmentLine not found")
    return l


def get_worker(wid):
    w = store.workers.get(wid)
    if w is None:
        raise_error("ERR_NOT_FOUND", "Worker not found")
    return w


def get_shift(sid):
    s = store.labor_shifts.get(sid)
    if s is None:
        raise_error("ERR_NOT_FOUND", "LaborShift not found")
    return s


def get_assignment(aid):
    a = store.shift_assignments.get(aid)
    if a is None:
        raise_error("ERR_NOT_FOUND", "ShiftAssignment not found")
    return a


def get_reading(rid):
    r = store.energy_readings.get(rid)
    if r is None:
        raise_error("ERR_NOT_FOUND", "EnergyMeterReading not found")
    return r


def get_failure(fid):
    f = store.failure_reports.get(fid)
    if f is None:
        raise_error("ERR_NOT_FOUND", "FailureReport not found")
    return f


def get_replant(rid):
    r = store.replant_requests.get(rid)
    if r is None:
        raise_error("ERR_NOT_FOUND", "ReplantRequest not found")
    return r


# ------------------------------------------------------------------ derived: water loop posture
def loop_posture(loop):
    """Derived on every read/mutation per sanitation_schedule calculation."""
    cycles = [c for c in store.sanitation_cycles.values() if c["water_loop_id"] == loop["id"]]
    if any(c["cycle_status"] == "IN_PROGRESS" for c in cycles):
        return "SANITATION_IN_PROGRESS"
    completed = [c for c in cycles if c["cycle_status"] in ("PASSED", "FAILED")]
    if completed:
        completed.sort(key=lambda c: (c["completed_at"], c["created_at"]))
        if completed[-1]["result"] == "FAILED":
            return "SANITATION_HOLD"
    due = loop.get("next_sanitation_due_at")
    if due is not None and logical_now() > due:
        return "SANITATION_DUE"
    return "IN_SERVICE"


def recompute_loop_schedule(loop):
    """Recompute last_passed_at / next_sanitation_due_at from PASSED cycles."""
    passed = [c for c in store.sanitation_cycles.values()
              if c["water_loop_id"] == loop["id"] and c["cycle_status"] == "PASSED"]
    if passed:
        passed.sort(key=lambda c: (c["completed_at"], c["created_at"]))
        loop["last_passed_at"] = passed[-1]["completed_at"]
        loop["next_sanitation_due_at"] = passed[-1]["completed_at"] + timedelta(hours=SANITATION_INTERVAL_HOURS)
    else:
        loop["last_passed_at"] = None
        loop["next_sanitation_due_at"] = None


def batches_on_loop(loop_id):
    """All batches occupying a tower on a rack of this loop.

    An allocation that has been RELEASED (e.g. by the harvest cascade) still ties
    the batch to the tower it grew on: PRD §3.4's quarantine cascade and the
    harvest-in-flight start gate both list HARVESTED (and PACKED) batches, states
    in which the batch's allocations are always released, so "occupying a tower on
    those racks" must cover allocations of any status.
    """
    rack_ids = {r["id"] for r in store.racks.values() if r["water_loop_id"] == loop_id}
    tower_ids = {t["id"] for t in store.towers.values() if t["rack_id"] in rack_ids}
    out = []
    for a in store.allocations.values():
        if a["tower_id"] in tower_ids:
            b = store.batches.get(a["batch_id"])
            if b is not None and b not in out:
                out.append(b)
    return out


# ------------------------------------------------------------------ derived: tower status
def tower_status(tower):
    """Clock-dependent projection: ALLOCATED iff an ACTIVE allocation covers now."""
    now = logical_now()
    for a in store.allocations.values():
        if a["tower_id"] == tower["id"] and a["allocation_status"] == "ACTIVE":
            if a["occupied_from_at"] <= now < a["occupied_to_at"]:
                return "ALLOCATED"
    return "IDLE"


def active_allocations_on_tower(tower_id):
    return [a for a in store.allocations.values()
            if a["tower_id"] == tower_id and a["allocation_status"] == "ACTIVE"]


def active_allocations_of_batch(batch_id):
    return [a for a in store.allocations.values()
            if a["batch_id"] == batch_id and a["allocation_status"] == "ACTIVE"]


def intervals_overlap_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; adjacency allowed."""
    return a_start < b_end and b_start < a_end


# ------------------------------------------------------------------ cascades
def release_allocation(alloc):
    """TowerAllocation ACTIVE -> RELEASED; tower -> IDLE; rack.occupied_towers -= 1."""
    if alloc["allocation_status"] != "ACTIVE":
        return
    alloc["allocation_status"] = "RELEASED"
    touch(alloc)
    rack = store.racks.get(store.towers[alloc["tower_id"]]["rack_id"])
    if rack is not None:
        rack["occupied_towers"] = max(0, rack.get("occupied_towers", 0) - 1)
        touch(rack)


def release_batch_allocations(batch):
    for a in active_allocations_of_batch(batch["id"]):
        release_allocation(a)


def batch_lines(batch_id):
    return [l for l in store.shipment_lines.values() if l["batch_id"] == batch_id]


def shipment_lines(shipment_id):
    return [l for l in store.shipment_lines.values() if l["shipment_id"] == shipment_id]


def recompute_shipment_aggregates(shipment):
    lines = shipment_lines(shipment["id"])
    reserved = sum((l["reserved_lb"] for l in lines if l["line_status"] in ("RESERVED", "PACKED", "SHORTED")), Decimal("0"))
    packed = sum((l["packed_lb"] or Decimal("0") for l in lines), Decimal("0"))
    shipped = sum((l["shipped_lb"] or Decimal("0") for l in lines), Decimal("0"))
    shipment["reserved_lb"] = q2(reserved)
    shipment["packed_lb"] = q2(packed)
    shipment["shipped_lb"] = q2(shipped)
    shipment["has_shortage"] = any(l["line_status"] == "SHORTED" for l in lines)
    # has_safety_block: true iff any non-RELEASED line's batch is not safety RELEASED
    block = False
    for l in lines:
        if l["line_status"] == "RELEASED":
            continue
        b = store.batches.get(l["batch_id"])
        if b is not None and b["safety_status"] != "RELEASED":
            block = True
            break
    shipment["has_safety_block"] = block


def recompute_batch_pools(batch):
    """reserved_lb and packed_available_lb per entity spec."""
    lines = batch_lines(batch["id"])
    reserved = sum((l["reserved_lb"] for l in lines if l["line_status"] == "RESERVED"), Decimal("0"))
    batch["reserved_lb"] = q2(reserved)
    packed_in_flight = sum(
        ((l["packed_lb"] or Decimal("0")) for l in lines if l["line_status"] in ("PACKED", "SHORTED", "SHIPPED")),
        Decimal("0"),
    )
    batch["packed_available_lb"] = q2(Decimal(batch.get("packed_lb") or 0) - reserved - packed_in_flight)


def release_line(line):
    """ShipmentLine {RESERVED, PACKED, SHORTED} -> RELEASED with batch pool recomputation."""
    if line["line_status"] not in ("RESERVED", "PACKED", "SHORTED"):
        return
    line["line_status"] = "RELEASED"
    touch(line)
    batch = store.batches.get(line["batch_id"])
    if batch is not None:
        recompute_batch_pools(batch)
        touch(batch)


def cancel_shipment_cascade(shipment, target_status="CANCELED"):
    """Cancel/expire: open lines released; batch pools recomputed."""
    if shipment["shipment_status"] not in ("RESERVED", "PACKED"):
        return
    for line in shipment_lines(shipment["id"]):
        release_line(line)
    shipment["shipment_status"] = target_status
    recompute_shipment_aggregates(shipment)
    touch(shipment)
    contract = store.contracts.get(shipment["contract_id"])
    if contract is not None:
        recompute_contract_week_reserved(contract)
        touch(contract)


def week_bounds_for_contract(contract, ref_date):
    """Return (week_start, week_end) 7-day half-open aligned to week_start_day containing ref_date."""
    anchor = WEEKDAYS[contract["week_start_day"]]
    delta = (ref_date.weekday() - anchor) % 7
    ws = ref_date - timedelta(days=delta)
    return ws, ws + timedelta(days=7)


def recompute_contract_week_reserved(contract):
    """week_reserved_lb: Σ reserved_lb of shipments in {RESERVED, PACKED} with ship_date in current week."""
    now_date = logical_now().date()
    ws, we = week_bounds_for_contract(contract, now_date)
    total = Decimal("0")
    for s in store.shipments.values():
        if s["contract_id"] != contract["id"]:
            continue
        if s["shipment_status"] not in ("RESERVED", "PACKED"):
            continue
        sd = s["ship_date"]
        if isinstance(sd, str):
            sd = date.fromisoformat(sd)
        if ws <= sd < we:
            total += s.get("reserved_lb") or Decimal("0")
    contract["week_reserved_lb"] = q2(total)


# ------------------------------------------------------------------ worker hours
def iso_week_bounds(d):
    """Monday 00:00 UTC .. next Monday 00:00 UTC containing date d."""
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=7)


def worker_hours_in_week(worker_id, week_start):
    total = Decimal("0")
    week_end = week_start + timedelta(days=7)
    for a in store.shift_assignments.values():
        if a["worker_id"] != worker_id or a["assignment_status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        shift = store.labor_shifts.get(a["shift_id"])
        if shift is None:
            continue
        sd = shift["shift_date"]
        if isinstance(sd, str):
            sd = date.fromisoformat(sd)
        if week_start <= sd < week_end:
            hours = Decimal(str((shift["end_at"] - shift["start_at"]).total_seconds())) / Decimal("3600")
            total += hours
    return q2(total)


def recompute_worker_weekly_hours(worker):
    ws, _ = iso_week_bounds(logical_now().date())
    worker["scheduled_hours_current_week"] = worker_hours_in_week(worker["id"], ws)


def recompute_shift_overtime(shift):
    """overtime_hours = max(0, Σ assigned workers' weekly hours after assignment - 40)."""
    assignments = [a for a in store.shift_assignments.values()
                   if a["shift_id"] == shift["id"] and a["assignment_status"] in ("ASSIGNED", "CONFIRMED")]
    sd = shift["shift_date"]
    if isinstance(sd, str):
        sd = date.fromisoformat(sd)
    ws, _ = iso_week_bounds(sd)
    total_ot = Decimal("0")
    for a in assignments:
        wh = worker_hours_in_week(a["worker_id"], ws)
        ot = wh - REGULAR_HOURS_PER_WEEK
        if ot > 0:
            total_ot += ot
    shift["overtime_hours"] = q2(total_ot)


# ------------------------------------------------------------------ serializers
def ser_crop(c):
    return {
        "id": c["id"], "crop_code": c["crop_code"], "display_name": c["display_name"],
        "category": c["category"], "margin_cents_per_lb": c["margin_cents_per_lb"],
        "floor_price_cents_per_lb": c["floor_price_cents_per_lb"],
        "crop_status": c["crop_status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_recipe(r):
    return {
        "id": r["id"], "crop_id": r["crop_id"],
        "light_hours_per_day": r["light_hours_per_day"],
        "light_ppfd_umol": r["light_ppfd_umol"],
        "ec_target_ms": float(r["ec_target_ms"]) if isinstance(r["ec_target_ms"], Decimal) else r["ec_target_ms"],
        "ph_target": float(r["ph_target"]) if isinstance(r["ph_target"], Decimal) else r["ph_target"],
        "temp_day_c": float(r["temp_day_c"]) if isinstance(r["temp_day_c"], Decimal) else r["temp_day_c"],
        "temp_night_c": float(r["temp_night_c"]) if isinstance(r["temp_night_c"], Decimal) else r["temp_night_c"],
        "humidity_pct": r["humidity_pct"], "co2_ppm": r["co2_ppm"],
        "days_to_harvest": r["days_to_harvest"],
        "expected_yield_lb_per_tower": float(r["expected_yield_lb_per_tower"]) if isinstance(r["expected_yield_lb_per_tower"], Decimal) else r["expected_yield_lb_per_tower"],
        "recipe_status": r["recipe_status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_loop(l):
    return {
        "id": l["id"], "loop_code": l["loop_code"],
        "posture": loop_posture(l),
        "last_passed_at": fmt_dt(l.get("last_passed_at")),
        "next_sanitation_due_at": fmt_dt(l.get("next_sanitation_due_at")),
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


def ser_rack(r):
    return {
        "id": r["id"], "rack_code": r["rack_code"], "water_loop_id": r["water_loop_id"],
        "zone": r["zone"], "tower_count": r["tower_count"],
        "occupied_towers": r["occupied_towers"],
        "rack_posture": r["rack_posture"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ser_tower(t):
    return {
        "id": t["id"], "rack_id": t["rack_id"], "tower_index": t["tower_index"],
        "tower_status": tower_status(t),
        "created_at": t["created_at"], "updated_at": t["updated_at"], "version": t["version"],
    }


def ser_batch(b):
    def f(v):
        return float(v) if isinstance(v, Decimal) else v
    return {
        "id": b["id"], "crop_id": b["crop_id"], "recipe_id": b.get("recipe_id"),
        "origin_replant_request_id": b.get("origin_replant_request_id"),
        "production_status": b["production_status"], "safety_status": b["safety_status"],
        "seeded_at": fmt_dt(b.get("seeded_at")),
        "germination_rate_pct": f(b.get("germination_rate_pct")),
        "yield_factor": f(b.get("yield_factor")),
        "replant_recommended": b.get("replant_recommended", False),
        "stress_extension_days": b.get("stress_extension_days", 0),
        "projected_harvest_at": fmt_dt(b.get("projected_harvest_at")),
        "projected_yield_lb": f(b.get("projected_yield_lb")),
        "harvested_at": fmt_dt(b.get("harvested_at")),
        "harvested_by_user_id": b.get("harvested_by_user_id"),
        "grade_a_lb": f(b.get("grade_a_lb")),
        "grade_b_lb": f(b.get("grade_b_lb")),
        "cull_lb": f(b.get("cull_lb")),
        "harvested_total_lb": f(b.get("harvested_total_lb")),
        "packed_available_lb": f(b.get("packed_available_lb")),
        "packed_lb": f(b.get("packed_lb")),
        "reserved_lb": f(b.get("reserved_lb")),
        "actual_cost_per_pound_cents": f(b.get("actual_cost_per_pound_cents")),
        "created_at": b["created_at"], "updated_at": b["updated_at"], "version": b["version"],
    }


def ser_allocation(a):
    return {
        "id": a["id"], "batch_id": a["batch_id"], "tower_id": a["tower_id"],
        "occupied_from_at": fmt_dt(a["occupied_from_at"]),
        "occupied_to_at": fmt_dt(a["occupied_to_at"]),
        "allocation_status": a["allocation_status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def ser_cycle(c):
    return {
        "id": c["id"], "water_loop_id": c["water_loop_id"],
        "parent_cycle_id": c.get("parent_cycle_id"),
        "scheduled_start_at": fmt_dt(c["scheduled_start_at"]),
        "scheduled_end_at": fmt_dt(c["scheduled_end_at"]),
        "started_at": fmt_dt(c.get("started_at")),
        "completed_at": fmt_dt(c.get("completed_at")),
        "result": c.get("result"),
        "coliform_cfu": c.get("coliform_cfu"),
        "result_recorded_by": c.get("result_recorded_by"),
        "cycle_status": c["cycle_status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_contract(c):
    return {
        "id": c["id"], "retailer_name": c["retailer_name"], "crop_id": c["crop_id"],
        "weekly_commitment_lb": c["weekly_commitment_lb"],
        "price_per_pound_cents": c["price_per_pound_cents"],
        "penalty_cents_per_short_lb": c["penalty_cents_per_short_lb"],
        "fill_rate_threshold": float(c["fill_rate_threshold"]) if isinstance(c["fill_rate_threshold"], Decimal) else c["fill_rate_threshold"],
        "week_start_day": c["week_start_day"],
        "start_date": fmt_date(c["start_date"]), "end_date": fmt_date(c["end_date"]),
        "contract_status": c["contract_status"],
        "next_unsettled_week_start": fmt_date(c.get("next_unsettled_week_start")),
        "consecutive_short_weeks": c.get("consecutive_short_weeks", 0),
        "week_reserved_lb": float(c.get("week_reserved_lb") or 0),
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_shipment(s):
    def f(v):
        return float(v) if isinstance(v, Decimal) else v
    return {
        "id": s["id"], "contract_id": s["contract_id"],
        "ship_date": fmt_date(s["ship_date"]),
        "window_start_at": fmt_dt(s["window_start_at"]),
        "window_end_at": fmt_dt(s["window_end_at"]),
        "shipment_status": s["shipment_status"],
        "reserved_lb": f(s.get("reserved_lb")),
        "packed_lb": f(s.get("packed_lb")),
        "shipped_lb": f(s.get("shipped_lb")),
        "has_shortage": s.get("has_shortage", False),
        "has_safety_block": s.get("has_safety_block", False),
        "invoice_total_cents": s.get("invoice_total_cents", 0),
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def ser_line(l):
    def f(v):
        return float(v) if isinstance(v, Decimal) else v
    return {
        "id": l["id"], "shipment_id": l["shipment_id"], "batch_id": l["batch_id"],
        "reserved_lb": f(l["reserved_lb"]),
        "packed_lb": f(l.get("packed_lb")),
        "shipped_lb": f(l.get("shipped_lb")),
        "line_status": l["line_status"],
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


def ser_worker(w):
    return {
        "id": w["id"], "full_name": w["full_name"],
        "certifications": w["certifications"],
        "hourly_rate_cents": w["hourly_rate_cents"],
        "scheduled_hours_current_week": float(w.get("scheduled_hours_current_week") or 0),
        "created_at": w["created_at"], "updated_at": w["updated_at"], "version": w["version"],
    }


def ser_shift(s):
    return {
        "id": s["id"], "shift_date": fmt_date(s["shift_date"]),
        "role_type": s["role_type"],
        "start_at": fmt_dt(s["start_at"]), "end_at": fmt_dt(s["end_at"]),
        "headcount_required": s["headcount_required"],
        "headcount_assigned": s.get("headcount_assigned", 0),
        "planned_hourly_rate_cents": s["planned_hourly_rate_cents"],
        "projected_labor_cost_cents": s.get("projected_labor_cost_cents", 0),
        "overtime_hours": float(s.get("overtime_hours") or 0),
        "shift_status": s["shift_status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"], "shift_id": a["shift_id"], "worker_id": a["worker_id"],
        "assignment_status": a["assignment_status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"],
    }


def ser_reading(r):
    def f(v):
        return float(v) if isinstance(v, Decimal) else v
    return {
        "id": r["id"], "scope_type": r["scope_type"], "zone": r.get("zone"),
        "period_start_at": fmt_dt(r["period_start_at"]),
        "period_end_at": fmt_dt(r["period_end_at"]),
        "kwh_consumed": f(r["kwh_consumed"]),
        "peak_demand_kw": f(r["peak_demand_kw"]),
        "created_at": r["created_at"],
    }


def ser_failure(f):
    return {
        "id": f["id"], "batch_id": f["batch_id"],
        "cause_category": f["cause_category"],
        "lost_lb_estimate": float(f["lost_lb_estimate"]) if isinstance(f["lost_lb_estimate"], Decimal) else f["lost_lb_estimate"],
        "triaged_by_user_id": f.get("triaged_by_user_id"),
        "report_status": f["report_status"],
        "created_at": f["created_at"], "updated_at": f["updated_at"], "version": f["version"],
    }


def ser_replant(r):
    return {
        "id": r["id"], "failure_id": r["failure_id"],
        "priority_score": float(r["priority_score"]) if isinstance(r["priority_score"], Decimal) else r["priority_score"],
        "towers_needed": r["towers_needed"],
        "replant_status": r["replant_status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }
