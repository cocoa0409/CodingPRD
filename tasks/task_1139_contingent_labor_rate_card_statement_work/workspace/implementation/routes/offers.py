from datetime import datetime

from flask import Blueprint, request

from db import clock_now, now_iso, store, touch
from envelope import ok, ok_list
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SUPPLIER_SUSPENDED,
    raise_err,
)
from security import NO_WORKER_READ, require_roles
from validators import apply_filters, get_body, paginate, req_enum
import serializers

bp = Blueprint("offers", __name__)

ACTIONS = {"ACCEPT", "DECLINE"}


def _get_offer(offer_id):
    offer = store.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_NOT_FOUND, f"Distribution offer {offer_id} not found.")
    return offer


@bp.get("/v1/distribution-offers")
def list_offers():
    require_roles(*NO_WORKER_READ)
    filters = {
        "engagement_id": request.args.get("engagement_id"),
        "supplier_id": request.args.get("supplier_id"),
        "status": request.args.get("status"),
    }
    records = apply_filters(list(store.offers.values()), filters)
    page, total, limit, offset = paginate(records, serializers.offer)
    return ok_list(page, total, limit, offset)


@bp.post("/v1/distribution-offers/expire-sweep")
def expire_sweep():
    require_roles("ProgramAdmin")
    now = clock_now()
    expired = 0
    for o in store.offers.values():
        if o["status"] != "OFFERED":
            continue
        due_dt = datetime.fromisoformat(o["response_due_at"].replace("Z", "+00:00"))
        if due_dt < now:
            o["status"] = "EXPIRED"
            touch(o)
            sup = store.suppliers.get(o["supplier_id"])
            if sup is not None:
                sup["open_offers_count"] -= 1
                touch(sup)
            expired += 1
    return ok({"expired_count": expired})


@bp.get("/v1/distribution-offers/<offer_id>")
def get_offer(offer_id):
    require_roles(*NO_WORKER_READ)
    return ok(serializers.offer(_get_offer(offer_id)))


@bp.post("/v1/distribution-offers/<offer_id>/respond")
def respond_offer(offer_id):
    uid, _ = require_roles("SupplierCoordinator")
    body = get_body()
    action = req_enum(body, "action", ACTIONS)
    offer = _get_offer(offer_id)
    if uid != offer["supplier_id"]:
        raise_err(ERR_FORBIDDEN, "A SupplierCoordinator may only respond to its own offers.")
    if offer["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "Only an OFFERED offer can be responded to.")
    sup = store.suppliers.get(offer["supplier_id"])
    if action == "ACCEPT" and sup is not None and sup["status"] != "ACTIVE":
        raise_err(ERR_SUPPLIER_SUSPENDED, "A suspended supplier cannot accept offers.")
    if sup is not None:
        sup["open_offers_count"] -= 1
        touch(sup)
    offer["responded_at"] = now_iso()
    if action == "ACCEPT":
        offer["status"] = "ACCEPTED"
        eng = store.engagements.get(offer["engagement_id"])
        if eng is not None and eng["status"] == "FILLING":
            eng["status"] = "ACTIVE"
            if eng["awarded_supplier_id"] is None:
                eng["awarded_supplier_id"] = offer["supplier_id"]
            touch(eng)
    else:
        offer["status"] = "DECLINED"
    touch(offer)
    return ok(serializers.offer(offer))


@bp.post("/v1/distribution-offers/<offer_id>/withdraw")
def withdraw_offer(offer_id):
    require_roles("ProgramAdmin")
    offer = _get_offer(offer_id)
    if offer["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "Only an OFFERED offer can be withdrawn.")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    sup = store.suppliers.get(offer["supplier_id"])
    if sup is not None:
        sup["open_offers_count"] -= 1
        touch(sup)
    return ok(serializers.offer(offer))
