"""Lot endpoints: receiving, presize, diversion (PRD 3.1, 3.3)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_BLOCK_GROWER_MISMATCH,
    ERR_LOT_INVALID_STATE,
    ERR_RUN_WEIGHT_MISMATCH,
)
from middleware import authorized, check_grower_scope, ALL_ROLES
from response import success_object
from routes.helpers import list_response, public, sorted_items
from services.core import new_record, touch
from services.domain import release_allocation
from util import CLOCK, round_half_up
from validate import (
    check_body_fk, get_body, req_num, req_int, req_pct, req_str,
    require_path_resource,
)

bp = Blueprint("lots", __name__)


@bp.post("/lots")
def create_lot():
    authorized(["Admin", "ReceivingClerk"])
    body = get_body()
    # Tier 4: body-supplied FK existence (grower_id, then block_id).
    grower = check_body_fk("growers", body.get("grower_id"), "grower_id")
    block = check_body_fk("blocks", body.get("block_id"), "block_id")
    # Tier 5: request shape.
    grower_id = req_str(body, "grower_id")
    block_id = req_str(body, "block_id")
    received_bin_count = req_int(body, "received_bin_count", positive=True)
    received_weight_lbs = req_num(body, "received_weight_lbs", positive=True)
    avg_color_pct = req_pct(body, "avg_color_pct")
    if grower is None:
        grower = db["growers"][grower_id]
    if block is None:
        block = db["blocks"][block_id]
    # Tier 8: block-to-grower referential check.
    if block["grower_id"] != grower_id:
        raise_error(ERR_BLOCK_GROWER_MISMATCH,
                    "block does not belong to the stated grower")
    now = CLOCK.now_iso()
    rec = new_record("lots", {
        "grower_id": grower_id,
        "block_id": block_id,
        "received_bin_count": received_bin_count,
        "received_weight_lbs": received_weight_lbs,
        "avg_color_pct": avg_color_pct,
        "received_at": now,
        "size_small_lbs": Decimal("0"),
        "size_medium_lbs": Decimal("0"),
        "size_large_lbs": Decimal("0"),
        "presize_cull_lbs": Decimal("0"),
        "est_packout_pct": None,
        "actual_packout_pct": None,
        "diverted_weight_lbs": Decimal("0"),
        "weight_balance_lbs": received_weight_lbs,
        "status": "RECEIVED",
    })
    return success_object(public(rec), status=201)


@bp.get("/lots/<lotId>")
def get_lot(lotId):
    caller = authorized(list(ALL_ROLES))
    lot = require_path_resource("lots", lotId)
    check_grower_scope(caller, lot["grower_id"])
    return success_object(public(lot))


@bp.get("/lots")
def list_lots():
    caller = authorized(list(ALL_ROLES))
    items = sorted_items("lots")
    if caller.role == "Grower":
        # Force-filtered to the caller's own grower_id (PRD 2.1).
        items = [l for l in items if l["grower_id"] == caller.user_id]
    f_grower = request.args.get("grower_id")
    f_block = request.args.get("block_id")
    f_status = request.args.get("status")
    if f_grower is not None and caller.role != "Grower":
        items = [l for l in items if l["grower_id"] == f_grower]
    if f_block is not None:
        items = [l for l in items if l["block_id"] == f_block]
    if f_status is not None:
        items = [l for l in items if l["status"] == f_status]
    return list_response(items)


@bp.post("/lots/<lotId>/presize")
def presize_lot(lotId):
    authorized(["Admin", "ReceivingClerk"])
    lot = require_path_resource("lots", lotId)
    body = get_body()
    small = req_num(body, "size_small_lbs", non_negative=True)
    medium = req_num(body, "size_medium_lbs", non_negative=True)
    large = req_num(body, "size_large_lbs", non_negative=True)
    cull = req_num(body, "presize_cull_lbs", non_negative=True)
    # Tier 8: presize requires a RECEIVED lot.
    if lot["status"] != "RECEIVED":
        raise_error(ERR_LOT_INVALID_STATE,
                    f"presize requires a RECEIVED lot, found {lot['status']}")
    # Tier 11: the profile must sum exactly to the received weight.
    total = small + medium + large + cull
    if total != lot["received_weight_lbs"]:
        raise_error(ERR_RUN_WEIGHT_MISMATCH,
                    "presize profile does not sum exactly to received_weight_lbs")
    lot["size_small_lbs"] = small
    lot["size_medium_lbs"] = medium
    lot["size_large_lbs"] = large
    lot["presize_cull_lbs"] = cull
    lot["est_packout_pct"] = round_half_up(
        Decimal("100") * (small + medium + large) / total, 1)
    lot["status"] = "PRESIZED"
    touch(lot)
    return success_object(public(lot))


@bp.post("/lots/<lotId>/divert")
def divert_lot(lotId):
    authorized(["Admin", "StorageOperator"])
    lot = require_path_resource("lots", lotId)
    # Tier 8: diversion requires a RECEIVED or IN_STORAGE lot.
    if lot["status"] not in ("RECEIVED", "IN_STORAGE"):
        raise_error(ERR_LOT_INVALID_STATE,
                    f"divert requires a RECEIVED or IN_STORAGE lot, found {lot['status']}")
    lot["diverted_weight_lbs"] = lot["weight_balance_lbs"]
    lot["weight_balance_lbs"] = Decimal("0")
    lot["status"] = "DIVERTED"
    touch(lot)
    # Cascade: every ACTIVE allocation of the lot releases with reason DIVERSION.
    for alloc in sorted(
            (a for a in db["allocations"].values()
             if a["lot_id"] == lot["id"] and a["status"] == "ACTIVE"),
            key=lambda a: a["_seq"]):
        room = db["ca_rooms"][alloc["room_id"]]
        release_allocation(alloc, room, "DIVERSION")
    return success_object(public(lot))
