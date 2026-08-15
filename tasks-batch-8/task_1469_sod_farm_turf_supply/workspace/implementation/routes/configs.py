"""Rate cards (PriceConfig) and turf varieties (VarietyConfig)."""
from flask import Blueprint

import calc
import db
from auth import require_roles
from db import common_fields
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from serialize import pub_price_config, pub_variety
from util import (D, as_int, as_num, as_str, body, ok, ok_list, paged, pagination,
                  require, sort_created)

bp = Blueprint("configs", __name__)

# (field, kind, default) — kinds: "num" (Decimal), "int"
_PRICE_CONFIG_SPEC = [
    ("slab_sqft", "num", "5"),
    ("roll_sqft", "num", "10"),
    ("pallet_sqft_premium", "num", "100"),
    ("pallet_sqft_standard", "num", "50"),
    ("pallet_sqft_economy", "num", "20"),
    ("rate_premium", "num", "0.855"),
    ("rate_standard", "num", "0.70"),
    ("rate_economy", "num", "0.50"),
    ("zone1_rate", "num", "1.20"),
    ("zone2_rate", "num", "1.80"),
    ("zone3_rate", "num", "2.60"),
    ("freight_sqft_unit", "int", 500),
    ("zone_truck_capacity", "int", 4),
    ("delivery_window_hours", "int", 2),
    ("delivery_earliest_start_hour", "int", 6),
    ("delivery_latest_start_hour", "int", 16),
    ("same_day_cutoff_hours", "int", 2),
    ("future_day_cutoff_hour", "int", 14),
    ("freshness_limit_hours", "num", "24"),
    ("card_fee_pct", "num", "0.02"),
    ("cash_discount_pct", "num", "0.03"),
    ("volume_t1_turf_min", "num", "2000"),
    ("volume_t1_pre_min", "num", "4000"),
    ("volume_t1_pct", "num", "0.06"),
    ("volume_t2_turf_min", "num", "8000"),
    ("volume_t2_pre_min", "num", "15000"),
    ("volume_t2_pct", "num", "0.15"),
    ("harvest_earliest_start_hour", "int", 6),
    ("harvest_latest_end_hour", "int", 18),
]


@bp.route("/price-configs", methods=["POST"])
def create_price_config():
    require_roles("FarmManager")
    payload = body()
    name = as_str(require(payload, "name"), "name")
    cfg = common_fields()
    cfg["name"] = name
    for fname, kind, default in _PRICE_CONFIG_SPEC:
        if fname in payload and payload[fname] is not None:
            if kind == "int":
                cfg[fname] = as_int(payload[fname], fname)
            else:
                cfg[fname] = as_num(payload[fname], fname)
        else:
            cfg[fname] = default if kind == "int" else D(default)
    # exclusive publication: the newest card is current, all others flip false
    for other in db.store.price_configs.values():
        if other["is_current"]:
            other["is_current"] = False
            db.bump(other)
    cfg["is_current"] = True
    db.store.price_configs[cfg["id"]] = cfg
    return ok(pub_price_config(cfg), 201)


@bp.route("/price-configs", methods=["GET"])
def list_price_configs():
    require_roles("FarmManager", "SalesRep")
    limit, offset = pagination()
    items = sort_created(db.store.price_configs.values())
    page, total = paged(items, limit, offset)
    return ok_list([pub_price_config(c) for c in page], total, limit, offset)


@bp.route("/variety-configs", methods=["POST"])
def create_variety_config():
    require_roles("FarmManager")
    payload = body()
    name = as_str(require(payload, "name"), "name")
    for v in db.store.variety_configs.values():
        if v["name"] == name:
            raise err(ERR_INVALID_REQUEST, f"variety name '{name}' already exists")
    variety = common_fields()
    variety["name"] = name
    variety["germination_max_days"] = as_int(payload["germination_max_days"], "germination_max_days") \
        if payload.get("germination_max_days") is not None else 14
    variety["growing_max_days"] = as_int(payload["growing_max_days"], "growing_max_days") \
        if payload.get("growing_max_days") is not None else 60
    variety["ready_max_days"] = as_int(payload["ready_max_days"], "ready_max_days") \
        if payload.get("ready_max_days") is not None else 150
    variety["mature_max_days"] = as_int(payload["mature_max_days"], "mature_max_days") \
        if payload.get("mature_max_days") is not None else 240
    variety["seed_lbs_per_1000_sqft"] = as_num(payload["seed_lbs_per_1000_sqft"], "seed_lbs_per_1000_sqft") \
        if payload.get("seed_lbs_per_1000_sqft") is not None else D("6")
    db.store.variety_configs[variety["id"]] = variety
    return ok(pub_variety(variety), 201)


@bp.route("/variety-configs", methods=["GET"])
def list_variety_configs():
    require_roles("FarmManager", "SalesRep", "HarvestSupervisor")
    limit, offset = pagination()
    items = sort_created(db.store.variety_configs.values())
    page, total = paged(items, limit, offset)
    return ok_list([pub_variety(v) for v in page], total, limit, offset)
