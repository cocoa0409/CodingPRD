"""LoadBatch, LoadAssignment, and LoadThermocoupleReading endpoints."""
from flask import Blueprint

import db
import validation as v
from db import store, new_id, new_common, new_evidence, touch
from errors import ApiError
from middleware import ANY_ROLES, get_context, require_roles
from response import Paginator, created, ok
from services import domain

bp = Blueprint("loads", __name__)


def _get_load(load_batch_id):
    return v.resolve_path(store.load_batches, load_batch_id, "ERR_LOAD_BATCH_NOT_FOUND")


def _check_occ(body, load):
    """Tier-5 optimistic concurrency on assignment writes (expected_load_batch_version)."""
    expected = body.get("expected_load_batch_version")
    if expected is not None and v.is_int(expected) and expected != load["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_load_batch_version does not equal the LoadBatch version")


@bp.post("/load-batches")
def create_load_batch():
    get_context()
    require_roles(["ShopScheduler"])
    body = v.get_body()

    # tier 4: body FK existence
    furnace = recipe = None
    if v.present(body, "furnace_id"):
        furnace = v.resolve_fk(store.furnaces, body.get("furnace_id"), "ERR_FURNACE_NOT_FOUND")
    if v.present(body, "recipe_id"):
        recipe = v.resolve_fk(store.recipes, body.get("recipe_id"), "ERR_RECIPE_NOT_FOUND")

    # tier 6 (safety): furnace class rank and quench-media compatibility
    if furnace is not None and recipe is not None:
        if domain.CLASS_RANK[furnace["furnace_class"]] > domain.CLASS_RANK[recipe["required_furnace_class"]]:
            raise ApiError("ERR_RECIPE_CLASS_MISMATCH", 422,
                           "Furnace class rank exceeds the recipe's required_furnace_class rank")
        if recipe["quench_media"] not in furnace["quench_media_supported"]:
            raise ApiError("ERR_QUENCH_MEDIA_INCOMPATIBLE", 422,
                           "Furnace does not support the recipe's quench_media")

    # tier 7 (referential): loads may only be built against APPROVED recipes
    if recipe is not None and recipe["status"] != "APPROVED":
        raise ApiError("ERR_RECIPE_NOT_APPROVED", 409, "Recipe is not APPROVED")

    # Parse the window when possible so tier-8 schedule gates can evaluate; malformed
    # values fall through to the tier-9 field checks.
    start = db.parse_iso(body.get("scheduled_start_at"))
    end = db.parse_iso(body.get("scheduled_end_at"))

    # tier 8 (temporal): committed-schedule overlap and quench purge gap
    if furnace is not None and recipe is not None and start is not None and end is not None and start < end:
        domain.check_schedule(furnace["id"], recipe, start, end)

    # tier 9 (constraint): required fields, datetime validity, start strictly before end
    if furnace is None:
        v.req_string(body, "furnace_id")  # raises ERR_INVALID_REQUEST
    if recipe is None:
        v.req_string(body, "recipe_id")  # raises ERR_INVALID_REQUEST
    start = v.req_datetime(body, "scheduled_start_at")
    end = v.req_datetime(body, "scheduled_end_at")
    if start >= end:
        raise ApiError("ERR_INVALID_REQUEST", 400, "scheduled_start_at must be before scheduled_end_at")

    load = {
        "id": new_id(),
        "furnace_id": furnace["id"],
        "recipe_id": recipe["id"],
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "status": "BUILDING",
        "total_weight_lb": 0,
        "out_of_spec": False,
        "total_energy_surcharge_cents": None,
        "started_at": None,
        "completed_at": None,
    }
    new_common(load)
    store.load_batches[load["id"]] = load
    return created(load)


@bp.get("/load-batches")
def list_load_batches():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.load_batches.values())
    rows = pg.filter(rows, "furnace_id")
    rows = pg.filter(rows, "recipe_id")
    rows = pg.filter(rows, "status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/load-batches/<load_batch_id>")
def get_load_batch(load_batch_id):
    get_context()
    require_roles(ANY_ROLES)
    return ok(_get_load(load_batch_id))


@bp.post("/load-batches/<load_batch_id>/assignments")
def create_assignment(load_batch_id):
    get_context()
    require_roles(["ShopScheduler"])
    body = v.get_body()
    load = _get_load(load_batch_id)
    # tier 4: body FK existence
    order = None
    if v.present(body, "work_order_id"):
        order = v.resolve_fk(store.work_orders, body.get("work_order_id"), "ERR_WORK_ORDER_NOT_FOUND")
    # tier 5 (state): assignment writes require BUILDING or HOLD
    if load["status"] not in ("BUILDING", "HOLD"):
        raise ApiError("ERR_LOAD_NOT_BUILDING", 409,
                       "Assignment writes require load status BUILDING or HOLD")
    # tier 5 (OCC): expected_load_batch_version must equal the current version
    _check_occ(body, load)
    # tier 5 (state): the order must be assignable
    if order is not None and order["processing_status"] not in ("RECEIVED", "AWAITING_RETREAT"):
        raise ApiError("ERR_WORK_ORDER_NOT_ASSIGNABLE", 409,
                       "Assignment requires processing_status in {RECEIVED, AWAITING_RETREAT}")
    # tier 7 (referential): the order's recipe must match the load's recipe
    if order is not None and order["recipe_id"] != load["recipe_id"]:
        raise ApiError("ERR_RECIPE_MISMATCH", 422,
                       "Work order's recipe_id differs from the load's recipe_id")
    # tier 9 (constraint): required fields and weight capacity (strictly-greater rejects;
    # a total exactly equal to max_load_weight_lb is allowed)
    if order is None:
        v.req_string(body, "work_order_id")  # raises ERR_INVALID_REQUEST
    if body.get("expected_load_batch_version") is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_load_batch_version is required")
    furnace = store.furnaces.get(load["furnace_id"])
    new_total = domain.load_weight(load["id"]) + domain.dec(order["received_weight_lb"])
    if furnace is not None and new_total > domain.dec(furnace["max_load_weight_lb"]):
        raise ApiError("ERR_LOAD_WEIGHT_EXCEEDED", 422,
                       "Assignment would push total_weight_lb above the furnace capacity")

    assignment = {
        "id": new_id(),
        "load_batch_id": load["id"],
        "work_order_id": order["id"],
        "status": "ACTIVE",
        "assigned_at": db.clock(),
    }
    new_common(assignment)
    store.load_assignments[assignment["id"]] = assignment
    # Side effects: order RECEIVED/AWAITING_RETREAT -> SCHEDULED; weight recompute; version bump.
    order["processing_status"] = "SCHEDULED"
    touch(order)
    domain.recompute_load_weight(load)
    touch(load)
    return created(assignment)


@bp.post("/load-batches/<load_batch_id>/assignments/<assignment_id>/unassign")
def unassign(load_batch_id, assignment_id):
    get_context()
    require_roles(["ShopScheduler"])
    body = v.get_body()
    # tier 4: path identifiers left to right — load, then assignment on this load
    load = _get_load(load_batch_id)
    assignment = store.load_assignments.get(assignment_id)
    if assignment is None or assignment["load_batch_id"] != load["id"]:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", 404,
                       "LoadAssignment does not exist on this load")
    # tier 5 (state): direct unassign requires BUILDING or HOLD
    if load["status"] not in ("BUILDING", "HOLD"):
        raise ApiError("ERR_LOAD_NOT_BUILDING", 409,
                       "Unassign requires load status BUILDING or HOLD")
    # tier 5 (OCC)
    _check_occ(body, load)
    # tier 9: expected_load_batch_version is a required field
    if body.get("expected_load_batch_version") is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_load_batch_version is required")
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_REQUEST", 400, "Assignment is not ACTIVE")

    assignment["status"] = "REMOVED"
    touch(assignment)
    order = store.work_orders.get(assignment["work_order_id"])
    if order is not None:
        # Revert target depends on re-treat history.
        order["processing_status"] = "AWAITING_RETREAT" if order["retreat_count"] > 0 else "RECEIVED"
        touch(order)
    domain.recompute_load_weight(load)
    touch(load)
    return ok(assignment)


@bp.get("/load-assignments")
def list_assignments():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.load_assignments.values())
    rows = pg.filter(rows, "load_batch_id")
    rows = pg.filter(rows, "work_order_id")
    rows = pg.filter(rows, "status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/load-assignments/<assignment_id>")
def get_assignment(assignment_id):
    get_context()
    require_roles(ANY_ROLES)
    return ok(v.resolve_path(store.load_assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND"))


@bp.post("/load-batches/<load_batch_id>/release")
def release_load(load_batch_id):
    get_context()
    require_roles(["ShopScheduler"])
    load = _get_load(load_batch_id)
    # tier 5 (state): release requires BUILDING
    if load["status"] != "BUILDING":
        raise ApiError("ERR_LOAD_NOT_BUILDING", 409, "Release requires load status BUILDING")
    furnace = store.furnaces.get(load["furnace_id"])
    recipe = store.recipes.get(load["recipe_id"])
    # tier 6 (safety): furnace posture recomputed against the logical clock right now
    if furnace is None or domain.recompute_posture(furnace) != "QUALIFIED":
        raise ApiError("ERR_FURNACE_NOT_QUALIFIED", 422,
                       "Furnace qualification_status is not QUALIFIED")
    # tier 7 (referential): recipe must still be APPROVED
    if recipe is None or recipe["status"] != "APPROVED":
        raise ApiError("ERR_RECIPE_NOT_APPROVED", 409, "Recipe is not APPROVED")
    # tier 8 (temporal): pyrometry validity containment, then schedule overlap / purge gap
    domain.check_pyrometry_window(furnace, load["scheduled_start_at"], load["scheduled_end_at"])
    domain.check_schedule(furnace["id"], recipe, load["scheduled_start_at"], load["scheduled_end_at"],
                          exclude_load_id=load["id"])
    # tier 9 (constraint): non-empty load
    if not domain.active_assignments(load["id"]):
        raise ApiError("ERR_EMPTY_LOAD", 422, "Release requires at least one ACTIVE assignment")
    load["status"] = "RELEASED"
    touch(load)
    return ok(load)


@bp.post("/load-batches/<load_batch_id>/start-run")
def start_run(load_batch_id):
    get_context()
    require_roles(["FurnaceOperator"])
    load = _get_load(load_batch_id)
    # tier 5 (state)
    if load["status"] != "RELEASED":
        raise ApiError("ERR_LOAD_NOT_RELEASED", 409, "start-run requires load status RELEASED")
    # tier 6 (safety): the furnace must still be QUALIFIED
    furnace = store.furnaces.get(load["furnace_id"])
    if furnace is None or domain.recompute_posture(furnace) != "QUALIFIED":
        raise ApiError("ERR_FURNACE_NOT_QUALIFIED", 422,
                       "Furnace qualification_status is not QUALIFIED")
    load["status"] = "RUNNING"
    load["started_at"] = db.clock()
    touch(load)
    for a in domain.active_assignments(load["id"]):
        order = store.work_orders.get(a["work_order_id"])
        if order is not None and order["processing_status"] == "SCHEDULED":
            order["processing_status"] = "IN_PROCESS"
            touch(order)
    return ok(load)


@bp.post("/load-batches/<load_batch_id>/complete-run")
def complete_run(load_batch_id):
    get_context()
    require_roles(["FurnaceOperator"])
    load = _get_load(load_batch_id)
    # tier 5 (state)
    if load["status"] != "RUNNING":
        raise ApiError("ERR_LOAD_NOT_RUNNING", 409, "complete-run requires load status RUNNING")
    load["status"] = "COMPLETED"
    load["completed_at"] = db.clock()
    # calculations.tc_excursion_assessment: strictly-greater deviation marks the load
    recipe = store.recipes.get(load["recipe_id"])
    out_of_spec = False
    if recipe is not None:
        for r in store.thermocouple_readings.values():
            if r["load_batch_id"] == load["id"]:
                if abs(r["temp_f"] - recipe["soak_temp_f"]) > recipe["soak_tolerance_f"]:
                    out_of_spec = True
                    break
    load["out_of_spec"] = out_of_spec
    # calculations.energy_surcharge_settlement: round each order line first, then sum
    total = 0
    for a in domain.active_assignments(load["id"]):
        order = store.work_orders.get(a["work_order_id"])
        if order is not None and order["processing_status"] == "IN_PROCESS":
            order["processing_status"] = "PROCESSED"
            order["energy_surcharge_cents"] = domain.energy_surcharge_for(order)
            total += order["energy_surcharge_cents"]
            touch(order)
    load["total_energy_surcharge_cents"] = total
    touch(load)
    return ok(load)


@bp.post("/load-batches/<load_batch_id>/abort")
def abort_run(load_batch_id):
    get_context()
    require_roles(["FurnaceOperator"])
    load = _get_load(load_batch_id)
    # tier 5 (state)
    if load["status"] != "RUNNING":
        raise ApiError("ERR_LOAD_NOT_RUNNING", 409, "abort requires load status RUNNING")
    load["status"] = "ABORTED"
    for a in domain.active_assignments(load["id"]):
        a["status"] = "REMOVED"
        touch(a)
        order = store.work_orders.get(a["work_order_id"])
        if order is not None and order["processing_status"] == "IN_PROCESS":
            order["processing_status"] = "RECEIVED"
            touch(order)
    domain.recompute_load_weight(load)
    touch(load)
    return ok(load)


@bp.post("/thermocouple-readings")
def create_reading():
    get_context()
    require_roles(["FurnaceOperator"])
    body = v.get_body()
    # tier 4: body FK existence
    load = None
    if v.present(body, "load_batch_id"):
        load = v.resolve_fk(store.load_batches, body.get("load_batch_id"), "ERR_LOAD_BATCH_NOT_FOUND")
    # tier 5 (state): readings are accepted only while the load is RUNNING
    if load is not None and load["status"] != "RUNNING":
        raise ApiError("ERR_LOAD_NOT_RUNNING", 409,
                       "Thermocouple readings require load status RUNNING")
    # tier 9: required fields
    if load is None:
        v.req_string(body, "load_batch_id")  # raises ERR_INVALID_REQUEST
    channel = v.req_string(body, "channel")
    recorded_at = v.req_datetime(body, "recorded_at")
    temp_f = v.req_int(body, "temp_f")
    reading = {
        "id": new_id(),
        "load_batch_id": load["id"],
        "channel": channel,
        "recorded_at": recorded_at,
        "temp_f": temp_f,
    }
    new_evidence(reading)
    store.thermocouple_readings[reading["id"]] = reading
    return created(reading)


@bp.get("/thermocouple-readings")
def list_readings():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.thermocouple_readings.values())
    rows = pg.filter(rows, "load_batch_id")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/thermocouple-readings/<reading_id>")
def get_reading(reading_id):
    get_context()
    require_roles(ANY_ROLES)
    return ok(v.resolve_path(store.thermocouple_readings, reading_id,
                             "ERR_THERMOCOUPLE_READING_NOT_FOUND"))
