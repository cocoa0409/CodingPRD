"""RINLot and BlendingRecord endpoints."""
from flask import Blueprint, request

import db
from errors import (
    invalid_request, not_found, reference_not_found, invalid_state,
    rin_invalidated, invalid_vintage, separation_exceeds_attached,
)
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import lot_view, blending_record_view
from services import calculations

bp = Blueprint("lots", __name__)

_D_CODES = ("D3", "D4", "D5", "D6")


def _get_lot(lot_id):
    lot = db.rin_lots.get(lot_id)
    if lot is None:
        raise not_found("RIN lot not found")
    return lot


@bp.route("/rfs/rin-lots", methods=["POST"])
def create_lot():
    require_roles("ComplianceManager")
    body = json_body()

    account_id = body.get("account_id")
    d_code = body.get("d_code")
    vintage_year = body.get("vintage_year")
    gallon_qty = body.get("gallon_qty")
    equivalence_value = body.get("equivalence_value", 1.0)

    # --- Request shape (priority 5) ---
    if account_id is None:
        raise invalid_request("account_id is required")
    if d_code not in _D_CODES:
        raise invalid_request("d_code must be one of D3, D4, D5, D6")
    if not isinstance(vintage_year, int) or isinstance(vintage_year, bool):
        raise invalid_request("vintage_year must be an integer")
    if not isinstance(gallon_qty, int) or isinstance(gallon_qty, bool) or gallon_qty <= 0:
        raise invalid_request("gallon_qty must be a positive integer")
    if not isinstance(equivalence_value, (int, float)) or isinstance(equivalence_value, bool) or equivalence_value <= 0:
        raise invalid_request("equivalence_value must be a positive number")

    # --- Referential integrity (priority 6) ---
    if db.compliance_accounts.get(account_id) is None:
        raise reference_not_found("Referenced account does not exist")

    # --- Temporal gate (priority 11): vintage within {clock year - 1, clock year} ---
    clock_year = db.now_utc().year
    if vintage_year not in (clock_year - 1, clock_year):
        raise invalid_vintage("vintage_year must be the current clock year or the year before")

    # --- rin_generation_qty calculation ---
    rin_qty = calculations.compute_rin_qty(gallon_qty, equivalence_value)

    now = db.now_utc()
    lot = {
        "id": db.new_id(),
        "account_id": account_id,
        "origin": "GENERATED",
        "vendor_id": None,
        "trade_id": None,
        "d_code": d_code,
        "vintage_year": vintage_year,
        "gallon_qty": gallon_qty,
        "equivalence_value": equivalence_value,
        "rin_qty": rin_qty,
        "attached_qty": rin_qty,
        "separated_qty": 0,
        "pending_retired_qty": 0,
        "retired_qty": 0,
        "invalidated_qty": 0,
        "expired_qty": 0,
        "available_qty": rin_qty,
        "unit_cost_cents": 0,
        "status": "ACTIVE",
        "retention_until": db.retention_until_from(now),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.rin_lots[lot["id"]] = lot
    return ok_object(lot_view(lot), status=201)


@bp.route("/rfs/rin-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    return ok_object(lot_view(_get_lot(lot_id)))


@bp.route("/rfs/rin-lots", methods=["GET"])
def list_lots():
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    vendor_id = request.args.get("vendor_id")
    trade_id = request.args.get("trade_id")
    rows = list(db.rin_lots.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if vendor_id is not None:
        rows = [r for r in rows if r.get("vendor_id") == vendor_id]
    if trade_id is not None:
        rows = [r for r in rows if r.get("trade_id") == trade_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([lot_view(r) for r in page], limit, offset, total)


@bp.route("/rfs/rin-lots/<lot_id>/separations", methods=["POST"])
def create_separation(lot_id):
    require_roles("ComplianceManager")
    lot = _get_lot(lot_id)
    body = json_body()
    blended_gallons = body.get("blended_gallons")
    if not isinstance(blended_gallons, int) or isinstance(blended_gallons, bool) or blended_gallons <= 0:
        raise invalid_request("blended_gallons must be a positive integer")

    # Regulatory gate: INVALIDATED lot refuses separation
    if lot["status"] == "INVALIDATED":
        raise rin_invalidated("Lot is INVALIDATED")
    # Only GENERATED lots separate (PURCHASED lots arrive already separated);
    # an EXPIRED/EXHAUSTED lot is no longer eligible for separation.
    if lot["status"] != "ACTIVE":
        raise invalid_state("Lot is not ACTIVE")

    # Quantity gate: blended gallons must not exceed attached_qty (exactly equal succeeds)
    if blended_gallons > lot["attached_qty"]:
        raise separation_exceeds_attached("blended_gallons exceeds the lot's attached_qty")

    now = db.now_utc()
    lot["attached_qty"] -= blended_gallons
    lot["separated_qty"] += blended_gallons
    calculations.sync_available(lot)  # unchanged: attached->separated both reduce equally
    lot["version"] += 1
    lot["updated_at"] = now

    record = {
        "id": db.new_id(),
        "account_id": lot["account_id"],
        "rin_lot_id": lot["id"],
        "blended_gallons": blended_gallons,
        "blended_at": now,
        "retention_until": db.retention_until_from(now),
        "created_at": now,
    }
    db.blending_records[record["id"]] = record
    return ok_object(blending_record_view(record), status=201)


@bp.route("/rfs/blending-records/<record_id>", methods=["GET"])
def get_blending_record(record_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    record = db.blending_records.get(record_id)
    if record is None:
        raise not_found("Blending record not found")
    return ok_object(blending_record_view(record))


@bp.route("/rfs/blending-records", methods=["GET"])
def list_blending_records():
    require_roles("OpsAdmin", "ComplianceManager", "Trader")
    limit, offset = parse_pagination(request.args)
    account_id = request.args.get("account_id")
    rin_lot_id = request.args.get("rin_lot_id")
    rows = list(db.blending_records.values())
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if rin_lot_id is not None:
        rows = [r for r in rows if r["rin_lot_id"] == rin_lot_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([blending_record_view(r) for r in page], limit, offset, total)
