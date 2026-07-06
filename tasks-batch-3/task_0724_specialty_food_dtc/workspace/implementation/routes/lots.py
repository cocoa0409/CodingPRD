from flask import Blueprint

from db import db, new_common, public, touch
from clock import clock, parse_iso
from middleware import auth, require_role
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_LABEL_NOT_APPROVED,
    ERR_LOT_EXPIRED,
)
from helpers import (
    body,
    require_str,
    require_int,
    find_sku,
    find_lot,
)
from response import ok_object
from services import domain

bp = Blueprint("lots", __name__)


def serialize_lot(l):
    return public(l)


@bp.post("/lots")
def create_lot():
    _, role = auth()
    require_role(role, {"InventoryManager"})
    data = body()
    sku_id = require_str(data, "sku_id")
    lot_code = require_str(data, "lot_code")
    produced_units = require_int(data, "produced_units", minimum=1)
    expiry_iso = require_str(data, "expiry_iso")
    if parse_iso(expiry_iso) is None:
        raise err(ERR_INVALID_REQUEST, "Invalid expiry_iso")
    find_sku(sku_id)  # existence

    lid = db.new_id()
    lot = {
        "id": lid,
        "sku_id": sku_id,
        "lot_code": lot_code,
        "produced_units": produced_units,
        "remaining_units": 0,
        "expiry_iso": expiry_iso,
        "status": "QUARANTINE",
    }
    lot.update(new_common())
    db.lots[lid] = lot
    return ok_object(serialize_lot(lot), 201)


@bp.get("/lots/<lid>")
def get_lot(lid):
    _, role = auth()
    require_role(role, {"PlatformAdmin", "InventoryManager"})
    return ok_object(serialize_lot(find_lot(lid)))


@bp.post("/lots/<lid>/release")
def release_lot(lid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    data = body()
    lot = find_lot(lid)
    # request shape
    if "expected_lot_version" not in data or data["expected_lot_version"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing expected_lot_version")
    expected = data["expected_lot_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_lot_version must be an integer")
    # OCC (priority 7) before state check (priority 8)
    if expected != lot["version"]:
        raise err(ERR_STALE_VERSION, "Stale lot version")
    if lot["status"] != "QUARANTINE":
        raise err(ERR_INVALID_STATE, "Release requires QUARANTINE")
    # business-safety: label approved (priority 9) before expiry (priority 11)
    sku = db.skus[lot["sku_id"]]
    if not sku["label_approved"]:
        raise err(ERR_LABEL_NOT_APPROVED, "Parent SKU label not approved")
    exp = parse_iso(lot["expiry_iso"])
    if not (exp is not None and clock.now() < exp):
        raise err(ERR_LOT_EXPIRED, "Lot expired")

    lot["status"] = "RELEASED"
    lot["remaining_units"] = lot["produced_units"]
    touch(lot)
    domain.recompute_sku_availability(sku)
    return ok_object(serialize_lot(lot))


@bp.post("/lots/<lid>/recall")
def recall_lot(lid):
    _, role = auth()
    require_role(role, {"ComplianceOfficer"})
    lot = find_lot(lid)
    if lot["status"] != "RELEASED":
        raise err(ERR_INVALID_STATE, "Recall requires RELEASED")
    lot["status"] = "RECALLED"
    lot["remaining_units"] = 0
    touch(lot)
    sku = db.skus[lot["sku_id"]]
    avail = domain.recompute_sku_availability(sku)
    if avail == 0:
        domain.auto_pause_subscriptions_for_sku(sku["id"])
    return ok_object(serialize_lot(lot))
