"""Shipper CRUD + suspension."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_SHIPPER_NOT_FOUND,
)
from ..helpers import (
    check_version,
    ensure_shipper_self_access,
    get_body,
    get_brokerage_or_404,
    get_scoped,
    optional_field,
    paginate,
    parse_pagination,
    require_field,
)
from ..store import store


shippers_bp = Blueprint("shippers", __name__, url_prefix="/brokerages")


@shippers_bp.post("/<brokerage_id>/shippers")
@require_auth(["BrokerOps"])
def create_shipper(brokerage_id):
    body = get_body()
    company_name = require_field(body, "company_name", str)
    smartway_required = optional_field(body, "smartway_required", bool, default=False)
    if "credit_limit_cents" not in body or body["credit_limit_cents"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: credit_limit_cents")
    credit_limit = body["credit_limit_cents"]
    if isinstance(credit_limit, bool) or not isinstance(credit_limit, int) or credit_limit < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "credit_limit_cents must be a non-negative integer.")

    with store.lock:
        get_brokerage_or_404(brokerage_id)
        s = {
            "brokerage_id": brokerage_id,
            "company_name": company_name,
            "smartway_required": bool(smartway_required),
            "credit_limit_cents": int(credit_limit),
            "outstanding_invoiced_cents": 0,
            "status": "ACTIVE",
        }
        store.stamp_create(s)
        store.shippers[s["id"]] = s
    return ok_object(s, status=201)


@shippers_bp.get("/<brokerage_id>/shippers")
@require_auth(["BrokerOps", "PlatformAdmin"])
def list_shippers(brokerage_id):
    limit, offset = parse_pagination()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        rows = [s for s in store.shippers.values() if s.get("brokerage_id") == brokerage_id]
        page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset, total_count=total, has_more=has_more)


@shippers_bp.get("/<brokerage_id>/shippers/<shipper_id>")
@require_auth(["BrokerOps", "ShipperUser", "PlatformAdmin"])
def get_shipper(brokerage_id, shipper_id):
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        s = get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        ensure_shipper_self_access(shipper_id)
    return ok_object(s)


@shippers_bp.post("/<brokerage_id>/shippers/<shipper_id>/suspend")
@require_auth(["BrokerOps"])
def suspend_shipper(brokerage_id, shipper_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        s = get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)
        check_version(s, body)
        # Idempotent in spirit but PRD doesn't define an error; simply set.
        s["status"] = "SUSPENDED"
        store.bump(s)
    return ok_object(s)
