"""LogLoad endpoints: receive, list, get, scale, dispute, resolve, deck, undeck."""
from flask import Blueprint

from db import DB, new_id, now_dt, now_iso, fmt_dt
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    LOG_GRADES,
    SPECIES,
    degrade_for_days,
    get_load,
    ser_load,
    stamp,
    touch,
    DECK_CAPACITY_MBF,
    days_in_deck,
)
from util import (
    as_enum,
    as_int,
    as_num,
    as_str,
    body,
    dec,
    pagination_args,
    required,
    round_cents,
)

bp = Blueprint("log_loads", __name__)


@bp.post("/api/log-loads")
def create_load():
    auth(["Scaler"])
    data = body()
    supplier_name = as_str(required(data, "supplier_name"), "supplier_name")
    species = as_enum(required(data, "species"), "species", SPECIES)
    log_grade = as_enum(required(data, "log_grade"), "log_grade", LOG_GRADES)
    load = {
        "id": new_id(),
        "supplier_name": supplier_name,
        "species": species,
        "log_grade": log_grade,
        "scaled_mbf": None,
        "price_per_mbf_cents": None,
        "purchase_cost_cents": None,
        "status": "RECEIVED",
        "decked_at": None,
        "decked_at_dt": None,
        "degrade_pct": 0,
        "sawing_run_id": None,
        "dispute_reason": None,
    }
    stamp(load)
    DB["log_loads"][load["id"]] = load
    return ok(ser_load(load), 201)


@bp.get("/api/log-loads")
def list_loads():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    status_f = None
    species_f = None
    run_f = None
    from flask import request

    if "status" in request.args:
        status_f = request.args.get("status")
    if "species" in request.args:
        species_f = request.args.get("species")
    if "sawing_run_id" in request.args:
        run_f = request.args.get("sawing_run_id")
    items = list(DB["log_loads"].values())
    if status_f is not None:
        items = [l for l in items if l["status"] == status_f]
    if species_f is not None:
        items = [l for l in items if l["species"] == species_f]
    if run_f is not None:
        items = [l for l in items if l["sawing_run_id"] == run_f]
    items.sort(key=lambda l: l["_seq"])  # created_at ascending, insertion order
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_load(l) for l in page], total, limit, offset)


@bp.get("/api/log-loads/<lid>")
def get_one_load(lid):
    auth(ALL_ROLES)
    return ok(ser_load(get_load(lid)))


def _scale_fields(data):
    scaled_mbf = as_num(required(data, "scaled_mbf"), "scaled_mbf", positive=True)
    price = as_int(
        required(data, "price_per_mbf_cents"), "price_per_mbf_cents", positive=True
    )
    return scaled_mbf, price


@bp.post("/api/log-loads/<lid>/scale")
def scale_load(lid):
    auth(["Scaler"])
    load = get_load(lid)
    data = body()
    scaled_mbf, price = _scale_fields(data)
    if load["status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a RECEIVED load can be scaled"
        )
    load["scaled_mbf"] = scaled_mbf
    load["price_per_mbf_cents"] = price
    load["purchase_cost_cents"] = round_cents(dec(scaled_mbf) * dec(price))
    load["status"] = "SCALED"
    touch(load)
    return ok(ser_load(load))


@bp.post("/api/log-loads/<lid>/dispute")
def dispute_load(lid):
    auth(["Scaler"])
    load = get_load(lid)
    data = body()
    reason = as_str(required(data, "reason"), "reason")
    if load["status"] != "SCALED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a SCALED load can be disputed"
        )
    load["dispute_reason"] = reason
    load["status"] = "DISPUTED"
    touch(load)
    return ok(ser_load(load))


@bp.post("/api/log-loads/<lid>/resolve-scale")
def resolve_scale(lid):
    auth(["MillManager"])
    load = get_load(lid)
    data = body()
    scaled_mbf, price = _scale_fields(data)
    if load["status"] != "DISPUTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a DISPUTED load can be resolved"
        )
    load["scaled_mbf"] = scaled_mbf
    load["price_per_mbf_cents"] = price
    load["purchase_cost_cents"] = round_cents(dec(scaled_mbf) * dec(price))
    load["status"] = "SCALED"
    touch(load)
    return ok(ser_load(load))


@bp.post("/api/log-loads/<lid>/deck")
def deck_load(lid):
    auth(["Scaler"])
    load = get_load(lid)
    body()
    if load["status"] != "SCALED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a SCALED load can be decked"
        )
    occupancy = sum(
        dec(l["scaled_mbf"]) for l in DB["log_loads"].values() if l["status"] == "DECKED"
    )
    if occupancy + dec(load["scaled_mbf"]) > DECK_CAPACITY_MBF:
        raise ApiError(
            "ERR_DECK_CAPACITY_EXCEEDED",
            422,
            "Decking this load would exceed the 500 MBF deck capacity",
        )
    load["decked_at_dt"] = now_dt()
    load["decked_at"] = fmt_dt(now_dt())
    load["degrade_pct"] = 0
    load["status"] = "DECKED"
    touch(load)
    return ok(ser_load(load))


@bp.post("/api/log-loads/<lid>/undeck")
def undeck_load(lid):
    auth(["Scaler"])
    load = get_load(lid)
    body()
    if load["status"] != "DECKED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a DECKED load can be undecked"
        )
    if load["sawing_run_id"] is not None:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Load is attached to a planned sawing run and cannot be undecked",
        )
    load["decked_at"] = None
    load["decked_at_dt"] = None
    load["degrade_pct"] = 0
    load["status"] = "SCALED"
    touch(load)
    return ok(ser_load(load))
