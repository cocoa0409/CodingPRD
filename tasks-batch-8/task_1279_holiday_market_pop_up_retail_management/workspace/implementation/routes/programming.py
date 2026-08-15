"""ProgrammingSlot endpoints (PRD 3.7)."""
from flask import Blueprint

import db
from errors import ApiError, invalid_state
from middleware import auth, require_roles
from response import success
from services import cascades
from services.core import (
    SLOT_KINDS,
    arg,
    as_dt,
    as_enum,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    get_vendor,
    list_response,
    required,
    serialize,
    touch,
)

bp = Blueprint("programming", __name__)

MO = ("MarketOperator",)
GET_ROLES = ("MarketOperator", "VendorRole")
ACTIVE_STATUSES = ("SCHEDULED", "LIVE")


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/markets/<marketId>/programming")
def create_programming(marketId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    data = body()
    title = as_str(required(data, "title"), "title")
    slot_kind = as_enum(required(data, "slot_kind"), "slot_kind", SLOT_KINDS)
    starts_at = as_dt(required(data, "starts_at"), "starts_at")
    ends_at = as_dt(required(data, "ends_at"), "ends_at")
    vendor_id = data.get("vendor_id")
    if vendor_id is not None:
        as_str(vendor_id, "vendor_id")
        get_vendor(vendor_id)
    if not starts_at < ends_at:
        raise ApiError("ERR_SLOT_CONFLICT", "starts_at must be strictly before ends_at", 409)
    for slot in db.STORES["programming"].values():
        if (
            slot["market_id"] == marketId
            and slot["slot_kind"] == slot_kind
            and slot["vendor_id"] == vendor_id
            and slot["status"] in ACTIVE_STATUSES
            and _overlaps(starts_at, ends_at, slot["starts_at"], slot["ends_at"])
        ):
            raise ApiError(
                "ERR_SLOT_CONFLICT",
                "interval overlaps an existing slot of the same kind on the same market and vendor",
                409,
            )
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "title": title,
            "slot_kind": slot_kind,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "vendor_id": vendor_id,
            "status": "SCHEDULED",
        }
    )
    db.STORES["programming"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/programming/<slotId>")
def get_programming(marketId, slotId):
    user = auth()
    require_roles(user, GET_ROLES)
    get_market(marketId)
    cascades.sync_programming()
    return success(serialize(get_child("programming", slotId, marketId)))


@bp.get("/markets/<marketId>/programming")
def list_programming(marketId):
    user = auth()
    require_roles(user, GET_ROLES)
    get_market(marketId)
    cascades.sync_programming()
    status = arg("status")
    slot_kind = arg("slot_kind")
    vendor_id = arg("vendor_id")
    records = []
    for s in db.STORES["programming"].values():
        if s["market_id"] != marketId:
            continue
        if status is not None and s["status"] != status:
            continue
        if slot_kind is not None and s["slot_kind"] != slot_kind:
            continue
        if vendor_id is not None and s["vendor_id"] != vendor_id:
            continue
        records.append(s)
    return list_response(records)


@bp.post("/markets/<marketId>/programming/<slotId>/cancel")
def cancel_programming(marketId, slotId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    slot = get_child("programming", slotId, marketId)
    if slot["status"] != "SCHEDULED":
        raise invalid_state("only a SCHEDULED programming slot can be cancelled")
    slot["status"] = "CANCELLED"
    touch(slot)
    return success(serialize(slot))
