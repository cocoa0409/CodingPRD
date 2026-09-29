"""Plants, board lines, product specs, markets and the logical clock (PRD 3.1)."""

from flask import Blueprint

import calc
import validate as v
from db import base_entity, db, ordered
from errors import fail
from middleware import ANY, guard
from response import entity_response, ok
from routes.common import (
    list_collection,
    require_plant,
    require_row,
)
from services.plant import recompute_plant_derived
from util import D, ZERO2, ZERO3, parse_iso

bp = Blueprint("config", __name__)

BOARD_TYPES = ("REGULAR", "TYPE_X", "TYPE_C", "MOLD_RESISTANT", "ABUSE_RESISTANT")
FIRE_RATED_TYPES = ("TYPE_X", "TYPE_C")
CHANGEOVER_FAMILIES = ("STANDARD", "FIRE_RATED", "SPECIALTY")
THICKNESSES = ("0.375", "0.5", "0.625")


# ------------------------------------------------------------------- plants
@bp.post("/plant-ops/plants")
@guard(("PlantAdmin",))
def create_plant():
    body = v.body_of()
    code = v.text(body, "code", min_len=1, max_len=16)
    name = v.text(body, "name", min_len=1)
    calciner_capacity_tph = v.num(body, "calciner_capacity_tph", gt=0)
    stucco_silo_capacity_tons = v.num(body, "stucco_silo_capacity_tons", gt=0)
    natural_floor = v.num(
        body, "natural_gypsum_purity_floor_pct", required=False, default=D("88.0"),
        ge="50.0", le="100.0",
    )
    synthetic_ceiling = v.num(
        body, "synthetic_free_moisture_ceiling_pct", required=False, default=D("12.0"),
        ge="0.0", le="30.0",
    )
    energy_price_per_mmbtu = v.num(body, "energy_price_per_mmbtu", gt=0)
    contribution_margin_per_msf = v.num(body, "contribution_margin_per_msf", ge=0)

    for existing in db.plants.values():
        if existing["code"] == code:
            fail("ERR_INVALID_REQUEST", "code %s is already registered" % code)

    plant = base_entity()
    plant.update(
        {
            "code": code,
            "name": name,
            "calciner_capacity_tph": calciner_capacity_tph,
            "stucco_silo_capacity_tons": stucco_silo_capacity_tons,
            "natural_gypsum_purity_floor_pct": natural_floor,
            "synthetic_free_moisture_ceiling_pct": synthetic_ceiling,
            "energy_price_per_mmbtu": energy_price_per_mmbtu,
            "contribution_margin_per_msf": contribution_margin_per_msf,
            "stucco_on_hand_tons": ZERO3,
            "stucco_committed_tons": ZERO3,
            "stucco_available_tons": ZERO3,
            "held_run_count": 0,
            "production_posture": "OPEN",
        }
    )
    db.plants[plant["id"]] = plant
    recompute_plant_derived(plant)
    return entity_response(plant, 201)


@bp.get("/plant-ops/plants")
@guard(ANY)
def list_plants():
    return list_collection(db.plants, ("code", "production_posture"))


@bp.get("/plant-ops/plants/<plant_id>")
@guard(ANY)
def read_plant(plant_id):
    return entity_response(require_plant(plant_id))


# -------------------------------------------------------------- board lines
@bp.post("/plant-ops/plants/<plant_id>/board-lines")
@guard(("PlantAdmin",))
def create_board_line(plant_id):
    plant = require_plant(plant_id)
    body = v.body_of()
    designation = v.text(body, "designation", min_len=1)
    max_speed_fpm = v.integer(body, "max_speed_fpm", ge=100, le=1200)
    web_width_in = v.num(body, "web_width_in", gt=0)

    for existing in db.board_lines.values():
        if existing["plant_id"] == plant["id"] and existing["designation"] == designation:
            fail(
                "ERR_INVALID_REQUEST",
                "designation %s already exists at this plant" % designation,
            )

    line = base_entity()
    line.update(
        {
            "plant_id": plant["id"],
            "designation": designation,
            "max_speed_fpm": max_speed_fpm,
            "web_width_in": web_width_in,
            "status": "AVAILABLE",
        }
    )
    db.board_lines[line["id"]] = line
    return entity_response(line, 201)


@bp.get("/plant-ops/plants/<plant_id>/board-lines")
@guard(ANY)
def list_plant_board_lines(plant_id):
    plant = require_plant(plant_id)
    base = [l for l in ordered(db.board_lines) if l["plant_id"] == plant["id"]]
    return list_collection(db.board_lines, ("status",), base=base)


@bp.get("/plant-ops/board-lines")
@guard(ANY)
def list_board_lines():
    return list_collection(db.board_lines, ("plant_id", "status"))


@bp.get("/plant-ops/board-lines/<line_id>")
@guard(ANY)
def read_board_line(line_id):
    return entity_response(require_row(db.board_lines, line_id, "board line"))


# ------------------------------------------------------------ product specs
@bp.post("/plant-ops/plants/<plant_id>/product-specs")
@guard(("PlantAdmin",))
def create_product_spec(plant_id):
    plant = require_plant(plant_id)
    body = v.body_of()
    sku_code = v.text(body, "sku_code", min_len=1)
    thickness_in = v.one_of_number(body, "thickness_in", THICKNESSES)
    board_type = v.enum(body, "board_type", BOARD_TYPES)
    fire_rated = v.boolean(body, "fire_rated")
    board_width_in = v.num(body, "board_width_in", gt=0)
    board_length_ft = v.num(body, "board_length_ft", gt=0)
    target_board_weight_lb_per_msf = v.num(body, "target_board_weight_lb_per_msf", gt=0)
    stucco_lb_per_msf = v.num(body, "stucco_lb_per_msf", gt=0)
    slurry_water_stucco_ratio = v.num(
        body, "slurry_water_stucco_ratio", ge="0.30", le="1.20"
    )
    line_speed_max_fpm = v.integer(body, "line_speed_max_fpm", ge=100, le=1200)
    paper_tension_min_lb = v.num(body, "paper_tension_min_lb", gt=0)
    paper_tension_max_lb = v.num(body, "paper_tension_max_lb", gt=0)
    core_hardness_min_lbf = v.num(body, "core_hardness_min_lbf", gt=0)
    nail_pull_min_lbf = v.num(body, "nail_pull_min_lbf", gt=0)
    flexural_cross_min_lbf = v.num(body, "flexural_cross_min_lbf", gt=0)
    max_boards_per_bundle = v.integer(body, "max_boards_per_bundle", ge=2, le=80)
    changeover_family = v.enum(body, "changeover_family", CHANGEOVER_FAMILIES)

    if paper_tension_max_lb <= paper_tension_min_lb:
        fail(
            "ERR_INVALID_REQUEST",
            "paper_tension_max_lb must be strictly greater than paper_tension_min_lb",
        )
    if max_boards_per_bundle % 2 != 0:
        fail("ERR_INVALID_REQUEST", "max_boards_per_bundle must be even")
    expected_fire_rated = board_type in FIRE_RATED_TYPES
    if fire_rated != expected_fire_rated:
        fail(
            "ERR_INVALID_REQUEST",
            "fire_rated must be %s for board_type %s"
            % ("true" if expected_fire_rated else "false", board_type),
        )
    for existing in db.product_specs.values():
        if existing["plant_id"] == plant["id"] and existing["sku_code"] == sku_code:
            fail("ERR_INVALID_REQUEST", "sku_code %s already exists at this plant" % sku_code)

    spec = base_entity()
    spec.update(
        {
            "plant_id": plant["id"],
            "sku_code": sku_code,
            "thickness_in": thickness_in,
            "board_type": board_type,
            "fire_rated": fire_rated,
            "board_width_in": board_width_in,
            "board_length_ft": board_length_ft,
            "target_board_weight_lb_per_msf": target_board_weight_lb_per_msf,
            "stucco_lb_per_msf": stucco_lb_per_msf,
            "slurry_water_stucco_ratio": slurry_water_stucco_ratio,
            "line_speed_max_fpm": line_speed_max_fpm,
            "paper_tension_min_lb": paper_tension_min_lb,
            "paper_tension_max_lb": paper_tension_max_lb,
            "core_hardness_min_lbf": core_hardness_min_lbf,
            "nail_pull_min_lbf": nail_pull_min_lbf,
            "flexural_cross_min_lbf": flexural_cross_min_lbf,
            "max_boards_per_bundle": max_boards_per_bundle,
            "changeover_family": changeover_family,
        }
    )
    db.product_specs[spec["id"]] = spec
    return entity_response(spec, 201)


@bp.get("/plant-ops/plants/<plant_id>/product-specs")
@guard(ANY)
def list_plant_product_specs(plant_id):
    plant = require_plant(plant_id)
    base = [s for s in ordered(db.product_specs) if s["plant_id"] == plant["id"]]
    return list_collection(db.product_specs, ("board_type",), base=base)


@bp.get("/plant-ops/product-specs")
@guard(ANY)
def list_product_specs():
    return list_collection(db.product_specs, ("plant_id", "board_type", "fire_rated"))


@bp.get("/plant-ops/product-specs/<spec_id>")
@guard(ANY)
def read_product_spec(spec_id):
    return entity_response(require_row(db.product_specs, spec_id, "product spec"))


# ------------------------------------------------------------------ markets
@bp.post("/plant-ops/markets")
@guard(("PlantAdmin",))
def create_market():
    body = v.body_of()
    name = v.text(body, "name", min_len=1)
    distance_miles = v.num(body, "distance_miles", gt=0)
    fuel_surcharge_pct = v.num(body, "fuel_surcharge_pct", ge="0.0", le="60.0")
    min_charge_usd = v.num(body, "min_charge_usd", ge=0)
    backhaul_credit_usd = v.num(
        body, "backhaul_credit_usd", required=False, default=ZERO2, ge=0
    )

    rate_zone, base_rate = calc.rate_zone_of(distance_miles)
    market = base_entity()
    market.update(
        {
            "name": name,
            "distance_miles": distance_miles,
            "fuel_surcharge_pct": fuel_surcharge_pct,
            "min_charge_usd": min_charge_usd,
            "backhaul_credit_usd": backhaul_credit_usd,
            "rate_zone": rate_zone,
            "base_rate_per_msf": base_rate,
        }
    )
    db.markets[market["id"]] = market
    return entity_response(market, 201)


@bp.get("/plant-ops/markets")
@guard(ANY)
def list_markets():
    return list_collection(db.markets, ("rate_zone",))


@bp.get("/plant-ops/markets/<market_id>")
@guard(ANY)
def read_market(market_id):
    return entity_response(require_row(db.markets, market_id, "market"))


# ------------------------------------------------------------ logical clock
@bp.post("/plant-ops/_clock/set_current_utc")
@guard(("PlantAdmin",))
def set_clock():
    body = v.body_of()
    raw, parsed = v.instant(body, "to_iso8601")
    db.clock = parsed
    db.clock_raw = raw
    return ok({"current_utc": raw})
