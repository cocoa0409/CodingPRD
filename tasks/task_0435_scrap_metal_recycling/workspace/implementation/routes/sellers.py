"""Seller routes (PRD §3.1)."""
from flask import Blueprint

import errors
import response
import serializers
from db import db, stamp_create, touch
from helpers import (as_enum, as_string, get_json_body, parse_pagination,
                     paginate, query_arg, require_fields)
from middleware import authenticate, require_roles

bp = Blueprint("sellers", __name__)

ID_TYPES = {"DRIVERS_LICENSE", "STATE_ID", "PASSPORT"}
SELLER_STATUSES = {"ACTIVE", "FLAGGED", "BANNED"}


@bp.route("/yard/sellers", methods=["POST"])
def create_seller():
    _uid, role = authenticate()
    require_roles(role, {"WeighMaster", "ComplianceOfficer"})
    body = get_json_body()
    require_fields(body, ["legal_name", "id_type", "id_number"])
    legal_name = as_string(body["legal_name"], "legal_name")
    id_type = as_enum(body["id_type"], "id_type", ID_TYPES)
    id_number = as_string(body["id_number"], "id_number")
    tin = body.get("tin")
    if tin is not None and not isinstance(tin, str):
        raise errors.invalid_request("tin must be a string or null.")

    record = {
        "legal_name": legal_name,
        "id_type": id_type,
        "id_number": id_number,
        "tin": tin,
        "status": "ACTIVE",
        "ytd_cash_paid_cents": 0,
        "requires_1099": False,
        "open_theft_reports": 0,
    }
    stamp_create(record)
    db.sellers[record["id"]] = record
    return response.success(serializers.seller(record), 201)


@bp.route("/yard/sellers/<sid>", methods=["GET"])
def get_seller(sid):
    authenticate()
    record = db.sellers.get(sid)
    if not record:
        raise errors.not_found("Seller not found.")
    return response.success(serializers.seller(record), 200)


@bp.route("/yard/sellers", methods=["GET"])
def list_sellers():
    authenticate()
    limit, offset = parse_pagination()
    status = query_arg("status")
    if status is not None and status not in SELLER_STATUSES:
        raise errors.invalid_request("status filter is invalid.")
    rows = list(db.sellers.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.seller(r) for r in page], limit, offset, total)


@bp.route("/yard/sellers/<sid>", methods=["PATCH"])
def patch_seller(sid):
    _uid, role = authenticate()
    require_roles(role, {"WeighMaster", "ComplianceOfficer"})
    record = db.sellers.get(sid)
    if not record:
        raise errors.not_found("Seller not found.")
    body = get_json_body()
    require_fields(body, ["tin"])
    tin = body["tin"]
    if tin is not None and not isinstance(tin, str):
        raise errors.invalid_request("tin must be a string or null.")
    record["tin"] = tin
    touch(record)
    return response.success(serializers.seller(record), 200)


@bp.route("/yard/sellers/<sid>/ban", methods=["POST"])
def ban_seller(sid):
    _uid, role = authenticate()
    require_roles(role, {"ComplianceOfficer"})
    record = db.sellers.get(sid)
    if not record:
        raise errors.not_found("Seller not found.")
    record["status"] = "BANNED"
    touch(record)
    return response.success(serializers.seller(record), 200)
