"""Bins: physical stock with ingredient assignment (PRD 3.3)."""
from decimal import Decimal

from flask import Blueprint, request

from db import STORE, make_record, bump
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import ser_bin, bin_on_hand, bin_status, sorted_items
from validation import get_body, req_str, req_num, req_tons, paginate

bp = Blueprint("bins", __name__)

READ_ROLES = {"MillManager", "Nutritionist", "Operator", "QualityTech"}


def _get_bin(bid):
    b = STORE["bins"].get(bid)
    if b is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bin {bid} not found")
    return b


@bp.post("/api/bins")
def create_bin():
    uid, role = authenticate()
    data = get_body()
    code = req_str(data, "code")
    capacity = req_num(data, "capacity_tons", gt=Decimal("0"))
    authorize(role, uid, {"MillManager"})
    if any(b["code"] == code for b in STORE["bins"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, f"Bin code {code!r} already exists")
    rec = make_record()
    rec.update(code=code, capacity_tons=capacity, ingredient_id=None,
               cumulative_replenished_tons=Decimal("0"), blocked=False)
    STORE["bins"][rec["id"]] = rec
    return success(ser_bin(rec), 201)


@bp.get("/api/bins")
def list_bins():
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    ingredient_id = request.args.get("ingredient_id")
    status = request.args.get("status")
    items = sorted_items(STORE["bins"])
    if ingredient_id is not None:
        items = [b for b in items if b["ingredient_id"] == ingredient_id]
    if status is not None:
        items = [b for b in items if bin_status(b) == status]
    page, meta = paginate(items)
    return success([ser_bin(b) for b in page], 200, meta)


@bp.get("/api/bins/<bid>")
def get_bin(bid):
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    return success(ser_bin(_get_bin(bid)), 200)


@bp.post("/api/bins/<bid>/assign")
def assign_bin(bid):
    uid, role = authenticate()
    data = get_body()
    ingredient_id = req_str(data, "ingredient_id")
    authorize(role, uid, {"MillManager"})
    b = _get_bin(bid)
    if ingredient_id not in STORE["ingredients"]:
        raise ApiError("ERR_NOT_FOUND", 404, f"Ingredient {ingredient_id} not found")
    # Assignable only while on_hand_tons is exactly zero (boundary passes).
    if bin_on_hand(b) != 0:
        raise ApiError("ERR_BIN_NOT_EMPTY", 409, "Bin holds stock and cannot be reassigned")
    b["ingredient_id"] = ingredient_id
    bump(b)
    return success(ser_bin(b), 200)


@bp.post("/api/bins/<bid>/replenish")
def replenish_bin(bid):
    uid, role = authenticate()
    data = get_body()
    tons = req_tons(data, "tons")
    authorize(role, uid, {"MillManager"})
    b = _get_bin(bid)
    if b["blocked"]:
        raise ApiError("ERR_BIN_BLOCKED", 409, "Bin is BLOCKED")
    if b["ingredient_id"] is None:
        raise ApiError("ERR_INVALID_STATE", 409, "Bin has no ingredient assigned")
    if bin_on_hand(b) + tons > b["capacity_tons"]:
        raise ApiError("ERR_BIN_CAPACITY_EXCEEDED", 422,
                       "Replenishment would exceed capacity_tons")
    b["cumulative_replenished_tons"] += tons
    bump(b)
    return success(ser_bin(b), 200)


@bp.post("/api/bins/<bid>/unblock")
def unblock_bin(bid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    b = _get_bin(bid)
    if not b["blocked"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Bin is not BLOCKED")
    if bin_on_hand(b) <= 0:
        raise ApiError("ERR_INVALID_STATE", 409, "An empty blocked bin cannot be unblocked")
    b["blocked"] = False
    bump(b)
    return success(ser_bin(b), 200)
