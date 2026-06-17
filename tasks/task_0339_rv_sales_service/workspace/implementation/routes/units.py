"""Unit routes (PRD 3.1, 3.2)."""

from flask import Blueprint, request

import db
import errors
from common import (body, new_entity, touch, require_str, require_int, require_enum,
                    opt_enum, CLASS_TYPES, ACQUISITIONS, paginate, get_or_404,
                    find_dealership)
from middleware import get_auth, require_role
from response import ok, created, ok_list
from services import recompute_open_recall_count

bp = Blueprint("units", __name__)


def _scan_recalls_for_new_unit(unit):
    """On unit create, attach PENDING remedies for existing OPEN campaigns in scope."""
    count = 0
    for campaign in db.store["recall_campaigns"].values():
        if (campaign["status"] == "OPEN"
                and campaign["dealership_id"] == unit["dealership_id"]
                and campaign["target_class_type"] == unit["class_type"]
                and campaign["target_model_year"] == unit["model_year"]):
            remedy = new_entity({
                "dealership_id": unit["dealership_id"],
                "recall_campaign_id": campaign["id"],
                "unit_id": unit["id"],
                "status": "PENDING",
            })
            db.store["recall_remedies"][remedy["id"]] = remedy
            count += 1
    unit["open_recall_count"] = count


@bp.post("/units")
def create_unit():
    _, role = get_auth()
    require_role(role, {"SalesAgent", "DealerManager"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)

    acquisition = opt_enum(data, "acquisition", ACQUISITIONS, "STOCK")
    consignor_id = data.get("consignor_customer_id")

    # Existence of consignor FK (priority 3) before business-referential rules.
    if consignor_id is not None:
        get_or_404("customers", consignor_id)

    # Business-referential consignor consistency (priority 6).
    if acquisition == "CONSIGNMENT":
        if (consignor_id is None
                or data.get("consignment_floor_cents") is None
                or data.get("consignment_fee_bps") is None):
            errors.err("ERR_CONSIGNOR_REQUIRED",
                       "Consignment units require consignor_customer_id, floor and fee.")
    else:
        if consignor_id is not None:
            errors.err("ERR_CONSIGNOR_NOT_ALLOWED",
                       "consignor_customer_id is only allowed on consignment units.")

    # Field-level validation (priority 13).
    vin = require_str(data, "vin")
    model_year = require_int(data, "model_year", minimum=1990, maximum=2100)
    class_type = require_enum(data, "class_type", CLASS_TYPES)
    list_price = require_int(data, "list_price_cents", minimum=0)

    floor = None
    fee = None
    if acquisition == "CONSIGNMENT":
        floor = require_int(data, "consignment_floor_cents", minimum=0)
        fee = require_int(data, "consignment_fee_bps", minimum=0)

    # vin unique per dealership
    for u in db.store["units"].values():
        if u["dealership_id"] == did and u["vin"] == vin:
            errors.err("ERR_DUPLICATE_VIN", "vin already used in this dealership.")

    rec = new_entity({
        "dealership_id": did,
        "vin": vin,
        "model_year": model_year,
        "class_type": class_type,
        "acquisition": acquisition,
        "consignor_customer_id": consignor_id,
        "trade_in_origin_unit_id": None,
        "list_price_cents": list_price,
        "consignment_floor_cents": floor,
        "consignment_fee_bps": fee,
        "open_recall_count": 0,
        "status": "AVAILABLE",
        "active_hold_deal_id": None,
    })
    _scan_recalls_for_new_unit(rec)
    db.store["units"][rec["id"]] = rec
    return created(rec)


@bp.get("/units")
def list_units():
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    items = list(db.store["units"].values())
    a = request.args
    for field in ("dealership_id", "consignor_customer_id", "trade_in_origin_unit_id",
                  "active_hold_deal_id", "status"):
        val = a.get(field)
        if val is not None:
            items = [u for u in items if u.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/units/<unit_id>")
def get_unit(unit_id):
    user_id, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor", "Customer"})
    rec = get_or_404("units", unit_id)
    return ok(rec)


@bp.post("/units/<unit_id>/return-consignment")
def return_consignment(unit_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    unit = get_or_404("units", unit_id)
    if unit["acquisition"] != "CONSIGNMENT":
        errors.err("ERR_NOT_CONSIGNMENT", "Unit is not a consignment.")
    if unit["status"] != "AVAILABLE":
        errors.err("ERR_UNIT_NOT_AVAILABLE", "Unit is not available.")
    unit["status"] = "CONSIGNMENT_RETURNED"
    touch(unit)
    return ok(unit)
