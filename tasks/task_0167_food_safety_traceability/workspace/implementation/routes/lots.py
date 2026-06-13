"""Lot endpoints: receive, get, list, release, reject, recall-trace
(PRD §3.2, §3.9)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth
from response import ok_object, ok_array
from services.common import (
    get_json_body, require_fields, require_str, require_number,
    parse_pagination, created_sort_key, paginate, parse_dt,
)
from services.entities import (
    base_fields, touch, get_facility_or_404, get_ingredient_or_404,
    get_supplier_or_404, get_lot_or_404,
)
from services.serialize import public
from services.lots import create_raw_lot, lot_effective_expiration
from services.recall import recall_trace

bp = Blueprint("lots", __name__)

ALL_ROLES = ["QualityManager", "ReceivingClerk", "ProductionOperator", "SafetyAuditor"]


@bp.post("/traceability/lots")
def receive_lot():
    require_auth(["ReceivingClerk", "QualityManager"])
    body = get_json_body()

    # priority 4: body well-formedness.
    require_fields(body, ["facility_id", "ingredient_id", "lot_code", "lot_kind",
                          "received_qty", "production_date"])
    facility_id = require_str(body, "facility_id")
    ingredient_id = require_str(body, "ingredient_id")
    lot_code = require_str(body, "lot_code")
    lot_kind = require_str(body, "lot_kind")
    received_qty = require_number(body, "received_qty", positive=True)
    require_str(body, "production_date")

    # Clients may only POST RAW_MATERIAL (scaffold §1.1, PRD §3.2).
    if lot_kind != "RAW_MATERIAL":
        raise err("ERR_INVALID_REQUEST", "lot_kind must be RAW_MATERIAL")

    supplier_id = body.get("supplier_id")
    if supplier_id is not None and not isinstance(supplier_id, str):
        raise err("ERR_INVALID_REQUEST", "supplier_id must be a string")
    expiration_date = body.get("expiration_date")

    # priority 5: FK resolution + same-facility ownership.
    facility = db.facilities.get(facility_id)
    if facility is None:
        # facility_id is a body FK; per §2.6 path existence is separate, but the
        # facility here is in the body. Missing -> cross-facility/FK family.
        raise err("ERR_FACILITY_NOT_FOUND", "Facility not found")
    ingredient = db.ingredients.get(ingredient_id)
    if ingredient is None:
        raise err("ERR_INGREDIENT_NOT_FOUND", "Ingredient not found")
    if ingredient["facility_id"] != facility_id:
        raise err("ERR_CROSS_FACILITY_REFERENCE", "Ingredient belongs to a different facility")

    supplier = None
    if supplier_id is not None:
        supplier = db.suppliers.get(supplier_id)
        if supplier is None:
            raise err("ERR_SUPPLIER_NOT_FOUND", "Supplier not found")
        if supplier["facility_id"] != facility_id:
            raise err("ERR_CROSS_FACILITY_REFERENCE", "Supplier belongs to a different facility")

    # validate production_date / expiration_date parse.
    parse_dt(body["production_date"], "production_date")
    if expiration_date is not None:
        parse_dt(expiration_date, "expiration_date")

    # priority 6: lot_code unique per (facility_id, ingredient_id).
    for lot in db.lots.values():
        if lot["facility_id"] == facility_id and lot["ingredient_id"] == ingredient_id \
                and lot["lot_code"] == lot_code:
            raise err("ERR_DUPLICATE_LOT_CODE", "lot_code already used for this facility/ingredient")

    # priority 9: supplier approval gate for a RAW_MATERIAL lot naming a supplier.
    if supplier is not None and supplier["approval_status"] != "APPROVED":
        raise err("ERR_SUPPLIER_NOT_APPROVED", "Supplier is not APPROVED")

    rec = create_raw_lot(
        facility_id=facility_id,
        ingredient=ingredient,
        supplier=supplier,
        lot_code=lot_code,
        received_qty=received_qty,
        production_date_str=body["production_date"],
        expiration_date_str=expiration_date,
        supplier_id=supplier_id,
    )
    return ok_object(public(rec), 201)


@bp.get("/traceability/lots/<lid>")
def get_lot(lid):
    require_auth(ALL_ROLES)
    rec = get_lot_or_404(lid)
    return ok_object(public(rec), 200)


@bp.get("/traceability/lots")
def list_lots():
    require_auth(ALL_ROLES)
    items = list(db.lots.values())
    facility_id = request.args.get("facility_id")
    supplier_id = request.args.get("supplier_id")
    ingredient_id = request.args.get("ingredient_id")
    status = request.args.get("status")
    if facility_id is not None:
        items = [x for x in items if x["facility_id"] == facility_id]
    if supplier_id is not None:
        items = [x for x in items if x.get("supplier_id") == supplier_id]
    if ingredient_id is not None:
        items = [x for x in items if x["ingredient_id"] == ingredient_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)


@bp.post("/traceability/lots/<lid>/release")
def release_lot(lid):
    require_auth(["QualityManager"])
    lot = get_lot_or_404(lid)
    facility = get_facility_or_404(lot["facility_id"])

    # priority 8: state.
    if lot["status"] != "RECEIVED":
        raise err("ERR_LOT_NOT_RECEIVED", "Lot is not in RECEIVED status")
    # priority 10: safety freeze precedes COA / expiry.
    if lot["hold_status"] != "FREE":
        raise err("ERR_LOT_ON_HOLD", "Lot is on hold")
    # priority 11: COA acceptance gate.
    supplier = db.suppliers.get(lot.get("supplier_id")) if lot.get("supplier_id") else None
    coa_required = supplier["coa_required"] if supplier is not None else False
    if coa_required and lot["lot_kind"] == "RAW_MATERIAL" and lot["coa_status"] != "ACCEPTED":
        raise err("ERR_COA_NOT_ACCEPTED", "COA is not ACCEPTED")
    # priority 12: expiry. current_utc must be strictly earlier than eff exp.
    current = parse_dt(facility["current_utc"], "current_utc")
    if not (current < lot_effective_expiration(lot)):
        raise err("ERR_LOT_EXPIRED", "Lot is past expiration")

    lot["status"] = "RELEASED"
    touch(lot)
    return ok_object(public(lot), 200)


@bp.post("/traceability/lots/<lid>/reject")
def reject_lot(lid):
    require_auth(["QualityManager"])
    lot = get_lot_or_404(lid)
    if lot["status"] != "RECEIVED":
        raise err("ERR_LOT_NOT_RECEIVED", "Lot is not in RECEIVED status")
    lot["status"] = "REJECTED"
    touch(lot)
    return ok_object(public(lot), 200)


@bp.get("/traceability/lots/<lid>/recall-trace")
def lot_recall_trace(lid):
    require_auth(["QualityManager", "SafetyAuditor"])
    get_lot_or_404(lid)
    return ok_object(recall_trace(lid), 200)


@bp.get("/traceability/lots/<lid>/ccp-readings")
def list_lot_ccp_readings(lid):
    require_auth(["QualityManager", "ProductionOperator", "SafetyAuditor"])
    get_lot_or_404(lid)
    items = [r for r in db.ccp_readings.values() if r["lot_id"] == lid]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)
