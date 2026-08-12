"""Ingredient catalogue and append-only spot price ticks (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

from db import STORE, make_record, bump, clock_now, now_iso, next_seq, new_id
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize, ALL_ROLES
from services import (ser_ingredient, ser_price_tick, sorted_items,
                      discontinue_cascade, recompute_provisional_for_ingredient)
from validation import get_body, req_str, req_enum, opt_bool, req_num, req_int, req_dt, paginate

bp = Blueprint("ingredients", __name__)


def _get_ingredient(iid):
    ing = STORE["ingredients"].get(iid)
    if ing is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Ingredient {iid} not found")
    return ing


@bp.post("/api/ingredients")
def create_ingredient():
    uid, role = authenticate()
    data = get_body()
    code = req_str(data, "code")
    name = req_str(data, "name")
    hazard_class = req_enum(data, "hazard_class", ("STANDARD", "MEDICATED"))
    is_flush_material = opt_bool(data, "is_flush_material", False)
    protein = req_num(data, "crude_protein_pct", ge=Decimal("0"))
    fiber = req_num(data, "crude_fiber_pct", ge=Decimal("0"))
    energy = req_num(data, "metabolizable_energy_kcal_kg", ge=Decimal("0"))
    authorize(role, uid, {"MillManager"})
    if any(i["code"] == code for i in STORE["ingredients"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, f"Ingredient code {code!r} already exists")
    rec = make_record()
    rec.update(code=code, name=name, hazard_class=hazard_class,
               is_flush_material=is_flush_material, crude_protein_pct=protein,
               crude_fiber_pct=fiber, metabolizable_energy_kcal_kg=energy,
               status="ACTIVE")
    STORE["ingredients"][rec["id"]] = rec
    return success(ser_ingredient(rec), 201)


@bp.get("/api/ingredients/<iid>")
def get_ingredient(iid):
    uid, role = authenticate()
    authorize(role, uid, ALL_ROLES)
    return success(ser_ingredient(_get_ingredient(iid)), 200)


@bp.post("/api/ingredients/<iid>/discontinue")
def discontinue_ingredient(iid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    ing = _get_ingredient(iid)
    if ing["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Ingredient is not ACTIVE")
    ing["status"] = "DISCONTINUED"
    bump(ing)
    discontinue_cascade(ing)
    return success(ser_ingredient(ing), 200)


@bp.post("/api/price-ticks")
def create_price_tick():
    uid, role = authenticate()
    data = get_body()
    ingredient_id = req_str(data, "ingredient_id")
    price = req_int(data, "price_cents_per_ton", gt=0)
    effective_from = req_dt(data, "effective_from")
    authorize(role, uid, {"MillManager"})
    _get_ingredient(ingredient_id)
    # PriceTick is an immutable append-only event: id + created_at only (PRD 2.4)
    rec = {
        "id": new_id(),
        "ingredient_id": ingredient_id,
        "price_cents_per_ton": price,
        "effective_from": effective_from,
        "created_at": now_iso(),
        "_created_dt": clock_now(),
        "_seq": next_seq(),
    }
    STORE["price_ticks"][rec["id"]] = rec
    recompute_provisional_for_ingredient(ingredient_id)
    return success(ser_price_tick(rec), 201)


@bp.get("/api/ingredients/<iid>/price-ticks")
def list_price_ticks(iid):
    uid, role = authenticate()
    authorize(role, uid, ALL_ROLES)
    _get_ingredient(iid)
    items = [t for t in sorted_items(STORE["price_ticks"]) if t["ingredient_id"] == iid]
    page, meta = paginate(items)
    return success([ser_price_tick(t) for t in page], 200, meta)
