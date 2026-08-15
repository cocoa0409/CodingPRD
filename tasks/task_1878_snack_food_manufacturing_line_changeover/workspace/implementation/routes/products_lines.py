from flask import Blueprint

from auth import require, ALL_ROLES
from domain import (ALLERGENS, FLAVOR_GROUPS, PROCESS_TYPES, LINE_TYPES,
                    dump_product, dump_line, dump_oil, get_product, get_line)
from errors import ApiError
from store import STORE, new_entity
from util import body, ok, req_str, req_enum, req_num, opt_num, req_int, opt_int, D

bp = Blueprint("products_lines", __name__)


@bp.post("/snack-mfg/products")
def create_product():
    require(["PlantManager"])
    data = body()
    # tier 5: shape
    name = req_str(data, "name")
    process_type = req_enum(data, "process_type", PROCESS_TYPES)
    allergen_profile = data.get("allergen_profile")
    if not isinstance(allergen_profile, list):
        raise ApiError("ERR_VALIDATION", 400, "allergen_profile must be an array")
    for a in allergen_profile:
        if not isinstance(a, str) or a not in ALLERGENS:
            raise ApiError("ERR_VALIDATION", 400, "invalid allergen tag")
    if len(set(allergen_profile)) != len(allergen_profile):
        raise ApiError("ERR_VALIDATION", 400, "duplicate allergen entries")
    flavor_group = req_enum(data, "flavor_group", FLAVOR_GROUPS)
    declared = req_num(data, "declared_net_weight_g", gt=0)
    tne = req_num(data, "tne_g", gt=0)
    giveaway_target = req_num(data, "giveaway_target_pct", ge=0)
    giveaway_max = req_num(data, "giveaway_max_pct", ge=0)
    shelf_life = req_int(data, "shelf_life_days", ge=1)
    seasoning_target = req_num(data, "seasoning_target_pct", ge=0)
    if process_type == "FRYER":
        fry_target = req_num(data, "fry_target_temp_c")
    else:
        fry_target = opt_num(data, "fry_target_temp_c", default=None)
    standard_oil_price = req_int(data, "standard_oil_price_cents_per_gal", ge=0)
    case_revenue = req_int(data, "case_revenue_cents", ge=0)
    min_margin = req_int(data, "min_margin_cents_per_case", ge=0)
    bags_per_case = opt_int(data, "bags_per_case", ge=1, default=12)
    for other in STORE.products.values():
        if other["name"] == name:
            raise ApiError("ERR_VALIDATION", 400, "product name must be unique")
    p = new_entity(STORE)
    p.update({
        "name": name, "process_type": process_type,
        "allergen_profile": list(allergen_profile), "flavor_group": flavor_group,
        "declared_net_weight_g": declared, "tne_g": tne,
        "giveaway_target_pct": giveaway_target, "giveaway_max_pct": giveaway_max,
        "shelf_life_days": shelf_life, "seasoning_target_pct": seasoning_target,
        "fry_target_temp_c": fry_target,
        "standard_oil_price_cents_per_gal": standard_oil_price,
        "case_revenue_cents": case_revenue, "min_margin_cents_per_case": min_margin,
        "bags_per_case": bags_per_case,
    })
    STORE.products[p["id"]] = p
    return ok(STORE, dump_product(p), status=201)


@bp.get("/snack-mfg/products/<pid>")
def get_product_ep(pid):
    require(ALL_ROLES)
    p = get_product(STORE, pid)
    return ok(STORE, dump_product(p))


@bp.post("/snack-mfg/lines")
def create_line():
    require(["PlantManager"])
    data = body()
    name = req_str(data, "name")
    line_type = req_enum(data, "line_type", LINE_TYPES)
    capacity = req_num(data, "oil_capacity_gallons", gt=0)
    full_wash = opt_int(data, "cleaning_minutes_full_wash", ge=0, default=120)
    dry = opt_int(data, "cleaning_minutes_dry", ge=0, default=30)
    for other in STORE.lines.values():
        if other["name"] == name:
            raise ApiError("ERR_VALIDATION", 400, "line name must be unique")
    line = new_entity(STORE)
    line.update({
        "name": name, "line_type": line_type, "oil_capacity_gallons": capacity,
        "cleaning_minutes_full_wash": full_wash, "cleaning_minutes_dry": dry,
    })
    STORE.lines[line["id"]] = line
    # atomic 1:1 FryerOil creation
    oil = new_entity(STORE)
    oil.update({
        "line_id": line["id"], "initial_charge_gallons": capacity,
        "current_gallons": D(capacity), "tpm_pct": D("0.5"), "state": "ACTIVE",
        "total_lbs_since_replace": D(0),
    })
    STORE.oils[oil["id"]] = oil
    STORE.oil_by_line[line["id"]] = oil["id"]
    return ok(STORE, dump_line(STORE, line), status=201)


@bp.get("/snack-mfg/lines/<lid>")
def get_line_ep(lid):
    require(ALL_ROLES)
    line = get_line(STORE, lid)
    return ok(STORE, dump_line(STORE, line))
