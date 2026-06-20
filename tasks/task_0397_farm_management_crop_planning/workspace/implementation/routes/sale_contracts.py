"""SaleContract endpoints + commit/ship/cancel logic (PRD §3.9).

SaleContract state machine (SCAFFOLD §1.2):
  OPEN -> PARTIALLY_FILLED / FILLED (commit-lot)
  PARTIALLY_FILLED -> PARTIALLY_FILLED / FILLED (commit-lot)
  FILLED -> SHIPPED (ship) — cascade lots to SHIPPED
  OPEN / PARTIALLY_FILLED -> CANCELLED (cancel) — release lots
"""
from flask import Blueprint, request

import db
import lookups
import serializers
from errors import err
from helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_number,
    require_str,
    round2,
)
from middleware import require_roles
from response import array_response, object_response

bp = Blueprint("sale_contracts", __name__)
CROPS = {"CORN", "SOY", "WHEAT", "COTTON", "ALFALFA"}
MIN_QUALITIES = {"GRADE_B", "GRADE_A"}
READ_ROLES = ("FarmManager", "SalesAgent", "Agronomist")

# Quality ordering for min_quality satisfaction (PRD §3.9).
QUALITY_RANK = {"GRADE_B": 1, "GRADE_A": 2}


def _recompute_contract(contract):
    """Recompute committed_quantity & contract_value from committed lots (PRD §3.9)."""
    committed = sum(
        lot["quantity_committed"]
        for lot in db.harvest_lots.values()
        if lot["committed_contract_id"] == contract["id"]
    )
    contract["committed_quantity"] = committed
    contract["contract_value"] = round2(committed * contract["price_per_unit"])


@bp.post("/sale-contracts")
@require_roles("SalesAgent")
def create_contract():
    body = get_json_body()
    crop = require_enum(body, "crop", CROPS)
    buyer_name = require_str(body, "buyer_name")
    contracted_quantity = require_number(body, "contracted_quantity")
    price_per_unit = require_number(body, "price_per_unit")
    min_quality = "GRADE_B"
    if "min_quality" in body and body.get("min_quality") is not None:
        min_quality = require_enum(body, "min_quality", MIN_QUALITIES)

    if contracted_quantity <= 0:
        raise err("ERR_INVALID_REQUEST", "contracted_quantity must be > 0.")
    if price_per_unit < 0:
        raise err("ERR_INVALID_REQUEST", "price_per_unit must be >= 0.")

    rec = db.new_entity(
        {
            "crop": crop,
            "buyer_name": buyer_name,
            "contracted_quantity": contracted_quantity,
            "min_quality": min_quality,
            "price_per_unit": price_per_unit,
            "committed_quantity": 0,
            "contract_value": round2(0),
            "status": "OPEN",
        }
    )
    db.sale_contracts[rec["id"]] = rec
    return object_response(serializers.sale_contract(rec), 201)


@bp.get("/sale-contracts/<cid>")
@require_roles(*READ_ROLES)
def get_contract(cid):
    rec = lookups.sale_contract(cid)
    return object_response(serializers.sale_contract(rec))


@bp.get("/sale-contracts")
@require_roles(*READ_ROLES)
def list_contracts():
    limit, offset = parse_pagination()
    records = list(db.sale_contracts.values())
    for key in ("crop", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.sale_contract(r) for r in page], limit, offset, total
    )


@bp.get("/sale-contracts/<cid>/harvest-lots")
@require_roles(*READ_ROLES)
def list_contract_lots(cid):
    lookups.sale_contract(cid)
    limit, offset = parse_pagination()
    records = [l for l in db.harvest_lots.values() if l["committed_contract_id"] == cid]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.harvest_lot(r) for r in page], limit, offset, total
    )


@bp.post("/sale-contracts/<cid>/commit-lot")
@require_roles("SalesAgent")
def commit_lot(cid):
    contract = lookups.sale_contract(cid)
    body = get_json_body()
    harvest_lot_id = require_str(body, "harvest_lot_id")
    commit_quantity = require_number(body, "commit_quantity")

    lot = lookups.harvest_lot(harvest_lot_id)

    if commit_quantity <= 0:
        raise err("ERR_INVALID_REQUEST", "commit_quantity must be > 0.")

    # State: contract must be in a state from which commit is defined (PRD §2.10).
    if contract["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        raise err("ERR_INVALID_STATE", "Contract is not OPEN or PARTIALLY_FILLED.")

    # --- Eligibility precedence (PRD §3.9, §2.10) ---
    # Quality: lot must be GRADE_A/GRADE_B and >= contract.min_quality.
    lot_q = lot["quality_status"]
    if lot_q not in ("GRADE_A", "GRADE_B"):
        raise err("ERR_LOT_QUALITY_INSUFFICIENT", "Lot quality is insufficient.")
    if QUALITY_RANK[lot_q] < QUALITY_RANK[contract["min_quality"]]:
        raise err("ERR_LOT_QUALITY_INSUFFICIENT", "Lot quality below contract min_quality.")

    # Crop match: plan behind the lot must match the contract crop.
    plan = db.crop_plans.get(lot["crop_plan_id"])
    if plan is None or plan["crop"] != contract["crop"]:
        raise err("ERR_CROP_MISMATCH", "Lot crop does not match contract crop.")

    # Already-committed-elsewhere / continuation-target check.
    if lot["committed_contract_id"] is not None and lot["committed_contract_id"] != cid:
        raise err(
            "ERR_LOT_ALREADY_COMMITTED",
            "Lot is already committed to a different contract.",
        )

    # Overcommit: must not push committed_quantity beyond contracted_quantity.
    if contract["committed_quantity"] + commit_quantity > contract["contracted_quantity"]:
        raise err("ERR_CONTRACT_OVERCOMMIT", "Commit would exceed contracted_quantity.")

    # Inventory: lot must have uncommitted quantity available.
    uncommitted = lot["quantity"] - lot["quantity_committed"]
    if commit_quantity > uncommitted:
        raise err("ERR_INSUFFICIENT_INVENTORY", "Lot has insufficient uncommitted quantity.")

    # --- Apply commit ---
    lot["quantity_committed"] += commit_quantity
    lot["committed_contract_id"] = cid
    if lot["quantity_committed"] >= lot["quantity"]:
        lot["sale_status"] = "FULLY_COMMITTED"
    else:
        lot["sale_status"] = "PARTIALLY_COMMITTED"
    db.touch(lot)

    _recompute_contract(contract)
    if contract["committed_quantity"] >= contract["contracted_quantity"]:
        contract["status"] = "FILLED"
    else:
        contract["status"] = "PARTIALLY_FILLED"
    db.touch(contract)

    return object_response(serializers.sale_contract(contract))


@bp.post("/sale-contracts/<cid>/ship")
@require_roles("SalesAgent")
def ship_contract(cid):
    contract = lookups.sale_contract(cid)
    if contract["status"] != "FILLED":
        raise err("ERR_CONTRACT_NOT_FILLED", "Contract is not FILLED.")

    contract["status"] = "SHIPPED"
    db.touch(contract)

    # Cascade: every lot committed to this contract -> SHIPPED (PRD §3.9).
    for lot in db.harvest_lots.values():
        if lot["committed_contract_id"] == cid:
            lot["sale_status"] = "SHIPPED"
            db.touch(lot)

    return object_response(serializers.sale_contract(contract))


@bp.post("/sale-contracts/<cid>/cancel")
@require_roles("SalesAgent")
def cancel_contract(cid):
    contract = lookups.sale_contract(cid)
    if contract["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        raise err("ERR_INVALID_STATE", "Contract is not OPEN or PARTIALLY_FILLED.")

    was_partial = contract["status"] == "PARTIALLY_FILLED"
    contract["status"] = "CANCELLED"

    if was_partial:
        # Release every committed lot (compensation, PRD §3.9).
        for lot in db.harvest_lots.values():
            if lot["committed_contract_id"] == cid:
                lot["quantity_committed"] = 0
                lot["committed_contract_id"] = None
                lot["sale_status"] = "IN_INVENTORY"
                db.touch(lot)
        _recompute_contract(contract)

    db.touch(contract)
    return object_response(serializers.sale_contract(contract))
