"""Customer endpoints + the test-driving logical clock endpoint."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INSUFFICIENT_PERMISSIONS,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import paginate, resolve_customer, serialize
from services.validate import json_body, parse_iso, req_int, req_str

bp = Blueprint("customers", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock(_user_id=None, _role=None):
    body = json_body(required=True)
    dt = parse_iso(body.get("to_iso8601"))
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 UTC timestamp")
    db.set_current_utc(dt)
    return success_object({}, 200)


@bp.route("/customers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_customer(_user_id=None, _role=None):
    body = json_body(required=True)
    legal_name = req_str(body, "legal_name")
    contact_email = req_str(body, "contact_email")
    credit_limit = req_int(body, "credit_limit_cents", min_value=0)
    customer = db.stamp_new({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "credit_limit_cents": credit_limit,
        "outstanding_exposure_cents": 0,
        "status": "ACTIVE",
    })
    db.customers[customer["id"]] = customer
    return success_object(serialize(customer), 201)


@bp.route("/customers", methods=["GET"])
@require_roles("PlatformAdmin", "ProjectManager", "SalesRep")
def list_customers(_user_id=None, _role=None):
    status = request.args.get("status")
    records = list(db.customers.values())
    if status is not None:
        records = [c for c in records if c["status"] == status]
    return paginate(records)


@bp.route("/customers/<customerId>", methods=["GET"])
@require_roles("PlatformAdmin", "ProjectManager", "SalesRep", "Customer")
def get_customer(customerId, _user_id=None, _role=None):
    customer = resolve_customer(customerId)
    if _role == "Customer" and _user_id != customer["id"]:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
            "Customer may access only its own record",
        )
    return success_object(serialize(customer), 200)


@bp.route("/customers/<customerId>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_customer(customerId, _user_id=None, _role=None):
    customer = resolve_customer(customerId)
    customer["status"] = "SUSPENDED"
    db.touch(customer)
    return success_object(serialize(customer), 200)
