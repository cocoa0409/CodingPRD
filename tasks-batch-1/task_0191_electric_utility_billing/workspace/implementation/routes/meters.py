"""Meter endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db, base_record
from errors import err
from middleware import authenticate, require_roles, require_owner
from response import success
from services import serializers as ser
from services.common import (
    check_enum,
    get_json_body,
    paginate,
    parse_pagination,
    require_fields,
    require_str,
)

bp = Blueprint("meters", __name__)

READ_ROLES = {"BillingOperator", "Customer", "FieldDispatcher"}
METER_TYPES = {"CONSUMPTION_ONLY", "BIDIRECTIONAL"}


@bp.route("/meters", methods=["POST"])
def create_meter():
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    body = get_json_body()
    require_fields(body, ["account_id", "serial"])
    account_id = body["account_id"]
    serial = require_str(body, "serial")
    meter_type = body.get("meter_type", "BIDIRECTIONAL")
    if meter_type is None:
        meter_type = "BIDIRECTIONAL"
    check_enum(meter_type, METER_TYPES, "meter_type")

    if db.accounts.get(account_id) is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced account does not exist.")

    for m in db.meters.values():
        if m["serial"] == serial:
            raise err("ERR_INVALID_REQUEST", "Meter serial must be unique.")

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "serial": serial,
        "meter_type": meter_type,
        "status": "ACTIVE",
    })
    db.meters[rec["id"]] = rec
    return success(ser.meter(rec), status=201)


@bp.route("/meters/<meter_id>", methods=["GET"])
def get_meter(meter_id):
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.meters.get(meter_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Meter not found.")
    require_owner(role, user_id, rec["account_id"])
    return success(ser.meter(rec), status=200)


@bp.route("/meters", methods=["GET"])
def list_meters():
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(db.meters.values())
    if role == "Customer":
        items = [m for m in items if m["account_id"] == user_id]
    if account_id is not None:
        items = [m for m in items if m["account_id"] == account_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, pagination = paginate(items)
    return success([ser.meter(m) for m in page], status=200, pagination=pagination)
