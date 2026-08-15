"""LumberPriceIndex and SeasonalPriceIndex endpoints (immutable market data)."""

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, opt_field, as_str, as_int, as_enum, as_datetime,
)
from response import success
from services.helpers import init_immutable, serialize, serialize_list, sorted_by_creation

bp = Blueprint("indices", __name__)

SPECIES = ("PINE", "OAK", "MIXED")


@bp.post("/pallet-ops/lumber-index")
def create_lumber_index():
    require_roles("ProcurementManager")
    body = get_json_body()
    species = as_enum(req_field(body, "species"), "species", SPECIES)
    price = as_int(req_field(body, "price_per_mbf_cents"), "price_per_mbf_cents", minimum=0)
    eff_from = as_datetime(req_field(body, "effective_from"), "effective_from")
    eff_to = as_datetime(req_field(body, "effective_to"), "effective_to")
    source_note = opt_field(body, "source_note", "")
    if not isinstance(source_note, str):
        raise_err("ERR_INVALID_REQUEST", "source_note must be a string")
    if not eff_from < eff_to:
        raise_err("ERR_INVALID_REQUEST", "effective_from must be before effective_to")

    # Half-open window overlap guard, same species only. Adjacency
    # (a.effective_to == b.effective_from) is permitted.
    for row in db.lumber_index.values():
        if row["species"] != species:
            continue
        if eff_from < row["_effective_to"] and row["_effective_from"] < eff_to:
            raise_err(
                "ERR_INDEX_WINDOW_OVERLAP",
                "Lumber index window overlaps an existing same-species window",
            )

    row = {
        "species": species,
        "price_per_mbf_cents": price,
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "source_note": source_note,
        "_effective_from": eff_from,
        "_effective_to": eff_to,
    }
    init_immutable(row)
    db.lumber_index[row["id"]] = row
    return success(serialize(row), status=201)


@bp.get("/pallet-ops/lumber-index")
def list_lumber_index():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.lumber_index.values())
    species = request.args.get("species")
    if species is not None:
        items = [r for r in items if r["species"] == species]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.post("/pallet-ops/seasonal-index")
def create_seasonal_index():
    require_roles("PlantManager")
    body = get_json_body()
    season_code = as_str(req_field(body, "season_code"), "season_code")
    multiplier_bp = as_int(req_field(body, "multiplier_bp"), "multiplier_bp")
    if multiplier_bp < 5000 or multiplier_bp > 20000:
        raise_err("ERR_INVALID_REQUEST", "multiplier_bp must be between 5000 and 20000")
    eff_from = as_datetime(req_field(body, "effective_from"), "effective_from")
    eff_to = as_datetime(req_field(body, "effective_to"), "effective_to")
    if not eff_from < eff_to:
        raise_err("ERR_INVALID_REQUEST", "effective_from must be before effective_to")

    if any(r["season_code"] == season_code for r in db.seasonal_index.values()):
        raise_err("ERR_INVALID_REQUEST", "season_code must be unique: %s" % season_code)

    # Seasonal bands must not overlap regardless of season_code.
    for row in db.seasonal_index.values():
        if eff_from < row["_effective_to"] and row["_effective_from"] < eff_to:
            raise_err(
                "ERR_SEASON_WINDOW_OVERLAP",
                "Seasonal index window overlaps an existing band",
            )

    row = {
        "season_code": season_code,
        "multiplier_bp": multiplier_bp,
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "_effective_from": eff_from,
        "_effective_to": eff_to,
    }
    init_immutable(row)
    db.seasonal_index[row["id"]] = row
    return success(serialize(row), status=201)


@bp.get("/pallet-ops/seasonal-index")
def list_seasonal_index():
    require_roles()
    limit, offset = parse_pagination()
    items = sorted_by_creation(list(db.seasonal_index.values()))
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)
