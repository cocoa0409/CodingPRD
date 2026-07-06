from flask import Blueprint, request

from db import db, new_common, public, touch
from middleware import auth, require_role
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
    ERR_INVALID_STATE,
    ERR_LABEL_NOT_APPROVED,
)
from helpers import (
    body,
    require_str,
    require_int,
    require_enum,
    find_sku,
    paginate,
    sorted_by_created,
    CATEGORIES,
    STORAGE_CLASSES,
    ALLERGENS,
)
from response import ok_object, ok_list
from services import domain

bp = Blueprint("skus", __name__)


def serialize_sku(s):
    return public(s)


@bp.post("/skus")
def create_sku():
    _, role = auth()
    require_role(role, {"InventoryManager", "PlatformAdmin"})
    data = body()
    name = require_str(data, "name")
    category = require_str(data, "category")
    storage_class = require_str(data, "storage_class")
    unit_price = require_int(data, "unit_price_cents", minimum=1)
    require_enum(category, CATEGORIES, "category")
    require_enum(storage_class, STORAGE_CLASSES, "storage_class")
    allergens = data.get("allergens", [])
    if allergens is None:
        allergens = []
    if not isinstance(allergens, list):
        raise err(ERR_INVALID_REQUEST, "allergens must be an array")
    for a in allergens:
        if a not in ALLERGENS:
            raise err(ERR_INVALID_ENUM, f"Invalid allergen: {a}")

    sid = db.new_id()
    sku = {
        "id": sid,
        "name": name,
        "category": category,
        "storage_class": storage_class,
        "unit_price_cents": unit_price,
        "allergens": allergens,
        "status": "DRAFT",
        "label_approved": False,
        "available_units": 0,
        "reserved_units": 0,
    }
    sku.update(new_common())
    db.skus[sid] = sku
    return ok_object(serialize_sku(sku), 201)


@bp.get("/skus")
def list_skus():
    _, role = auth()
    require_role(role, {"PlatformAdmin", "InventoryManager", "Customer", "CorporateBuyer"})
    items = list(db.skus.values())
    status = request.args.get("status")
    category = request.args.get("category")
    if status:
        items = [s for s in items if s["status"] == status]
    if category:
        items = [s for s in items if s["category"] == category]
    items = sorted_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_sku(s) for s in page], limit, offset, total)


@bp.get("/skus/<sid>")
def get_sku(sid):
    _, role = auth()
    require_role(role, {"PlatformAdmin", "InventoryManager", "Customer", "CorporateBuyer"})
    return ok_object(serialize_sku(find_sku(sid)))


@bp.post("/skus/<sid>/label/approve")
def approve_label(sid):
    _, role = auth()
    require_role(role, {"ComplianceOfficer"})
    sku = find_sku(sid)
    if sku["status"] == "DRAFT":
        sku["label_approved"] = True
        touch(sku)
    elif sku["status"] == "LABEL_HOLD":
        sku["label_approved"] = True
        sku["status"] = "ACTIVE"
        touch(sku)
    else:
        raise err(ERR_INVALID_STATE, "Label approve requires DRAFT or LABEL_HOLD")
    return ok_object(serialize_sku(sku))


@bp.post("/skus/<sid>/label/hold")
def hold_label(sid):
    _, role = auth()
    require_role(role, {"ComplianceOfficer"})
    sku = find_sku(sid)
    if sku["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Label hold requires ACTIVE")
    sku["label_approved"] = False
    sku["status"] = "LABEL_HOLD"
    touch(sku)
    domain.auto_pause_subscriptions_for_sku(sid)
    return ok_object(serialize_sku(sku))


@bp.post("/skus/<sid>/activate")
def activate_sku(sid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    sku = find_sku(sid)
    if sku["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Activate requires DRAFT")
    if not sku["label_approved"]:
        raise err(ERR_LABEL_NOT_APPROVED, "Label not approved")
    has_released_lot = any(
        l["sku_id"] == sid and l["status"] == "RELEASED" for l in db.lots.values()
    )
    if not has_released_lot:
        raise err(ERR_INVALID_STATE, "No released lot")
    sku["status"] = "ACTIVE"
    touch(sku)
    return ok_object(serialize_sku(sku))


@bp.post("/skus/<sid>/discontinue")
def discontinue_sku(sid):
    _, role = auth()
    require_role(role, {"InventoryManager"})
    sku = find_sku(sid)
    if sku["status"] not in ("ACTIVE", "LABEL_HOLD", "DRAFT"):
        raise err(ERR_INVALID_STATE, "Cannot discontinue from this state")
    sku["status"] = "DISCONTINUED"
    touch(sku)
    return ok_object(serialize_sku(sku))


@bp.get("/skus/<sid>/lots")
def list_sku_lots(sid):
    _, role = auth()
    require_role(role, {"PlatformAdmin", "InventoryManager"})
    find_sku(sid)
    from routes.lots import serialize_lot
    items = sorted_by_created([l for l in db.lots.values() if l["sku_id"] == sid])
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([serialize_lot(l) for l in page], limit, offset, total)
