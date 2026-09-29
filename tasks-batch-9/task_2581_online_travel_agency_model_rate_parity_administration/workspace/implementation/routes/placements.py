"""Preferred-placement agreements and the paid-slot capacity test (PRD 3.6)."""
from flask import Blueprint

import auth
import calc
import response
import store
import validate
from errors import ApiError
from store import created_key, db, touch

from routes import common

bp = Blueprint("placements", __name__)

LABELS = ("SPONSORED", "PREFERRED_PARTNER")
STATUSES = ("PROPOSED", "ACTIVE", "REJECTED", "CANCELLED", "EXPIRED")


@bp.post("/placement-agreements")
def create_placement():
    actor = auth.authenticate(("CommercialManager",))
    data = validate.body()
    raw_supplier = data.get("supplier_id")
    if isinstance(raw_supplier, str) and raw_supplier:
        common.find("suppliers", raw_supplier)
    raw_market = data.get("market_id")
    if isinstance(raw_market, str) and raw_market:
        common.find("markets", raw_market)
    supplier_id = validate.str_req(data, "supplier_id")
    market_id = validate.str_req(data, "market_id")
    slots = validate.int_req(data, "slots", 1, 10)
    boost_points = validate.int_req(data, "boost_points", 0, 15)
    fee_cents = validate.int_req(data, "fee_cents", 0)
    label = validate.enum_req(data, "disclosure_label", LABELS)
    window_start = validate.date_req(data, "window_start")
    window_end = validate.date_req(data, "window_end")
    common.guard_offboarded(db["suppliers"][supplier_id])
    placement = store.new_row("placements", {
        "supplier_id": supplier_id,
        "market_id": market_id,
        "slots": slots,
        "boost_points": boost_points,
        "fee_cents": fee_cents,
        "disclosure_label": label,
        "window_start": window_start,
        "window_end": window_end,
        "status": "PROPOSED",
        "proposed_by_user_id": actor.user_id,
        "approved_by_user_id": None,
        "cancellation_reason": None,
    })
    return response.obj(placement, 201)


@bp.get("/placement-agreements/<placement_id>")
def read_placement(placement_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("placements", placement_id), 200)


@bp.get("/placement-agreements")
def list_placements():
    auth.authenticate(auth.ALL_ROLES)
    supplier_id = validate.filter_str("supplier_id")
    market_id = validate.filter_str("market_id")
    status = validate.filter_enum("status", STATUSES)
    rows = []
    for row in db["placements"].values():
        if supplier_id is not None and row["supplier_id"] != supplier_id:
            continue
        if market_id is not None and row["market_id"] != market_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return common.paged(rows, key=lambda r: (r["window_start"], created_key(r)))


@bp.post("/placement-agreements/<placement_id>/approve")
def approve(placement_id):
    actor = auth.authenticate(("PlatformAdmin",))
    placement = common.find("placements", placement_id)
    data = validate.body()
    validate.str_opt(data, "note")
    supplier = db["suppliers"].get(placement["supplier_id"])
    common.guard_offboarded(supplier)
    if placement["status"] != "PROPOSED":
        raise ApiError("ERR_PLACEMENT_NOT_PROPOSED")
    auth.require_distinct(actor, placement["proposed_by_user_id"])
    if supplier is None or supplier["visibility_status"] != "ACTIVE":
        raise ApiError("ERR_SUPPLIER_NOT_CERTIFIED",
                       "The supplier's visibility_status must be ACTIVE.")
    market = db["markets"].get(placement["market_id"])
    if market is None or not calc.placement_capacity_ok(placement, market):
        raise ApiError("ERR_PLACEMENT_CAPACITY_EXCEEDED")
    placement["status"] = "ACTIVE"
    placement["approved_by_user_id"] = actor.user_id
    touch(placement)
    return response.obj(placement, 200)


@bp.post("/placement-agreements/<placement_id>/cancel")
def cancel(placement_id):
    auth.authenticate(("CommercialManager", "PlatformAdmin"))
    placement = common.find("placements", placement_id)
    data = validate.body()
    reason = validate.str_req(data, "cancellation_reason")
    if placement["status"] not in ("PROPOSED", "ACTIVE"):
        raise ApiError("ERR_PLACEMENT_NOT_PROPOSED")
    placement["status"] = "REJECTED" if placement["status"] == "PROPOSED" else "CANCELLED"
    placement["cancellation_reason"] = reason
    touch(placement)
    return response.obj(placement, 200)
