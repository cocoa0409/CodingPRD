"""Routes: clock, crops, recipes, water loops, racks, towers."""

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles, ALL_ROLES
from response import success, list_response
from util import (get_body, get_body_optional, pagination_params, parse_dt, parse_date,
                  req_int, req_str, req_enum, dec)
from services.core import (
    stamp_new, touch, logical_now,
    get_crop, get_recipe, get_loop, get_rack, get_tower,
    ser_crop, ser_recipe, ser_loop, ser_rack, ser_tower, ser_allocation,
    loop_posture, CROP_CATEGORIES, BATCH_NONTERMINAL_FOR_RETIRE,
)

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------- clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("FarmManager")
    body = get_body({"to_iso8601"}, {"to_iso8601"})
    store.clock = parse_dt(body["to_iso8601"], "to_iso8601")
    return success({"current_utc": _fmt_clock()})


def _fmt_clock():
    from util import fmt_dt
    return fmt_dt(store.clock)


# ---------------------------------------------------------------- crops
@bp.post("/crops")
def create_crop():
    require_roles("FarmManager")
    body = get_body(
        {"crop_code", "display_name", "category", "margin_cents_per_lb", "floor_price_cents_per_lb"},
        {"crop_code", "display_name", "category", "margin_cents_per_lb", "floor_price_cents_per_lb"},
    )
    crop_code = req_str(body["crop_code"], "crop_code")
    display_name = req_str(body["display_name"], "display_name")
    category = req_enum(body["category"], "category", CROP_CATEGORIES)
    margin = req_int(body["margin_cents_per_lb"], "margin_cents_per_lb")
    floor = req_int(body["floor_price_cents_per_lb"], "floor_price_cents_per_lb")
    if margin < 0 or floor < 0:
        raise_error("ERR_INVALID_REQUEST", "money fields must be non-negative")
    for c in store.crops.values():
        if c["crop_code"] == crop_code:
            raise_error("ERR_DUPLICATE_CODE", "crop_code already exists")
    crop = stamp_new({
        "crop_code": crop_code, "display_name": display_name, "category": category,
        "margin_cents_per_lb": margin, "floor_price_cents_per_lb": floor,
        "crop_status": "ACTIVE",
    })
    store.crops[crop["id"]] = crop
    return success(ser_crop(crop), status=201)


@bp.get("/crops")
def list_crops():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.crops.values())
    category = _q("category")
    status = _q("crop_status")
    if category is not None:
        items = [c for c in items if c["category"] == category]
    if status is not None:
        items = [c for c in items if c["crop_status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return list_response(items, ser_crop, limit, offset)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.get("/crops/<cid>")
def get_crop_route(cid):
    require_roles(*ALL_ROLES)
    return success(ser_crop(get_crop(cid)))


@bp.post("/crops/<cid>/retire")
def retire_crop(cid):
    require_roles("FarmManager")
    crop = get_crop(cid)
    if crop["crop_status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Crop is not ACTIVE")
    for b in store.batches.values():
        if b["crop_id"] == cid and b["production_status"] in BATCH_NONTERMINAL_FOR_RETIRE:
            raise_error("ERR_CROP_IN_USE", "Crop has non-terminal batches")
    for c in store.contracts.values():
        if c["crop_id"] == cid and c["contract_status"] in ("ACTIVE", "SUSPENDED"):
            raise_error("ERR_CROP_IN_USE", "Crop has live contracts")
    crop["crop_status"] = "RETIRED"
    touch(crop)
    for r in store.recipes.values():
        if r["crop_id"] == cid and r["recipe_status"] == "DRAFT":
            r["recipe_status"] = "RETIRED"
            touch(r)
    return success(ser_crop(crop))


# ---------------------------------------------------------------- recipes
@bp.post("/recipes")
def create_recipe():
    require_roles("Grower")
    fields = {"crop_id", "light_hours_per_day", "light_ppfd_umol", "ec_target_ms", "ph_target",
              "temp_day_c", "temp_night_c", "humidity_pct", "co2_ppm", "days_to_harvest",
              "expected_yield_lb_per_tower"}
    body = get_body(fields, fields)
    crop = get_crop(body["crop_id"]) if isinstance(body["crop_id"], str) else _bad("crop_id")
    light_hours = req_int(body["light_hours_per_day"], "light_hours_per_day")
    light_ppfd = req_int(body["light_ppfd_umol"], "light_ppfd_umol")
    ec = dec(body["ec_target_ms"], "ec_target_ms")
    ph = dec(body["ph_target"], "ph_target")
    temp_day = dec(body["temp_day_c"], "temp_day_c")
    temp_night = dec(body["temp_night_c"], "temp_night_c")
    humidity = req_int(body["humidity_pct"], "humidity_pct")
    co2 = req_int(body["co2_ppm"], "co2_ppm")
    days = req_int(body["days_to_harvest"], "days_to_harvest")
    eyield = dec(body["expected_yield_lb_per_tower"], "expected_yield_lb_per_tower")
    if light_hours < 0 or light_ppfd < 0 or humidity < 0 or co2 < 0 or days <= 0:
        raise_error("ERR_INVALID_REQUEST", "numeric fields out of range")
    if ec < 0 or temp_day < -100 or temp_night < -100 or eyield < 0:
        raise_error("ERR_INVALID_REQUEST", "numeric fields out of range")
    recipe = stamp_new({
        "crop_id": crop["id"],
        "light_hours_per_day": light_hours, "light_ppfd_umol": light_ppfd,
        "ec_target_ms": ec, "ph_target": ph,
        "temp_day_c": temp_day, "temp_night_c": temp_night,
        "humidity_pct": humidity, "co2_ppm": co2,
        "days_to_harvest": days, "expected_yield_lb_per_tower": eyield,
        "recipe_status": "DRAFT",
    })
    store.recipes[recipe["id"]] = recipe
    return success(ser_recipe(recipe), status=201)


def _bad(field):
    raise_error("ERR_INVALID_REQUEST", f"{field} invalid")


@bp.get("/recipes")
def list_recipes():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.recipes.values())
    crop_id = _q("crop_id")
    status = _q("recipe_status")
    if crop_id is not None:
        items = [r for r in items if r["crop_id"] == crop_id]
    if status is not None:
        items = [r for r in items if r["recipe_status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response(items, ser_recipe, limit, offset)


@bp.get("/recipes/<rid>")
def get_recipe_route(rid):
    require_roles(*ALL_ROLES)
    return success(ser_recipe(get_recipe(rid)))


@bp.post("/recipes/<rid>/activate")
def activate_recipe(rid):
    require_roles("Grower")
    body = get_body({"expected_crop_version"}, {"expected_crop_version"})
    recipe = get_recipe(rid)
    if recipe["recipe_status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Recipe is not DRAFT")
    crop = get_crop(recipe["crop_id"])
    if crop["crop_status"] != "ACTIVE":
        raise_error("ERR_CROP_RETIRED", "Crop is not ACTIVE")
    expected = req_int(body["expected_crop_version"], "expected_crop_version")
    # OCC checked last (priority 11)
    if expected != crop["version"]:
        raise_error("ERR_STALE_VERSION", "Stale crop version")
    # supersede
    for r in store.recipes.values():
        if r["crop_id"] == crop["id"] and r["recipe_status"] == "ACTIVE" and r["id"] != recipe["id"]:
            r["recipe_status"] = "RETIRED"
            touch(r)
    recipe["recipe_status"] = "ACTIVE"
    touch(recipe)
    touch(crop)
    return success(ser_recipe(recipe))


@bp.post("/recipes/<rid>/retire")
def retire_recipe(rid):
    require_roles("Grower")
    recipe = get_recipe(rid)
    if recipe["recipe_status"] not in ("DRAFT", "ACTIVE"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Recipe not in DRAFT/ACTIVE")
    for b in store.batches.values():
        if b.get("recipe_id") == rid and b["production_status"] in BATCH_NONTERMINAL_FOR_RETIRE:
            raise_error("ERR_RECIPE_IN_USE", "Recipe referenced by non-terminal batches")
    recipe["recipe_status"] = "RETIRED"
    touch(recipe)
    return success(ser_recipe(recipe))


# ---------------------------------------------------------------- water loops
@bp.post("/water-loops")
def create_loop():
    require_roles("FarmManager")
    body = get_body({"loop_code"}, {"loop_code"})
    loop_code = req_str(body["loop_code"], "loop_code")
    for l in store.water_loops.values():
        if l["loop_code"] == loop_code:
            raise_error("ERR_DUPLICATE_CODE", "loop_code already exists")
    loop = stamp_new({
        "loop_code": loop_code,
        "last_passed_at": None,
        "next_sanitation_due_at": None,
    })
    store.water_loops[loop["id"]] = loop
    return success(ser_loop(loop), status=201)


@bp.get("/water-loops")
def list_loops():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.water_loops.values())
    posture = _q("posture")
    if posture is not None:
        items = [l for l in items if loop_posture(l) == posture]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return list_response(items, ser_loop, limit, offset)


@bp.get("/water-loops/<lid>")
def get_loop_route(lid):
    require_roles(*ALL_ROLES)
    return success(ser_loop(get_loop(lid)))


@bp.get("/water-loops/<lid>/sanitation-cycles")
def list_loop_cycles(lid):
    require_roles(*ALL_ROLES)
    loop = get_loop(lid)
    limit, offset = pagination_params()
    items = [c for c in store.sanitation_cycles.values() if c["water_loop_id"] == loop["id"]]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    from services.core import ser_cycle
    return list_response(items, ser_cycle, limit, offset)


# ---------------------------------------------------------------- racks & towers
@bp.post("/racks")
def create_rack():
    require_roles("FarmManager")
    body = get_body({"rack_code", "water_loop_id", "zone", "tower_count"},
                    {"rack_code", "water_loop_id", "zone", "tower_count"})
    rack_code = req_str(body["rack_code"], "rack_code")
    loop_id = body["water_loop_id"]
    if not isinstance(loop_id, str):
        raise_error("ERR_INVALID_REQUEST", "water_loop_id must be a string")
    loop = store.water_loops.get(loop_id)
    if loop is None:
        raise_error("ERR_NOT_FOUND", "WaterLoop not found")
    zone = req_str(body["zone"], "zone")
    tower_count = req_int(body["tower_count"], "tower_count")
    if tower_count <= 0:
        raise_error("ERR_INVALID_REQUEST", "tower_count must be positive")
    for r in store.racks.values():
        if r["rack_code"] == rack_code:
            raise_error("ERR_DUPLICATE_CODE", "rack_code already exists")
    rack = stamp_new({
        "rack_code": rack_code, "water_loop_id": loop["id"], "zone": zone,
        "tower_count": tower_count, "occupied_towers": 0,
        "rack_posture": "OPERATING",
    })
    store.racks[rack["id"]] = rack
    for i in range(1, tower_count + 1):
        tower = stamp_new({"rack_id": rack["id"], "tower_index": i})
        store.towers[tower["id"]] = tower
    return success(ser_rack(rack), status=201)


@bp.get("/racks")
def list_racks():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.racks.values())
    wl = _q("water_loop_id")
    rp = _q("rack_posture")
    zone = _q("zone")
    if wl is not None:
        items = [r for r in items if r["water_loop_id"] == wl]
    if rp is not None:
        items = [r for r in items if r["rack_posture"] == rp]
    if zone is not None:
        items = [r for r in items if r["zone"] == zone]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response(items, ser_rack, limit, offset)


@bp.get("/racks/<rid>")
def get_rack_route(rid):
    require_roles(*ALL_ROLES)
    return success(ser_rack(get_rack(rid)))


@bp.get("/racks/<rid>/towers")
def list_rack_towers(rid):
    require_roles(*ALL_ROLES)
    rack = get_rack(rid)
    limit, offset = pagination_params()
    items = [t for t in store.towers.values() if t["rack_id"] == rack["id"]]
    items.sort(key=lambda t: t["tower_index"])
    return list_response(items, ser_tower, limit, offset)


@bp.post("/racks/<rid>/set-out-of-service")
def rack_out_of_service(rid):
    require_roles("FarmManager")
    rack = get_rack(rid)
    if rack["rack_posture"] != "OPERATING":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Rack is not OPERATING")
    # no ACTIVE allocation on any tower
    tower_ids = {t["id"] for t in store.towers.values() if t["rack_id"] == rid}
    for a in store.allocations.values():
        if a["tower_id"] in tower_ids and a["allocation_status"] == "ACTIVE":
            raise_error("ERR_RACK_HAS_ACTIVE_BATCHES", "Rack has active allocations")
    rack["rack_posture"] = "OUT_OF_SERVICE"
    touch(rack)
    return success(ser_rack(rack))


@bp.post("/racks/<rid>/return-to-service")
def rack_return_to_service(rid):
    require_roles("FarmManager")
    rack = get_rack(rid)
    if rack["rack_posture"] != "OUT_OF_SERVICE":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Rack is not OUT_OF_SERVICE")
    loop = get_loop(rack["water_loop_id"])
    if loop_posture(loop) not in ("IN_SERVICE", "SANITATION_DUE"):
        raise_error("ERR_WATER_LOOP_SANITATION_HOLD", "Loop in sanitation")
    rack["rack_posture"] = "OPERATING"
    touch(rack)
    return success(ser_rack(rack))


@bp.get("/towers")
def list_towers():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.towers.values())
    rack_id = _q("rack_id")
    status = _q("tower_status")
    if rack_id is not None:
        items = [t for t in items if t["rack_id"] == rack_id]
    from services.core import tower_status
    if status is not None:
        items = [t for t in items if tower_status(t) == status]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    return list_response(items, ser_tower, limit, offset)


@bp.get("/towers/<tid>")
def get_tower_route(tid):
    require_roles(*ALL_ROLES)
    return success(ser_tower(get_tower(tid)))


@bp.get("/towers/<tid>/allocations")
def list_tower_allocations(tid):
    require_roles(*ALL_ROLES)
    tower = get_tower(tid)
    limit, offset = pagination_params()
    items = [a for a in store.allocations.values() if a["tower_id"] == tower["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return list_response(items, ser_allocation, limit, offset)
