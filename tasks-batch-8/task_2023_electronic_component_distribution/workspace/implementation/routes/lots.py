"""InventoryLot and MoistureExposure endpoints."""

from flask import Blueprint, request

import clock
import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    get_json_body,
    get_lot_or_404,
    mint_id,
    opt_str,
    paginate,
    pagination_params,
    recompute_part_availability,
    req_enum,
    req_int,
    req_str,
    serialize_exposure,
    serialize_lot,
    stamp_clock,
    stamp_now,
    valid_date_code,
)

bp = Blueprint("lots", __name__)

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


@bp.post("/lots")
def create_lot():
    user_id, role = require_auth()
    require_role(user_id, role, {"WarehouseOps"})
    body = get_json_body()
    part_id = req_str(body, "part_id")
    date_code = req_str(body, "date_code")
    qty_received = req_int(body, "qty_received")
    source_type = req_enum(body, "source_type", {"FRANCHISED", "OPEN_MARKET"})
    if qty_received <= 0:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "qty_received must be positive.")
    if not valid_date_code(date_code):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "date_code must be YYYYMM.")

    part = db.parts.get(part_id)
    if part is None:
        raise ApiError(E.ERR_PART_NOT_FOUND, 404, "Part not found.")

    mline = db.manufacturer_lines.get(part["manufacturer_line_id"])
    if source_type == "FRANCHISED" and (
        mline is None or mline["sourcing_channel"] != "FRANCHISED"
    ):
        raise ApiError(
            E.ERR_CHANNEL_MISMATCH,
            409,
            "FRANCHISED lot requires a FRANCHISED manufacturer line.",
        )

    now = stamp_now()
    if source_type == "FRANCHISED":
        status = "AVAILABLE"
        authenticity = "NOT_REQUIRED"
    else:
        status = "IN_INSPECTION"
        authenticity = "PENDING_INSPECTION"
    lot = {
        "id": mint_id(),
        "part_id": part_id,
        "date_code": date_code,
        "qty_received": qty_received,
        "qty_on_hand": qty_received,
        "qty_reserved": 0,
        "qty_shipped": 0,
        "source_type": source_type,
        "authenticity": authenticity,
        "last_baked_at": None,
        "_last_baked_at": None,
        "received_by_user_id": user_id,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.inventory_lots[lot["id"]] = lot
    recompute_part_availability(part_id)
    return success(serialize_lot(lot), status=201)


@bp.get("/lots")
def list_lots():
    require_auth()
    limit, offset = pagination_params()
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    authenticity = request.args.get("authenticity")
    items = list(db.inventory_lots.values())
    if part_id is not None:
        items = [l for l in items if l["part_id"] == part_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if authenticity is not None:
        items = [l for l in items if l["authenticity"] == authenticity]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_lot(l) for l in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/lots/<lotId>")
def get_lot(lotId):
    require_auth()
    lot = get_lot_or_404(lotId)
    return success(serialize_lot(lot), status=200)


@bp.post("/lots/<lotId>/inspect")
def inspect_lot(lotId):
    user_id, role = require_auth()
    require_role(user_id, role, {"QualityInspector"})
    body = get_json_body()
    disposition = body.get("disposition")
    if disposition not in ("AUTHENTICATE", "REJECT"):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "disposition must be AUTHENTICATE or REJECT.")
    lot = get_lot_or_404(lotId)
    if lot["status"] != "IN_INSPECTION":
        raise ApiError(E.ERR_INSPECTION_NOT_PENDING, 409, "Lot is not IN_INSPECTION.")
    if user_id == lot["received_by_user_id"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES,
            403,
            "Inspector must differ from the lot's receiver.",
        )
    if disposition == "AUTHENTICATE":
        lot["status"] = "AVAILABLE"
        lot["authenticity"] = "AUTHENTICATED"
    else:
        lot["status"] = "REJECTED"
        lot["authenticity"] = "REJECTED"
    lot["updated_at"] = stamp_now()
    lot["version"] += 1
    recompute_part_availability(lot["part_id"])
    return success(serialize_lot(lot), status=200)


@bp.post("/lots/<lotId>/exposures")
def open_exposure(lotId):
    user_id, role = require_auth()
    require_role(user_id, role, {"WarehouseOps"})
    body = get_json_body()
    note = body.get("note", "")
    if not isinstance(note, str):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid note.")
    lot = get_lot_or_404(lotId)
    if lot["status"] != "AVAILABLE":
        raise ApiError(E.ERR_LOT_NOT_AVAILABLE, 409, "Lot is not AVAILABLE.")
    for exp in db.moisture_exposures.values():
        if exp["lot_id"] == lotId and exp["sealed_at"] is None:
            raise ApiError(
                E.ERR_EXPOSURE_ALREADY_OPEN,
                409,
                "Another exposure interval of this lot is still open.",
            )
    now = stamp_now()
    exp = {
        "id": mint_id(),
        "lot_id": lotId,
        "opened_at": stamp_clock(),
        "_opened_at": clock.now(),
        "sealed_at": None,
        "_sealed_at": None,
        "note": note,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.moisture_exposures[exp["id"]] = exp
    return success(serialize_exposure(exp), status=201)


@bp.get("/lots/<lotId>/exposures")
def list_exposures(lotId):
    require_auth()
    get_lot_or_404(lotId)
    limit, offset = pagination_params()
    items = [e for e in db.moisture_exposures.values() if e["lot_id"] == lotId]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_exposure(e) for e in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.post("/lots/<lotId>/exposures/<exposureId>/seal")
def seal_exposure(lotId, exposureId):
    user_id, role = require_auth()
    require_role(user_id, role, {"WarehouseOps"})
    get_lot_or_404(lotId)
    exp = db.moisture_exposures.get(exposureId)
    if exp is None or exp["lot_id"] != lotId:
        raise ApiError(E.ERR_EXPOSURE_NOT_FOUND, 404, "Exposure not found for this lot.")
    if exp["sealed_at"] is not None:
        raise ApiError(E.ERR_EXPOSURE_NOT_OPEN, 409, "Exposure interval is already sealed.")
    exp["sealed_at"] = stamp_clock()
    exp["_sealed_at"] = clock.now()
    exp["updated_at"] = stamp_now()
    exp["version"] += 1
    return success(serialize_exposure(exp), status=200)


@bp.post("/lots/<lotId>/bake")
def bake_lot(lotId):
    user_id, role = require_auth()
    require_role(user_id, role, {"WarehouseOps"})
    lot = get_lot_or_404(lotId)
    if lot["status"] != "QUARANTINED":
        raise ApiError(E.ERR_LOT_NOT_QUARANTINED, 409, "Lot is not QUARANTINED.")
    for exp in db.moisture_exposures.values():
        if exp["lot_id"] == lotId and exp["sealed_at"] is None:
            raise ApiError(
                E.ERR_EXPOSURE_ALREADY_OPEN,
                409,
                "An exposure interval of this lot is still open.",
            )
    lot["last_baked_at"] = stamp_clock()
    lot["_last_baked_at"] = clock.now()
    lot["status"] = "AVAILABLE"
    lot["updated_at"] = stamp_now()
    lot["version"] += 1
    recompute_part_availability(lot["part_id"])
    return success(serialize_lot(lot), status=200)
