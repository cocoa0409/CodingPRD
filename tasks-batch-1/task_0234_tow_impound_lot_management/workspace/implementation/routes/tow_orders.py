"""TowOrder endpoints: intake, lifecycle, holds, ledger, payments."""
from flask import Blueprint, request

import db
from clock import iso, now
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services import calc
from services import orders as order_svc
from services.serialize import public
from validators import (optional_int, paginate_and_respond, require_enum,
                        require_int, require_str, sort_by_created)

bp = Blueprint("tow_orders", __name__)

TOW_TYPES = {"POLICE", "PRIVATE", "ABANDONED"}
HOLD_TYPES = {"POLICE_HOLD", "EVIDENCE_HOLD"}


def get_order_or_404(order_id):
    o = db.tow_orders.get(order_id)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", "Tow order not found")
    return o


def serialize_order(order):
    """Recompute computed fields for non-terminal-with-frozen orders then strip
    private fields. For active accrual (open segment) recompute reflects current
    clock; for frozen/terminal orders the stored computed values are final."""
    if order["status"] not in ("RELEASED", "AUCTIONED", "VOIDED"):
        order_svc.recompute(order)
    return public(order)


@bp.route("/tow-orders", methods=["POST"])
def create_order():
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "PoliceOfficer"})
    body = get_json_body()
    provider_id = body.get("provider_id")
    rotation_assignment_id = body.get("rotation_assignment_id")
    lienholder_id = body.get("lienholder_id")

    # existence (priority 3) before body well-formedness (priority 4). A
    # referenced id must be present to be resolvable; a present-but-unknown id is
    # ERR_NOT_FOUND ahead of any enum/type body error.
    if body.get("lot_id") is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: lot_id")
    lot = db.impound_lots.get(body.get("lot_id"))
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", "Impound lot not found")
    if provider_id is not None and provider_id not in db.tow_providers:
        raise ApiError("ERR_NOT_FOUND", "Tow provider not found")
    if rotation_assignment_id is not None and rotation_assignment_id not in db.rotation_assignments:
        raise ApiError("ERR_NOT_FOUND", "Rotation assignment not found")
    if lienholder_id is not None and lienholder_id not in db.lienholders:
        raise ApiError("ERR_NOT_FOUND", "Lienholder not found")

    # body well-formedness (priority 4)
    lot_id = require_str(body, "lot_id")
    tow_type = require_enum(body, "tow_type", TOW_TYPES)
    vin = require_str(body, "vin")
    plate = require_str(body, "plate")
    owner_name = require_str(body, "owner_name")
    owner_address = require_str(body, "owner_address")

    # referential consistency (priority 5) ERR_REFERENCE_MISMATCH
    if rotation_assignment_id is not None:
        ra = db.rotation_assignments[rotation_assignment_id]
        if provider_id is not None and ra["provider_id"] != provider_id:
            raise ApiError("ERR_REFERENCE_MISMATCH",
                           "rotation_assignment provider_id does not match provider_id")
        if ra["lot_id"] != lot_id:
            raise ApiError("ERR_REFERENCE_MISMATCH",
                           "rotation_assignment lot_id does not match lot_id")

    # lot must be OPEN (priority 13)
    if lot["status"] != "OPEN":
        raise ApiError("ERR_LOT_SUSPENDED", "Lot is SUSPENDED; no new intake")

    intake_dt = now()
    order = {
        "lot_id": lot_id,
        "provider_id": provider_id,
        "rotation_assignment_id": rotation_assignment_id,
        "lienholder_id": lienholder_id,
        "auction_id": None,
        "tow_type": tow_type,
        "vin": vin,
        "plate": plate,
        "owner_name": owner_name,
        "owner_address": owner_address,
        "intake_at": iso(intake_dt),
        "stored_at": None,
        "accrual_frozen_at": None,
        "accrued_days": 0,
        "estimated_storage_cents": calc.estimated_storage(lot),
        "accrued_storage_cents": 0,
        "balance_due_cents": 0,
        "waiver_credit_cents": 0,
        "net_due_cents": 0,
        "amount_paid_cents": 0,
        "hold_status": "NONE",
        "status": "TOWED",
        "_intake_dt": intake_dt,
        "_accrual_frozen_dt": None,
    }
    db.stamp_create(order)
    db.tow_orders[order["id"]] = order
    order_svc.recompute(order)
    return object_response(public(order), 201)


@bp.route("/tow-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "PoliceOfficer", "Claimant", "AuctionOfficial"})
    o = get_order_or_404(order_id)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders", methods=["GET"])
def list_orders():
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "PoliceOfficer", "AuctionOfficial", "Claimant"})
    items = list(db.tow_orders.values())
    for key in ("lot_id", "provider_id", "lienholder_id", "rotation_assignment_id", "auction_id"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sort_by_created(items)
    return paginate_and_respond([serialize_order(o) for o in items])


@bp.route("/tow-orders/<order_id>/store", methods=["POST"])
def store(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    o = get_order_or_404(order_id)
    if o["status"] != "TOWED":
        raise ApiError("ERR_INVALID_STATE", "Order is not TOWED")
    has_inventory = any(i["tow_order_id"] == order_id for i in db.inventory_items.values())
    if not has_inventory:
        raise ApiError("ERR_INVENTORY_REQUIRED", "At least one inventory item required")
    lot = order_svc.lot_of(o)
    stored_dt = now()
    o["stored_at"] = iso(stored_dt)
    o["status"] = "STORED"
    order_svc.open_accrual(o, lot, "ACCRUAL", stored_dt)
    order_svc.recompute(o)
    db.touch(o)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders/<order_id>/authorize-release", methods=["POST"])
def authorize_release(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    o = get_order_or_404(order_id)
    if o["status"] != "STORED":
        raise ApiError("ERR_INVALID_STATE", "Order is not STORED")
    if o["hold_status"] != "NONE":
        raise ApiError("ERR_HOLD_ACTIVE", "An active hold blocks authorization")
    pending = any(w["tow_order_id"] == order_id and w["status"] in ("REQUESTED", "UNDER_REVIEW")
                  for w in db.fee_waivers.values())
    if pending:
        raise ApiError("ERR_WAIVER_PENDING", "A pending fee waiver blocks authorization")
    order_svc.recompute(o)
    if o["amount_paid_cents"] < o["net_due_cents"]:
        raise ApiError("ERR_BALANCE_UNPAID", "amount_paid_cents does not cover net_due_cents")
    lot = order_svc.lot_of(o)
    order_svc.freeze_accrual(o, lot, now())
    o["status"] = "RELEASE_AUTHORIZED"
    db.touch(o)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders/<order_id>/lapse-authorization", methods=["POST"])
def lapse_authorization(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    o = get_order_or_404(order_id)
    if o["status"] != "RELEASE_AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", "Order is not RELEASE_AUTHORIZED")
    lot = order_svc.lot_of(o)
    order_svc.resume_accrual(o, lot, now())
    o["status"] = "STORED"
    db.touch(o)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders/<order_id>/mark-auction-eligible", methods=["POST"])
def mark_auction_eligible(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    o = get_order_or_404(order_id)
    if o["status"] != "STORED":
        raise ApiError("ERR_INVALID_STATE", "Order is not STORED")
    if o["hold_status"] != "NONE":
        raise ApiError("ERR_HOLD_ACTIVE", "An active hold blocks marking auction-eligible")
    if not order_svc.statutory_eligible(o):
        raise ApiError("ERR_STATUTORY_PERIOD_NOT_ELAPSED",
                       "Statutory hold or notice grace window has not elapsed")
    lot = order_svc.lot_of(o)
    order_svc.freeze_accrual(o, lot, now())
    o["status"] = "AUCTION_ELIGIBLE"
    db.touch(o)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders/<order_id>/reclaim", methods=["POST"])
def reclaim(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    o = get_order_or_404(order_id)
    if o["status"] != "AUCTION_ELIGIBLE":
        raise ApiError("ERR_INVALID_STATE", "Order is not AUCTION_ELIGIBLE")
    if o.get("auction_id") is not None:
        raise ApiError("ERR_ALREADY_IN_AUCTION", "Order already swept into an auction")
    lot = order_svc.lot_of(o)
    order_svc.resume_accrual(o, lot, now())
    o["status"] = "STORED"
    db.touch(o)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders/<order_id>/void", methods=["POST"])
def void(order_id):
    user_id, role = require_user_context()
    require_role(role, {"PoliceOfficer"})
    o = get_order_or_404(order_id)
    if o["status"] not in ("TOWED", "STORED"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be voided from its current state")
    lot = order_svc.lot_of(o)
    order_svc.zero_accrual(o, lot, now())
    o["status"] = "VOIDED"
    db.touch(o)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders/<order_id>/place-hold", methods=["POST"])
def place_hold(order_id):
    user_id, role = require_user_context()
    require_role(role, {"PoliceOfficer"})
    o = get_order_or_404(order_id)
    body = get_json_body()
    hold = require_enum(body, "hold_status", HOLD_TYPES)
    if o["status"] in ("RELEASED", "AUCTIONED", "VOIDED"):
        raise ApiError("ERR_INVALID_STATE", "Order is in a terminal state")
    if o["hold_status"] != "NONE":
        raise ApiError("ERR_HOLD_ACTIVE", "A hold is already active")
    o["hold_status"] = hold
    db.touch(o)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders/<order_id>/lift-hold", methods=["POST"])
def lift_hold(order_id):
    user_id, role = require_user_context()
    require_role(role, {"PoliceOfficer"})
    o = get_order_or_404(order_id)
    if o["hold_status"] == "NONE":
        raise ApiError("ERR_NO_HOLD", "No active hold to lift")
    o["hold_status"] = "NONE"
    db.touch(o)
    return object_response(serialize_order(o), 200)


@bp.route("/tow-orders/<order_id>/ledger-entries", methods=["GET"])
def list_ledger(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant", "AuctionOfficial"})
    get_order_or_404(order_id)
    kind = request.args.get("kind")
    items = [e for e in db.ledger_entries.values() if e["tow_order_id"] == order_id]
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    return paginate_and_respond([public(e) for e in items])


@bp.route("/tow-orders/<order_id>/payments", methods=["POST"])
def record_payment(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant"})
    o = get_order_or_404(order_id)
    body = get_json_body()
    amount = require_int(body, "amount_cents", minimum=0)
    o["amount_paid_cents"] += amount
    order_svc.recompute(o)
    db.touch(o)
    return object_response(serialize_order(o), 200)
