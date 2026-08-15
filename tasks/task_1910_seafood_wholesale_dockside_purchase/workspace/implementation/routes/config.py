"""Configuration entities: Vessel, Customer, CatchArea, Species."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_record
from errors import (
    ApiError,
    ERR_VESSEL_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_CATCH_AREA_NOT_FOUND,
    ERR_SPECIES_NOT_FOUND,
    ERR_DUPLICATE_UNIQUE_VALUE,
)
from middleware import auth, require
from response import ok, ok_list
from util import body, req_str, req_int, opt_num, opt_bool, apply_filters

bp = Blueprint("config", __name__)

ANY_ROLE = None  # GET endpoints accept every authenticated role


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------
@bp.post("/vessels")
def create_vessel():
    _, role = auth()
    require(role, {"OperationsManager"})
    b = body()
    vessel_name = req_str(b, "vessel_name")
    registration_number = req_str(b, "registration_number")
    home_port = req_str(b, "home_port")
    if any(v["registration_number"] == registration_number for v in store.vessels.values()):
        raise ApiError(ERR_DUPLICATE_UNIQUE_VALUE, 409, "registration_number already in use")
    rec = new_record({
        "vessel_name": vessel_name,
        "registration_number": registration_number,
        "home_port": home_port,
        "payable_balance_cents": 0,
    })
    store.vessels[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/vessels/<rid>")
def get_vessel(rid):
    auth()
    rec = store.vessels.get(rid)
    if rec is None:
        raise ApiError(ERR_VESSEL_NOT_FOUND, 404, "Vessel id does not exist")
    return ok(rec)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@bp.post("/customers")
def create_customer():
    _, role = auth()
    require(role, {"OperationsManager"})
    b = body()
    business_name = req_str(b, "business_name")
    credit_limit_cents = req_int(b, "credit_limit_cents")
    discount_pct = opt_num(b, "discount_pct", Decimal("0"))
    rec = new_record({
        "business_name": business_name,
        "credit_limit_cents": credit_limit_cents,
        "discount_pct": discount_pct,
        "credit_exposure_cents": 0,
    })
    store.customers[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/customers/<rid>")
def get_customer(rid):
    auth()
    rec = store.customers.get(rid)
    if rec is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, 404, "Customer id does not exist")
    return ok(rec)


# ---------------------------------------------------------------------------
# Catch areas
# ---------------------------------------------------------------------------
@bp.post("/catch-areas")
def create_catch_area():
    _, role = auth()
    require(role, {"OperationsManager"})
    b = body()
    fao_code = req_str(b, "fao_code")
    name = req_str(b, "name")
    region = req_str(b, "region")
    if any(c["fao_code"] == fao_code for c in store.catch_areas.values()):
        raise ApiError(ERR_DUPLICATE_UNIQUE_VALUE, 409, "fao_code already in use")
    rec = new_record({
        "fao_code": fao_code,
        "name": name,
        "region": region,
    })
    store.catch_areas[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/catch-areas/<rid>")
def get_catch_area(rid):
    auth()
    rec = store.catch_areas.get(rid)
    if rec is None:
        raise ApiError(ERR_CATCH_AREA_NOT_FOUND, 404, "CatchArea id does not exist")
    return ok(rec)


# ---------------------------------------------------------------------------
# Species
# ---------------------------------------------------------------------------
@bp.post("/species")
def create_species():
    _, role = auth()
    require(role, {"OperationsManager"})
    b = body()
    species_code = req_str(b, "species_code")
    common_name = req_str(b, "common_name")
    labeling_name = req_str(b, "labeling_name")
    substitution_group = req_str(b, "substitution_group")
    fresh_shelf_life_hours = req_int(b, "fresh_shelf_life_hours")
    frozen_shelf_life_days = req_int(b, "frozen_shelf_life_days")
    is_import = opt_bool(b, "is_import", False)
    requires_cites = opt_bool(b, "requires_cites", False)
    if any(s["species_code"] == species_code for s in store.species.values()):
        raise ApiError(ERR_DUPLICATE_UNIQUE_VALUE, 409, "species_code already in use")
    rec = new_record({
        "species_code": species_code,
        "common_name": common_name,
        "labeling_name": labeling_name,
        "substitution_group": substitution_group,
        "is_import": is_import,
        "requires_cites": requires_cites,
        "fresh_shelf_life_hours": fresh_shelf_life_hours,
        "frozen_shelf_life_days": frozen_shelf_life_days,
    })
    store.species[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/species/<rid>")
def get_species(rid):
    auth()
    rec = store.species.get(rid)
    if rec is None:
        raise ApiError(ERR_SPECIES_NOT_FOUND, 404, "Species id does not exist")
    return ok(rec)
