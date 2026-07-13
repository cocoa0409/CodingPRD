from flask import Blueprint, g, request

import errors
from auth import require
from common import (
    get_body,
    lookup,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
)
from constants import FEE_TYPES
from envelope import array_response, object_response
from services import logic
from services.logic import effective_fee_status, serialize_fee
from store import base_fields, db, touch

bp = Blueprint("fees", __name__)


@bp.route("/fee-invoices", methods=["POST"])
@require("Registrar")
def create_fee():
    body = get_body()
    device_id = require_string(body, "device_id")
    ftype = require_enum(body, "type", FEE_TYPES)
    due_period = require_int(body, "due_period")
    device = lookup(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")

    fee = base_fields()
    fee.update({
        "device_id": device_id,
        "type": ftype,
        "amount_cents": logic.compute_fee_provisional_amount(ftype, device["category"]),
        "due_period": due_period,
        "paid_period": None,
        "status": "PENDING",
    })
    db.fee_invoices[fee["id"]] = fee
    return object_response(serialize_fee(fee), 201)


@bp.route("/fee-invoices/<fee_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "BuildingOwner")
def get_fee(fee_id):
    f = lookup(db.fee_invoices, fee_id, "ERR_FEE_INVOICE_NOT_FOUND")
    return object_response(serialize_fee(f), 200)


@bp.route("/fee-invoices", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "BuildingOwner")
def list_fees():
    limit, offset = parse_pagination()
    device_id = request.args.get("device_id")
    status = request.args.get("status")
    ftype = request.args.get("type")
    items = list(db.fee_invoices.values())
    if device_id is not None:
        items = [f for f in items if f["device_id"] == device_id]
    if status is not None:
        items = [f for f in items if effective_fee_status(f) == status]
    if ftype is not None:
        items = [f for f in items if f["type"] == ftype]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_fee(f) for f in page], limit, offset, total)


@bp.route("/fee-invoices/<fee_id>/pay", methods=["POST"])
@require("BuildingOwner")
def pay_fee(fee_id):
    f = lookup(db.fee_invoices, fee_id, "ERR_FEE_INVOICE_NOT_FOUND")
    device = db.devices[f["device_id"]]
    if device["owner_id"] != g.user_id:
        raise errors.not_resource_owner()
    if effective_fee_status(f) not in ("PENDING", "OVERDUE"):
        raise errors.ApiError("ERR_INVOICE_NOT_PAYABLE", 409,
                              "Invoice is not payable.")
    paid_period = db.current_period_index
    f["amount_cents"] = logic.compute_fee_final_amount(
        f["type"], device["category"], f["due_period"], paid_period
    )
    f["paid_period"] = paid_period
    f["status"] = "PAID"
    touch(f)
    return object_response(serialize_fee(f), 200)
