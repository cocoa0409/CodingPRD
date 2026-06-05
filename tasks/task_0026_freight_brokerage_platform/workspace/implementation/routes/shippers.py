"""Shipper endpoints (PRD §3.1, §3.9)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_UNAUTHORIZED
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_string,
    require_int_or_str_int,
    lookup_path_or_404,
)
from services.calculations import compute_credit_risk


bp = Blueprint("shippers", __name__)


@bp.post("/freight/shippers")
def create_shipper():
    require_auth(["BrokerOps"])()
    body = get_json_body()
    require_fields(body, ["legal_name", "billing_email", "credit_limit_cents"])
    require_string(body["legal_name"], "legal_name")
    require_string(body["billing_email"], "billing_email")
    credit_limit = require_int_or_str_int(body["credit_limit_cents"], "credit_limit_cents")
    if credit_limit < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "credit_limit_cents must be >= 0")

    shipper = {
        "legal_name": body["legal_name"],
        "billing_email": body["billing_email"],
        "credit_limit_cents": credit_limit,
        "open_ar_cents": 0,
        "status": "ACTIVE",
    }
    db.stamp_common(shipper)
    db.shippers[shipper["id"]] = shipper
    return ok_object(shipper, 201)


@bp.get("/freight/shippers/<sid>")
def get_shipper(sid: str):
    require_auth(["BrokerOps", "Shipper"])()
    shipper = lookup_path_or_404(db.shippers, sid, "Shipper")
    if current_role() == "Shipper" and current_user_id() != sid:
        raise APIError(ERR_UNAUTHORIZED, 403, "Shipper may only view own record")
    return ok_object(shipper, 200)


@bp.get("/freight/shippers")
def list_shippers():
    require_auth(["BrokerOps"])()
    limit, offset = paginate_params(request.args)
    status = request.args.get("status")
    items = list(db.shippers.values())
    if status:
        items = [s for s in items if s.get("status") == status]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/freight/shippers/<sid>/credit-risk")
def shipper_credit_risk(sid: str):
    require_auth(["BrokerOps"])()
    lookup_path_or_404(db.shippers, sid, "Shipper")
    payload = compute_credit_risk(sid)
    return ok_object(payload, 200)
