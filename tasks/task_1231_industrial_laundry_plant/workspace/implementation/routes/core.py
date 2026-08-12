"""Logical clock, Plant, and LinenCategory endpoints."""

from flask import Blueprint

import clock
import db
from response import success, success_raw, list_response
from util import (
    ALL_ROLES,
    PLANT_SIDE,
    FLOOR_READ,
    authenticate,
    require_roles,
    body_json,
    field,
    path_get,
    filter_eq,
)

bp = Blueprint("core", __name__)

FORMULAS = ("WF_STANDARD", "WF_THERMAL_DISINFECT", "WF_CHEM_DISINFECT", "WF_HEAVY_SOIL")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    data = body_json()
    to_iso = field(data, "to_iso8601", "datetime")
    auth = authenticate()
    require_roles(auth, {"PlantAdmin"})
    dt = clock.parse_dt(to_iso)
    clock.set_current(dt)
    return success_raw({"current_utc": clock.fmt(clock.now())})


@bp.route("/plants", methods=["POST"])
def create_plant():
    data = body_json()
    name = field(data, "name", "s")
    reject_pct = field(data, "reject_rate_alert_pct", "n", minv=0)
    par_alert = field(data, "par_shortage_alert_pieces", "i", minv=0)
    base_kwh = field(data, "utility_baseline_kwh_per_lb", "n", minv=0)
    base_gal = field(data, "utility_baseline_gal_per_lb", "n", minv=0)
    auth = authenticate()
    require_roles(auth, {"PlantAdmin"})
    plant = db.new_entity()
    plant.update(
        {
            "name": name,
            "reject_rate_alert_pct": reject_pct,
            "par_shortage_alert_pieces": par_alert,
            "utility_baseline_kwh_per_lb": base_kwh,
            "utility_baseline_gal_per_lb": base_gal,
        }
    )
    db.plants[plant["id"]] = plant
    return success(plant, 201)


@bp.route("/plants/<pid>", methods=["GET"])
def get_plant(pid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    return success(path_get(db.plants, pid))


@bp.route("/plants/<pid>/linen-categories", methods=["POST"])
def create_category(pid):
    data = body_json()
    code = field(data, "code", "s")
    weight = field(data, "piece_weight_lb", "n", minv=0)
    formula = field(data, "wash_formula_code", "s", choices=FORMULAS)
    test_req = field(data, "hygienic_test_required", "b")
    repl = field(data, "replacement_cost_cents", "i", minv=0)
    cog_rate = field(data, "cog_wash_rate_cents_per_lb", "i", minv=0)
    auth = authenticate()
    require_roles(auth, {"PlantAdmin"})
    plant = path_get(db.plants, pid)
    cat = db.new_entity()
    cat.update(
        {
            "plant_id": plant["id"],
            "code": code,
            "piece_weight_lb": weight,
            "wash_formula_code": formula,
            "hygienic_test_required": test_req,
            "replacement_cost_cents": repl,
            "cog_wash_rate_cents_per_lb": cog_rate,
        }
    )
    db.categories[cat["id"]] = cat
    return success(cat, 201)


@bp.route("/plants/<pid>/linen-categories", methods=["GET"])
def list_categories(pid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    plant = path_get(db.plants, pid)
    items = [c for c in db.sorted_all(db.categories) if c["plant_id"] == plant["id"]]
    return list_response(items)


@bp.route("/linen-categories/<cid>", methods=["GET"])
def get_category(cid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    return success(path_get(db.categories, cid))


@bp.route("/linen-categories/<cid>/par-levels", methods=["GET"])
def list_category_par_levels(cid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    cat = path_get(db.categories, cid)
    items = [p for p in db.sorted_all(db.par_levels) if p["category_id"] == cat["id"]]
    return list_response(items)


@bp.route("/linen-categories/<cid>/sort-items", methods=["GET"])
def list_category_sort_items(cid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    cat = path_get(db.categories, cid)
    items = [s for s in db.sorted_all(db.sort_items) if s["category_id"] == cat["id"]]
    return list_response(items)


@bp.route("/linen-categories/<cid>/wash-loads", methods=["GET"])
def list_category_wash_loads(cid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    cat = path_get(db.categories, cid)
    items = [w for w in db.sorted_all(db.wash_loads) if w["category_id"] == cat["id"]]
    return list_response(items)


@bp.route("/linen-categories/<cid>/garments", methods=["GET"])
def list_category_garments(cid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    cat = path_get(db.categories, cid)
    items = [g for g in db.sorted_all(db.garments) if g["category_id"] == cat["id"]]
    return list_response(items)


@bp.route("/linen-categories/<cid>/deliveries", methods=["GET"])
def list_category_deliveries(cid):
    auth = authenticate()
    require_roles(auth, PLANT_SIDE)
    cat = path_get(db.categories, cid)
    items = [d for d in db.sorted_all(db.deliveries) if d["category_id"] == cat["id"]]
    return list_response(items)
