"""Routes: grow batches lifecycle, safety release, cost summary."""

from datetime import timedelta, datetime, timezone
from decimal import Decimal

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles, ALL_ROLES
from response import success, list_response
from util import (get_body, get_body_optional, pagination_params, parse_dt,
                  dec, q2)
from services.core import (
    stamp_new, touch, logical_now,
    get_batch, get_crop, ser_batch, ser_allocation, ser_failure, ser_line,
    active_allocations_of_batch, intervals_overlap_half_open,
    release_batch_allocations, batch_lines, recompute_batch_pools,
    recompute_shipment_aggregates, shipment_lines,
    STRESS_EXTENSION_CAP, HARVEST_READY_EARLY_HOURS, FOOD_SAFETY_RECENCY_HOURS,
)
from services.calculations import (
    yield_factor_for_rate, recompute_projected_yield,
    provisional_cost_per_pound, actual_cost_allocation,
    recompute_actual_costs_for_batch,
)

bp = Blueprint("batches", __name__)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ---------------------------------------------------------------- create
@bp.post("/batches")
def create_batch():
    require_roles("Grower")
    body = get_body({"crop_id", "tower_ids", "planned_seed_at"}, {"crop_id", "tower_ids"})
    crop_id = body["crop_id"]
    if not isinstance(crop_id, str):
        raise_error("ERR_INVALID_REQUEST", "crop_id must be a string")
    crop = store.crops.get(crop_id)
    if crop is None:
        raise_error("ERR_NOT_FOUND", "Crop not found")
    tower_ids = body["tower_ids"]
    if not isinstance(tower_ids, list) or not tower_ids or not all(isinstance(t, str) for t in tower_ids):
        raise_error("ERR_INVALID_REQUEST", "tower_ids must be a non-empty array of strings")
    if len(set(tower_ids)) != len(tower_ids):
        raise_error("ERR_INVALID_REQUEST", "tower_ids contains duplicates")
    # existence of towers (priority 4)
    towers = []
    for tid in tower_ids:
        t = store.towers.get(tid)
        if t is None:
            raise_error("ERR_NOT_FOUND", f"Tower {tid} not found")
        towers.append(t)
    planned_seed_at = None
    if "planned_seed_at" in body and body["planned_seed_at"] is not None:
        planned_seed_at = parse_dt(body["planned_seed_at"], "planned_seed_at")
    # reference coherence (priority 8)
    if crop["crop_status"] == "RETIRED":
        raise_error("ERR_CROP_RETIRED", "Crop is RETIRED")
    active_recipe = None
    for r in store.recipes.values():
        if r["crop_id"] == crop["id"] and r["recipe_status"] == "ACTIVE":
            active_recipe = r
            break
    if active_recipe is None:
        raise_error("ERR_NO_ACTIVE_RECIPE", "Crop has no ACTIVE recipe")
    # cross-entity posture: rack OPERATING (priority 6)
    for t in towers:
        rack = store.racks.get(t["rack_id"])
        if rack is None or rack["rack_posture"] != "OPERATING":
            raise_error("ERR_RACK_NOT_OPERATING", "Rack not OPERATING")
    from_at = planned_seed_at or logical_now()
    to_at = from_at + timedelta(days=active_recipe["days_to_harvest"])
    # overlap check (priority 9) — check ALL before committing ANY (atomicity)
    for t in towers:
        for a in store.allocations.values():
            if a["tower_id"] == t["id"] and a["allocation_status"] == "ACTIVE":
                if intervals_overlap_half_open(from_at, to_at, a["occupied_from_at"], a["occupied_to_at"]):
                    raise_error("ERR_TOWER_INTERVAL_OVERLAP", "Tower interval overlap")
    # create batch
    batch = stamp_new({
        "crop_id": crop["id"],
        "recipe_id": active_recipe["id"],
        "origin_replant_request_id": None,
        "production_status": "PLANNED",
        "safety_status": "PENDING",
        "seeded_at": None,
        "germination_rate_pct": None,
        "yield_factor": Decimal("1.00"),
        "replant_recommended": False,
        "stress_extension_days": 0,
        "projected_harvest_at": None,
        "projected_yield_lb": None,
        "harvested_at": None,
        "harvested_by_user_id": None,
        "grade_a_lb": None, "grade_b_lb": None, "cull_lb": None,
        "harvested_total_lb": None,
        "packed_available_lb": Decimal("0"),
        "packed_lb": Decimal("0"),
        "reserved_lb": Decimal("0"),
        "actual_cost_per_pound_cents": None,
        "tower_count_pin": len(towers),
    })
    store.batches[batch["id"]] = batch
    # initial projected yield with factor 1.00
    batch["projected_yield_lb"] = q2(
        Decimal(len(towers)) * Decimal(str(active_recipe["expected_yield_lb_per_tower"]))
    )
    # create allocations
    racks_touched = {}
    for t in towers:
        alloc = stamp_new({
            "batch_id": batch["id"], "tower_id": t["id"],
            "occupied_from_at": from_at, "occupied_to_at": to_at,
            "allocation_status": "ACTIVE",
        })
        store.allocations[alloc["id"]] = alloc
        rack = store.racks[t["rack_id"]]
        rack["occupied_towers"] = rack.get("occupied_towers", 0) + 1
        racks_touched[rack["id"]] = rack
    for rack in racks_touched.values():
        touch(rack)
    return success(ser_batch(batch), status=201)


# ---------------------------------------------------------------- reads
@bp.get("/batches")
def list_batches():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.batches.values())
    for key in ("crop_id", "recipe_id", "production_status", "safety_status", "origin_replant_request_id"):
        v = _q(key)
        if v is not None:
            items = [b for b in items if b.get(key) == v]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    return list_response(items, ser_batch, limit, offset)


@bp.get("/batches/<bid>")
def get_batch_route(bid):
    require_roles(*ALL_ROLES)
    return success(ser_batch(get_batch(bid)))


@bp.get("/batches/<bid>/allocations")
def list_batch_allocations(bid):
    require_roles(*ALL_ROLES)
    batch = get_batch(bid)
    limit, offset = pagination_params()
    items = [a for a in store.allocations.values() if a["batch_id"] == batch["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return list_response(items, ser_allocation, limit, offset)


@bp.get("/batches/<bid>/failure-reports")
def list_batch_failures(bid):
    require_roles(*ALL_ROLES)
    batch = get_batch(bid)
    limit, offset = pagination_params()
    items = [f for f in store.failure_reports.values() if f["batch_id"] == batch["id"]]
    items.sort(key=lambda f: (f["created_at"], f["id"]))
    return list_response(items, ser_failure, limit, offset)


@bp.get("/batches/<bid>/shipment-lines")
def list_batch_lines(bid):
    require_roles(*ALL_ROLES)
    batch = get_batch(bid)
    limit, offset = pagination_params()
    items = batch_lines(batch["id"])
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return list_response(items, ser_line, limit, offset)


@bp.get("/batches/<bid>/cost-summary")
def batch_cost_summary(bid):
    require_roles("FarmManager", "Grower", "ContractsManager")
    batch = get_batch(bid)
    prov = provisional_cost_per_pound(batch)
    recompute_actual_costs_for_batch(batch)
    actual = batch.get("actual_cost_per_pound_cents")
    energy_alloc = None
    demand_alloc = None
    reading_id = batch.get("_actual_reading_id")
    if reading_id and reading_id in store.energy_readings:
        result = actual_cost_allocation(batch, store.energy_readings[reading_id])
        if result is not None:
            energy_alloc, demand_alloc, actual = result
    return success({
        "provisional_cost_per_pound_cents": float(prov) if prov is not None else None,
        "actual_cost_per_pound_cents": float(actual) if isinstance(actual, Decimal) else actual,
        "projected_yield_lb": float(batch["projected_yield_lb"]) if isinstance(batch.get("projected_yield_lb"), Decimal) else batch.get("projected_yield_lb"),
        "harvested_total_lb": float(batch["harvested_total_lb"]) if isinstance(batch.get("harvested_total_lb"), Decimal) else batch.get("harvested_total_lb"),
        "energy_alloc_cents": energy_alloc,
        "demand_alloc_cents": demand_alloc,
    })


# ---------------------------------------------------------------- lifecycle actions
def _batch_racks(batch):
    racks = []
    for a in active_allocations_of_batch(batch["id"]):
        tower = store.towers.get(a["tower_id"])
        if tower is not None:
            rack = store.racks.get(tower["rack_id"])
            if rack is not None and rack not in racks:
                racks.append(rack)
    return racks


def _check_batch_racks_operating(batch):
    for rack in _batch_racks(batch):
        if rack["rack_posture"] != "OPERATING":
            raise_error("ERR_RACK_NOT_OPERATING", "Rack not OPERATING")


@bp.post("/batches/<bid>/seed")
def seed_batch(bid):
    require_roles("Grower")
    get_body_optional(set())
    batch = get_batch(bid)
    if batch["production_status"] != "PLANNED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch not PLANNED")
    _check_batch_racks_operating(batch)
    now = logical_now()
    recipe = store.recipes[batch["recipe_id"]]
    batch["seeded_at"] = now
    batch["projected_harvest_at"] = now + timedelta(days=recipe["days_to_harvest"])
    for a in active_allocations_of_batch(batch["id"]):
        a["occupied_from_at"] = now
        a["occupied_to_at"] = batch["projected_harvest_at"]
        touch(a)
    batch["production_status"] = "SEEDED"
    touch(batch)
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/germination-check")
def germination_check(bid):
    require_roles("Grower")
    body = get_body({"germination_rate_pct"}, {"germination_rate_pct"})
    batch = get_batch(bid)
    if batch["production_status"] != "SEEDED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch not SEEDED")
    rate = dec(body["germination_rate_pct"], "germination_rate_pct")
    if rate < 0 or rate > 100:
        raise_error("ERR_INVALID_REQUEST", "germination_rate_pct out of range")
    factor, replant = yield_factor_for_rate(rate)
    batch["germination_rate_pct"] = rate
    batch["yield_factor"] = factor
    batch["replant_recommended"] = replant
    recompute_projected_yield(batch)
    batch["production_status"] = "GROWING"
    touch(batch)
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/report-stress")
def report_stress(bid):
    require_roles("Grower")
    get_body_optional({"stress_note"})
    batch = get_batch(bid)
    if batch["production_status"] != "GROWING":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch not GROWING")
    if batch["stress_extension_days"] >= STRESS_EXTENSION_CAP:
        raise_error("ERR_STRESS_CAP_REACHED", "Stress extension cap reached")
    batch["stress_extension_days"] += 1
    batch["projected_harvest_at"] = batch["projected_harvest_at"] + timedelta(days=1)
    for a in active_allocations_of_batch(batch["id"]):
        a["occupied_to_at"] = a["occupied_to_at"] + timedelta(days=1)
        touch(a)
    batch["production_status"] = "AT_RISK"
    touch(batch)
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/recover")
def recover_batch(bid):
    require_roles("Grower")
    get_body_optional(set())
    batch = get_batch(bid)
    if batch["production_status"] != "AT_RISK":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch not AT_RISK")
    batch["production_status"] = "GROWING"
    touch(batch)
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/mark-harvest-ready")
def mark_harvest_ready(bid):
    require_roles("Grower")
    get_body_optional(set())
    batch = get_batch(bid)
    if batch["production_status"] not in ("GROWING", "AT_RISK"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch not GROWING/AT_RISK")
    now = logical_now()
    if now < batch["projected_harvest_at"] - timedelta(hours=HARVEST_READY_EARLY_HOURS):
        raise_error("ERR_HARVEST_NOT_DUE", "Harvest not due")
    batch["production_status"] = "HARVEST_READY"
    touch(batch)
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/harvest")
def harvest_batch(bid):
    user_id, _ = require_roles("Grower")
    body = get_body({"grade_a_lb", "grade_b_lb", "cull_lb"}, {"grade_a_lb", "grade_b_lb", "cull_lb"})
    batch = get_batch(bid)
    if batch["production_status"] != "HARVEST_READY":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch not HARVEST_READY")
    _check_batch_racks_operating(batch)
    ga = dec(body["grade_a_lb"], "grade_a_lb")
    gb = dec(body["grade_b_lb"], "grade_b_lb")
    gc = dec(body["cull_lb"], "cull_lb")
    if ga < 0 or gb < 0 or gc < 0:
        raise_error("ERR_INVALID_REQUEST", "grades must be non-negative")
    now = logical_now()
    batch["grade_a_lb"] = q2(ga)
    batch["grade_b_lb"] = q2(gb)
    batch["cull_lb"] = q2(gc)
    batch["harvested_total_lb"] = q2(ga + gb)
    batch["harvested_at"] = now
    batch["harvested_by_user_id"] = user_id
    batch["packed_available_lb"] = Decimal("0")
    batch["production_status"] = "HARVESTED"
    touch(batch)
    release_batch_allocations(batch)
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/fail")
def fail_batch(bid):
    require_roles("Grower")
    body = get_body({"cause_category", "lost_lb_estimate"}, {"cause_category"})
    batch = get_batch(bid)
    if batch["production_status"] not in ("PLANNED", "SEEDED", "GROWING", "AT_RISK", "HARVEST_READY"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch cannot be failed from this state")
    from util import req_enum
    from services.core import CAUSE_CATEGORIES
    cause = req_enum(body["cause_category"], "cause_category", CAUSE_CATEGORIES)
    lost = batch.get("projected_yield_lb")
    if "lost_lb_estimate" in body and body["lost_lb_estimate"] is not None:
        lost = dec(body["lost_lb_estimate"], "lost_lb_estimate")
        if lost < 0:
            raise_error("ERR_INVALID_REQUEST", "lost_lb_estimate must be non-negative")
        lost = q2(lost)
    batch["production_status"] = "FAILED"
    touch(batch)
    release_batch_allocations(batch)
    now = logical_now()
    failure = stamp_new({
        "batch_id": batch["id"],
        "cause_category": cause,
        "lost_lb_estimate": lost if lost is not None else Decimal("0"),
        "triaged_by_user_id": None,
        "report_status": "REPORTED",
    })
    failure["created_at_dt"] = now
    store.failure_reports[failure["id"]] = failure
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/cull")
def cull_batch(bid):
    require_roles("Grower")
    get_body_optional(set())
    batch = get_batch(bid)
    if batch["production_status"] not in ("PLANNED", "SEEDED", "GROWING", "AT_RISK", "HARVEST_READY"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch cannot be culled from this state")
    batch["production_status"] = "CULLED"
    touch(batch)
    release_batch_allocations(batch)
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/safety-release")
def safety_release(bid):
    user_id, _ = require_roles("QualityAssurance")
    body = get_body({"decision", "lab_ref"}, {"decision", "lab_ref"})
    batch = get_batch(bid)
    # segregation of duties (priority 3) — evaluated before state checks per tier order
    decision = body["decision"]
    if decision not in ("RELEASED", "CONDEMNED"):
        raise_error("ERR_INVALID_REQUEST", "decision must be RELEASED or CONDEMNED")
    if not isinstance(body["lab_ref"], str):
        raise_error("ERR_INVALID_REQUEST", "lab_ref must be a string")
    if batch.get("harvested_by_user_id") is not None and user_id == batch["harvested_by_user_id"]:
        raise_error("ERR_SEGREGATION_OF_DUTIES", "Harvester cannot release own batch")
    # state checks
    if decision == "RELEASED":
        if batch["production_status"] not in ("GROWING", "AT_RISK", "HARVEST_READY", "HARVESTED", "PACKED"):
            raise_error("ERR_INVALID_STATE_TRANSITION", "production_status does not permit release")
        if batch["safety_status"] not in ("PENDING", "QUARANTINED"):
            raise_error("ERR_INVALID_STATE_TRANSITION", "safety_status does not permit release")
        batch["safety_status"] = "RELEASED"
        touch(batch)
        # recompute has_safety_block on shipments with lines on this batch
        affected_shipments = {l["shipment_id"] for l in batch_lines(batch["id"])}
        for sid in affected_shipments:
            s = store.shipments.get(sid)
            if s is not None:
                recompute_shipment_aggregates(s)
                touch(s)
    else:  # CONDEMNED
        if batch["safety_status"] not in ("PENDING", "QUARANTINED", "RELEASED"):
            raise_error("ERR_INVALID_STATE_TRANSITION", "safety_status does not permit condemnation")
        batch["safety_status"] = "CONDEMNED"
        batch["packed_available_lb"] = Decimal("0")
        touch(batch)
        affected_shipments = {l["shipment_id"] for l in batch_lines(batch["id"])}
        for line in batch_lines(batch["id"]):
            if line["line_status"] in ("RESERVED", "PACKED", "SHORTED"):
                line["line_status"] = "RELEASED"
                touch(line)
        for sid in affected_shipments:
            s = store.shipments.get(sid)
            if s is None:
                continue
            recompute_shipment_aggregates(s)
            lines = shipment_lines(sid)
            if lines and all(l["line_status"] == "RELEASED" for l in lines) and s["shipment_status"] in ("RESERVED", "PACKED"):
                s["shipment_status"] = "CANCELED"
            touch(s)
    return success(ser_batch(batch))


@bp.post("/batches/<bid>/pack")
def pack_batch(bid):
    require_roles("Grower")
    body = get_body({"packed_lb"}, {"packed_lb"})
    batch = get_batch(bid)
    # lifecycle state (priority 5)
    if batch["production_status"] != "HARVESTED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Batch not HARVESTED")
    # food-safety gates (priority 7)
    if batch["safety_status"] == "PENDING":
        raise_error("ERR_BATCH_SAFETY_PENDING", "Batch safety PENDING")
    if batch["safety_status"] == "QUARANTINED":
        raise_error("ERR_BATCH_QUARANTINED", "Batch QUARANTINED")
    if batch["safety_status"] == "CONDEMNED":
        raise_error("ERR_BATCH_CONDEMNED", "Batch CONDEMNED")
    now = logical_now()
    if batch["harvested_at"] is None or now.date() != batch["harvested_at"].date():
        raise_error("ERR_SAME_DAY_PACK_VIOLATION", "Pack must be same UTC date as harvest")
    # sanitation recency: loop via any allocated tower's rack
    loop_id = None
    allocs = [a for a in store.allocations.values() if a["batch_id"] == batch["id"]]
    for a in allocs:
        tower = store.towers.get(a["tower_id"])
        if tower is not None:
            rack = store.racks.get(tower["rack_id"])
            if rack is not None:
                loop_id = rack["water_loop_id"]
                break
    latest_pass = None
    if loop_id is not None:
        for c in store.sanitation_cycles.values():
            if c["water_loop_id"] == loop_id and c["cycle_status"] == "PASSED":
                if latest_pass is None or c["completed_at"] > latest_pass["completed_at"]:
                    latest_pass = c
    if latest_pass is None:
        raise_error("ERR_SANITATION_RECENCY_MISSING", "No PASSED sanitation cycle on loop")
    if (now - latest_pass["completed_at"]) > timedelta(hours=FOOD_SAFETY_RECENCY_HOURS):
        raise_error("ERR_SANITATION_RECENCY_MISSING", "Last PASS older than 72h")
    packed = dec(body["packed_lb"], "packed_lb")
    if packed <= 0 or packed > Decimal(str(batch["harvested_total_lb"])):
        raise_error("ERR_INVALID_REQUEST", "packed_lb must be > 0 and <= harvested_total_lb")
    batch["packed_lb"] = q2(packed)
    batch["packed_available_lb"] = q2(packed)
    batch["production_status"] = "PACKED"
    touch(batch)
    return success(ser_batch(batch))
