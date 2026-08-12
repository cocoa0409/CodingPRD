"""Forward purchase contracts (PRD 3.2)."""
from flask import Blueprint

from db import STORE, make_record, bump
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize, ALL_ROLES
from services import (ser_contract, sorted_items, maybe_expire_contract,
                      recompute_provisional_for_ingredient)
from validation import get_body, req_str, req_int, req_tons, req_date, bad, paginate

bp = Blueprint("contracts", __name__)


def _get_contract(cid):
    c = STORE["contracts"].get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Contract {cid} not found")
    return c


@bp.post("/api/contracts")
def create_contract():
    uid, role = authenticate()
    data = get_body()
    ingredient_id = req_str(data, "ingredient_id")
    supplier_ref = req_str(data, "supplier_ref")
    fixed_price = req_int(data, "fixed_price_cents_per_ton", gt=0)
    total_tons = req_tons(data, "total_tons")
    window_start = req_date(data, "window_start_date")
    window_end = req_date(data, "window_end_date")
    if window_end < window_start:
        bad("window_end_date must be on or after window_start_date")
    authorize(role, uid, {"MillManager"})
    ing = STORE["ingredients"].get(ingredient_id)
    if ing is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Ingredient {ingredient_id} not found")
    # Layer 8 (temporal): closed-interval overlap against OPEN/EXHAUSTED windows
    # of the same ingredient; touching dates conflict.
    for c in STORE["contracts"].values():
        if c["ingredient_id"] != ingredient_id:
            continue
        maybe_expire_contract(c)
        if c["status"] not in ("OPEN", "EXHAUSTED"):
            continue
        if window_start <= c["window_end"] and c["window_start"] <= window_end:
            raise ApiError("ERR_CONTRACT_WINDOW_OVERLAP", 409,
                           "Contract window overlaps an existing OPEN/EXHAUSTED contract")
    # Layer 9 (constraint): the ingredient must be ACTIVE
    if ing["status"] != "ACTIVE":
        raise ApiError("ERR_INGREDIENT_NOT_ACTIVE", 422,
                       "Cannot create a contract for a DISCONTINUED ingredient")
    rec = make_record()
    rec.update(ingredient_id=ingredient_id, supplier_ref=supplier_ref,
               fixed_price_cents_per_ton=fixed_price, total_tons=total_tons,
               window_start=window_start, window_end=window_end, status="OPEN")
    STORE["contracts"][rec["id"]] = rec
    recompute_provisional_for_ingredient(ingredient_id)
    return success(ser_contract(rec), 201)


@bp.get("/api/contracts")
def list_contracts():
    uid, role = authenticate()
    authorize(role, uid, ALL_ROLES)
    ingredient_id = None
    status = None
    from flask import request
    ingredient_id = request.args.get("ingredient_id")
    status = request.args.get("status")
    expiry_sweep_list()
    items = sorted_items(STORE["contracts"])
    if ingredient_id is not None:
        items = [c for c in items if c["ingredient_id"] == ingredient_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success([ser_contract(c) for c in page], 200, meta)


def expiry_sweep_list():
    for c in list(STORE["contracts"].values()):
        maybe_expire_contract(c)


@bp.get("/api/contracts/<cid>")
def get_contract(cid):
    uid, role = authenticate()
    authorize(role, uid, ALL_ROLES)
    c = _get_contract(cid)
    maybe_expire_contract(c)
    return success(ser_contract(c), 200)


@bp.post("/api/contracts/<cid>/cancel")
def cancel_contract(cid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    c = _get_contract(cid)
    maybe_expire_contract(c)
    if c["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an OPEN contract can be cancelled")
    c["status"] = "CANCELLED"
    bump(c)
    recompute_provisional_for_ingredient(c["ingredient_id"])
    return success(ser_contract(c), 200)
