"""Weighments: listing, get, and the void compensating action (PRD 3.6)."""
from flask import Blueprint, request

from db import STORE, bump
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import (ser_weighment, sorted_items, bin_status, contract_after_void,
                      recompute_provisional_for_ingredient)
from validation import get_body, paginate

bp = Blueprint("weighments", __name__)

READ_ROLES = {"MillManager", "Nutritionist", "Operator", "QualityTech"}


def _get_weighment(wid):
    w = STORE["weighments"].get(wid)
    if w is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Weighment {wid} not found")
    return w


@bp.get("/api/weighments")
def list_weighments():
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    items = sorted_items(STORE["weighments"])
    for key in ("batch_id", "bin_id", "ingredient_id", "contract_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [w for w in items if w[key] == value]
    page, meta = paginate(items)
    return success([ser_weighment(w) for w in page], 200, meta)


@bp.get("/api/weighments/<wid>")
def get_weighment(wid):
    uid, role = authenticate()
    authorize(role, uid, READ_ROLES)
    return success(ser_weighment(_get_weighment(wid)), 200)


@bp.post("/api/weighments/<wid>/void")
def void_weighment(wid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Operator"})
    w = _get_weighment(wid)
    if w["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a RECORDED weighment can be voided")
    batch = STORE["batches"][w["batch_id"]]
    if batch["status"] != "BATCHING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Voids are allowed only while the batch is BATCHING")
    bin_rec = STORE["bins"][w["bin_id"]]
    before = bin_status(bin_rec)
    w["status"] = "VOID"
    bump(w)
    # Compensating action: on_hand_tons is derived, so voiding restores the
    # draw automatically; flip EMPTY -> READY (and bump) when stock returns.
    if bin_status(bin_rec) != before:
        bump(bin_rec)
    if w["contract_id"] is not None:
        contract = STORE["contracts"].get(w["contract_id"])
        if contract is not None:
            contract_after_void(contract)
    recompute_provisional_for_ingredient(w["ingredient_id"])
    return success(ser_weighment(w), 200)
