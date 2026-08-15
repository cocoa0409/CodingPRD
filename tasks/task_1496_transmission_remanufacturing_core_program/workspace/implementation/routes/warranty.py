"""WarrantyClaim endpoints including the parallel return-leg dimension."""

import uuid
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_ORDER_NOT_FOUND, ERR_CLAIM_NOT_FOUND, ERR_PART_NOT_FOUND,
    ERR_ORDER_NOT_SHIPPED, ERR_CLAIM_NOT_REVIEWABLE, ERR_CLAIM_NOT_PAYABLE,
    ERR_RETURN_NOT_SHIPPABLE, ERR_RETURN_NOT_RECEIVABLE,
    ERR_RETURN_NOT_RECEIVED, ERR_WARRANTY_WINDOW_EXPIRED,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import require_role
from response import success
from services.allocation import promotion_scan
from services.calculations import compute_labor_allowance, compute_routing
from services.serializers import claim_view
from validators import (
    get_json_body, require_fields, check_string, check_int, check_number,
    check_positive, check_enum, invalid, parse_limit_offset, paginate,
)

bp = Blueprint("warranty", __name__)

FAILURE_CODES = {
    "CONVERTER_FAILURE", "GEAR_CLUNK", "PRESSURE_LEAK", "ELECTRICAL_TCM",
}
ALLOWANCE_POLICIES = {"BOOK_HOURS", "ACTUAL_HOURS"}


def _get_claim(cid):
    c = db.warranty_claims.get(cid)
    if c is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND, "WarrantyClaim id does not exist", 404)
    return c


@bp.post("/api/warranty-claims")
def create_claim():
    user_id, _ = require_role({"Installer"})
    body = get_json_body()
    require_fields(
        body,
        [
            "reman_order_id", "failure_code", "claimed_labor_hours",
            "installer_labor_rate_cents", "allowance_policy",
        ],
    )
    check_string(body["reman_order_id"], "reman_order_id")
    check_enum(body["failure_code"], "failure_code", FAILURE_CODES)
    check_number(body["claimed_labor_hours"], "claimed_labor_hours")
    check_positive(body["claimed_labor_hours"], "claimed_labor_hours")
    check_int(body["installer_labor_rate_cents"], "installer_labor_rate_cents")
    check_positive(body["installer_labor_rate_cents"], "installer_labor_rate_cents")
    check_enum(body["allowance_policy"], "allowance_policy", ALLOWANCE_POLICIES)

    order = db.reman_orders.get(body["reman_order_id"])
    if order is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, "RemanOrder id does not exist", 404)
    if order["status"] != "SHIPPED":
        raise ApiError(
            ERR_ORDER_NOT_SHIPPED, "warranty claim requires order status SHIPPED", 409
        )
    # Warranty window: filed <= warranty_days after shipped_at.
    deadline = order["shipped_at"] + timedelta(days=order["pinned_spec"]["warranty_days"])
    if db.now() > deadline:
        raise ApiError(
            ERR_WARRANTY_WINDOW_EXPIRED,
            "claim filed after shipped_at + warranty_days",
            422,
        )

    now = db.now()
    claim = {
        "id": str(uuid.uuid4()),
        "reman_order_id": order["id"],
        "installer_id": user_id,
        "failure_code": body["failure_code"],
        "claimed_labor_hours": body["claimed_labor_hours"],
        "installer_labor_rate_cents": body["installer_labor_rate_cents"],
        "allowance_policy": body["allowance_policy"],
        "labor_allowance_cents": None,
        "routing_type": None,
        "return_required": None,
        "claim_status": "SUBMITTED",
        "return_status": "NONE",
        "deny_reason": None,
        "salvaged_parts": [],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.warranty_claims[claim["id"]] = claim
    return success(claim_view(claim), "object", 201)


@bp.get("/api/warranty-claims")
def list_claims():
    require_role({"Any"})
    items = list(db.warranty_claims.values())
    oid = request.args.get("reman_order_id")
    status = request.args.get("claim_status")
    if oid is not None:
        items = [c for c in items if c["reman_order_id"] == oid]
    if status is not None:
        items = [c for c in items if c["claim_status"] == status]
    items.sort(key=lambda c: c["created_at"])
    limit, offset = parse_limit_offset(request.args)
    page, pg = paginate(items, limit, offset)
    return success([claim_view(c) for c in page], "array", 200, pg)


@bp.get("/api/warranty-claims/<cid>")
def get_claim(cid):
    require_role({"Any"})
    return success(claim_view(_get_claim(cid)), "object", 200)


@bp.post("/api/warranty-claims/<cid>/approve")
def approve_claim(cid):
    require_role({"WarrantyAdjuster"})
    claim = _get_claim(cid)
    if claim["claim_status"] != "SUBMITTED":
        raise ApiError(
            ERR_CLAIM_NOT_REVIEWABLE, "approve requires claim_status SUBMITTED", 409
        )
    order = db.reman_orders.get(claim["reman_order_id"])
    allowance = compute_labor_allowance(claim, order["pinned_spec"])
    routing, return_required = compute_routing(claim["failure_code"], allowance)
    claim["labor_allowance_cents"] = allowance
    claim["routing_type"] = routing
    claim["return_required"] = return_required
    claim["claim_status"] = "APPROVED"
    if return_required:
        claim["return_status"] = "ISSUED"
    claim["updated_at"] = db.now()
    claim["version"] += 1
    return success(claim_view(claim), "object", 200)


@bp.post("/api/warranty-claims/<cid>/deny")
def deny_claim(cid):
    require_role({"WarrantyAdjuster"})
    body = get_json_body()
    reason = body.get("reason")
    if reason is not None:
        check_string(reason, "reason")
    claim = _get_claim(cid)
    if claim["claim_status"] != "SUBMITTED":
        raise ApiError(
            ERR_CLAIM_NOT_REVIEWABLE, "deny requires claim_status SUBMITTED", 409
        )
    claim["claim_status"] = "DENIED"
    claim["deny_reason"] = reason
    claim["updated_at"] = db.now()
    claim["version"] += 1
    return success(claim_view(claim), "object", 200)


@bp.post("/api/warranty-claims/<cid>/pay")
def pay_claim(cid):
    require_role({"WarrantyAdjuster"})
    claim = _get_claim(cid)
    if claim["claim_status"] != "APPROVED":
        raise ApiError(
            ERR_CLAIM_NOT_PAYABLE, "pay requires claim_status APPROVED", 409
        )
    if claim["return_required"] and claim["return_status"] != "DISPOSITIONED":
        raise ApiError(
            ERR_RETURN_NOT_RECEIVED,
            "pay on a return-required claim requires return_status DISPOSITIONED",
            409,
        )
    claim["claim_status"] = "PAID"
    claim["updated_at"] = db.now()
    claim["version"] += 1
    return success(claim_view(claim), "object", 200)


@bp.post("/api/warranty-claims/<cid>/return-ship")
def return_ship(cid):
    user_id, _ = require_role({"Installer"})
    claim = _get_claim(cid)
    if not (claim["claim_status"] == "APPROVED" and claim["return_status"] == "ISSUED"):
        raise ApiError(
            ERR_RETURN_NOT_SHIPPABLE,
            "return-ship requires claim APPROVED with return_status ISSUED",
            409,
        )
    # Ownership: only the filing installer may ship the return.
    if user_id != claim["installer_id"]:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "return-ship restricted to the claim's installer_id",
            403,
        )
    claim["return_status"] = "IN_TRANSIT"
    claim["updated_at"] = db.now()
    claim["version"] += 1
    return success(claim_view(claim), "object", 200)


@bp.post("/api/warranty-claims/<cid>/return-receive")
def return_receive(cid):
    require_role({"WarrantyAdjuster"})
    body = get_json_body()
    salvaged = body.get("salvaged_parts", [])
    if not isinstance(salvaged, list):
        invalid("Field salvaged_parts must be an array")
    for line in salvaged:
        if not isinstance(line, dict):
            invalid("salvaged_parts entries must be objects")
        if "hard_part_id" not in line or "qty" not in line:
            invalid("salvaged_parts entries require hard_part_id and qty")
        check_string(line["hard_part_id"], "salvaged_parts.hard_part_id")
        check_int(line["qty"], "salvaged_parts.qty")
        check_positive(line["qty"], "salvaged_parts.qty")

    claim = _get_claim(cid)
    # FK existence for salvaged parts (priority 4) before state gate (6).
    for line in salvaged:
        if line["hard_part_id"] not in db.hard_parts:
            raise ApiError(ERR_PART_NOT_FOUND, "HardPart id does not exist", 404)
    if claim["return_status"] != "IN_TRANSIT":
        raise ApiError(
            ERR_RETURN_NOT_RECEIVABLE,
            "return-receive requires return_status IN_TRANSIT",
            409,
        )
    now = db.now()
    claim["return_status"] = "DISPOSITIONED"
    claim["salvaged_parts"] = [
        {"hard_part_id": line["hard_part_id"], "qty": line["qty"]} for line in salvaged
    ]
    restocked = False
    for line in salvaged:
        part = db.hard_parts[line["hard_part_id"]]
        part["qty_on_hand"] += line["qty"]
        part["updated_at"] = now
        part["version"] += 1
        restocked = True
    claim["updated_at"] = now
    claim["version"] += 1
    if restocked:
        promotion_scan()
    return success(claim_view(claim), "object", 200)
