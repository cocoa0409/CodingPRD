"""Certificate of Analysis endpoints and the acceptance gate (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth
from response import ok_object, ok_array
from services.common import (
    get_json_body, require_fields, require_str, require_bool, require_int,
    parse_pagination, created_sort_key, paginate,
)
from services.entities import base_fields, touch, get_lot_or_404, get_coa_or_404
from services.serialize import public
from services.lots import finalized_expiration, _store_dt
from services.common import parse_dt

bp = Blueprint("coa", __name__)

SUSPEND_STREAK = 3

ALL_ROLES = ["QualityManager", "ReceivingClerk", "ProductionOperator", "SafetyAuditor"]


@bp.post("/traceability/coa")
def attach_coa():
    require_auth(["ReceivingClerk", "QualityManager"])
    body = get_json_body()
    require_fields(body, ["lot_id", "pathogen_pass", "declared_shelf_life_days"])
    lot_id = require_str(body, "lot_id")
    pathogen_pass = require_bool(body, "pathogen_pass")
    declared_shelf_life_days = require_int(body, "declared_shelf_life_days")

    measured = body.get("measured_allergen_codes")
    if measured is None:
        measured = []
    if not isinstance(measured, list) or not all(isinstance(c, str) for c in measured):
        raise err("ERR_INVALID_REQUEST", "measured_allergen_codes must be a list of strings")

    # FK resolution.
    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", "Lot not found")

    rec = base_fields(common=True)
    rec.update({
        "lot_id": lot_id,
        "supplier_id": lot.get("supplier_id"),  # copied from the lot
        "measured_allergen_codes": list(measured),
        "pathogen_pass": pathogen_pass,
        "declared_shelf_life_days": declared_shelf_life_days,
        "status": "PENDING",
        "rejection_reason": None,
    })
    db.coas[rec["id"]] = rec

    # Lot.coa_status := PENDING on attachment.
    lot["coa_status"] = "PENDING"
    touch(lot)

    return ok_object(public(rec), 201)


@bp.get("/traceability/coa/<cid>")
def get_coa(cid):
    require_auth(ALL_ROLES)
    rec = get_coa_or_404(cid)
    return ok_object(public(rec), 200)


@bp.get("/traceability/coa")
def list_coa():
    require_auth(ALL_ROLES)
    items = list(db.coas.values())
    lot_id = request.args.get("lot_id")
    supplier_id = request.args.get("supplier_id")
    if lot_id is not None:
        items = [x for x in items if x["lot_id"] == lot_id]
    if supplier_id is not None:
        items = [x for x in items if x.get("supplier_id") == supplier_id]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)


@bp.post("/traceability/coa/<cid>/decide")
def decide_coa(cid):
    require_auth(["QualityManager"])
    coa = get_coa_or_404(cid)
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = require_str(body, "decision")
    if decision not in ("ACCEPT", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "decision must be ACCEPT or REJECT")

    # priority 8: state — COA must be PENDING.
    if coa["status"] != "PENDING":
        raise err("ERR_COA_NOT_PENDING", "COA is not in PENDING status")

    lot = db.lots.get(coa["lot_id"])
    ingredient = db.ingredients.get(lot["ingredient_id"]) if lot else None
    supplier = db.suppliers.get(coa.get("supplier_id")) if coa.get("supplier_id") else None

    if decision == "ACCEPT":
        # Accept preconditions, each with its own error (PRD §3.3).
        declared_codes = set(ingredient.get("declared_allergen_codes", [])) if ingredient else set()
        if not set(coa["measured_allergen_codes"]).issubset(declared_codes):
            raise err("ERR_COA_ALLERGEN_UNDISCLOSED",
                      "measured_allergen_codes not a subset of ingredient declared codes")
        if coa["pathogen_pass"] is not True:
            raise err("ERR_COA_PATHOGEN_FAIL", "pathogen_pass is false")
        if coa["declared_shelf_life_days"] < ingredient["shelf_life_days"]:
            raise err("ERR_COA_SHELF_LIFE_SHORT",
                      "declared_shelf_life_days shorter than ingredient shelf_life_days")

        coa["status"] = "ACCEPTED"
        # Lot.coa_status := ACCEPTED; recompute effective_expiration_date.
        if lot is not None:
            lot["coa_status"] = "ACCEPTED"
            production_date = parse_dt(lot["production_date"], "production_date")
            lot["effective_expiration_date"] = _store_dt(
                finalized_expiration(production_date, ingredient, coa)
            )
            touch(lot)
        # Supplier streak reset to 0.
        if supplier is not None:
            supplier["failed_coa_streak"] = 0
            touch(supplier)
        touch(coa)

    else:  # REJECT
        coa["status"] = "REJECTED"
        coa["rejection_reason"] = "MANUAL"
        if lot is not None:
            lot["coa_status"] = "REJECTED"
            touch(lot)
        # Supplier streak += 1; suspend at >= SUSPEND_STREAK (cascade C).
        if supplier is not None:
            supplier["failed_coa_streak"] = supplier.get("failed_coa_streak", 0) + 1
            if supplier["failed_coa_streak"] >= SUSPEND_STREAK:
                supplier["approval_status"] = "SUSPENDED"
            touch(supplier)
        touch(coa)

    return ok_object(public(coa), 200)
