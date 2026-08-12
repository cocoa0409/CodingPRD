"""Buyer and SalesContract endpoints."""

from decimal import Decimal
from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, r2, to_float, req_body, require_fields, req_string, req_enum, req_int,
    req_number, opt_number, check_contract_month, pagination_params, page_slice,
    get_or_404, touch, parse_date, latest_settlement_tick,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_buyer, ser_contract
from services import (
    recompute_plan_counters, evaluate_over_sold, governing_agreement,
)
from routes.plans import _do_close_plan


bp = Blueprint("buyers_contracts", __name__)


# ---------------------------------------------------------------------------
# Buyer
# ---------------------------------------------------------------------------

@bp.route("/advisory/buyers", methods=["POST"])
def create_buyer():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["name", "buyer_type", "credit_rating"])
    name = req_string(body, "name")
    buyer_type = req_enum(body, "buyer_type", {"ELEVATOR", "PROCESSOR", "EXPORTER", "ETHANOL"})
    credit = req_enum(body, "credit_rating", {"A", "B", "C"})
    bid = db.new_id()
    now = db.now_iso()
    buyer = {
        "id": bid,
        "name": name,
        "buyer_type": buyer_type,
        "credit_rating": credit,
        "status": "PROVISIONAL",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.buyers[bid] = buyer
    return success_object(ser_buyer(buyer), status=201)


@bp.route("/advisory/buyers/<buyerId>", methods=["GET"])
def get_buyer(buyerId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    b = get_or_404(DB.buyers, buyerId, "Buyer")
    return success_object(ser_buyer(b))


@bp.route("/advisory/buyers", methods=["GET"])
def list_buyers():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    limit, offset = pagination_params()
    status = request.args.get("status")
    buyer_type = request.args.get("buyer_type")
    items = list(DB.buyers.values())
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if buyer_type is not None:
        items = [b for b in items if b["buyer_type"] == buyer_type]
    items.sort(key=lambda b: b["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_buyer(b) for b in slice_], limit, offset, total)


@bp.route("/advisory/buyers/<buyerId>/approve", methods=["POST"])
def approve_buyer(buyerId):
    user_id, role = get_auth()
    require_role(role, ["ComplianceOfficer"])
    b = get_or_404(DB.buyers, buyerId, "Buyer")
    if b["status"] not in {"PROVISIONAL", "SUSPENDED"}:
        raise ApiError("ERR_INVALID_STATE", f"Buyer in state {b['status']} cannot be approved", 409)
    b["status"] = "APPROVED"
    touch(b)
    return success_object(ser_buyer(b))


@bp.route("/advisory/buyers/<buyerId>/suspend", methods=["POST"])
def suspend_buyer(buyerId):
    user_id, role = get_auth()
    require_role(role, ["ComplianceOfficer"])
    b = get_or_404(DB.buyers, buyerId, "Buyer")
    if b["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", f"Buyer in state {b['status']} cannot be suspended", 409)
    b["status"] = "SUSPENDED"
    touch(b)
    return success_object(ser_buyer(b))


# ---------------------------------------------------------------------------
# SalesContract
# ---------------------------------------------------------------------------

@bp.route("/advisory/sales-contracts", methods=["POST"])
def create_contract():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    body = req_body()
    require_fields(body, [
        "operation_id", "plan_id", "buyer_id", "contract_type", "bushels",
        "delivery_window_start", "delivery_window_end",
    ])
    operation_id = body["operation_id"]
    plan_id = body["plan_id"]
    buyer_id = body["buyer_id"]
    for f, v in (("operation_id", operation_id), ("plan_id", plan_id), ("buyer_id", buyer_id)):
        if not isinstance(v, str):
            raise ApiError("ERR_VALIDATION", f"{f} must be a string", 400)
    ctype = req_enum(body, "contract_type", {"FLAT_PRICE", "HTA", "BASIS"})
    bushels = req_int(body, "bushels", positive=True)

    fixed_price = opt_number(body, "fixed_price")
    basis_level = opt_number(body, "basis_level")
    contract_month = body.get("contract_month")

    # Conditional fields by contract_type
    if ctype == "FLAT_PRICE":
        if fixed_price is None:
            raise ApiError("ERR_VALIDATION", "fixed_price required for FLAT_PRICE", 400)
        if basis_level is not None or contract_month is not None:
            raise ApiError("ERR_VALIDATION", "basis_level/contract_month forbidden for FLAT_PRICE", 400)
    elif ctype == "BASIS":
        if basis_level is None:
            raise ApiError("ERR_VALIDATION", "basis_level required for BASIS", 400)
        if fixed_price is not None or contract_month is not None:
            raise ApiError("ERR_VALIDATION", "fixed_price/contract_month forbidden for BASIS", 400)
    else:  # HTA
        if contract_month is None:
            raise ApiError("ERR_VALIDATION", "contract_month required for HTA", 400)
        if fixed_price is not None or basis_level is not None:
            raise ApiError("ERR_VALIDATION", "fixed_price/basis_level forbidden for HTA", 400)
        check_contract_month(contract_month)

    # delivery window: half-open [start, end); window inversion -> ERR_VALIDATION
    dws_raw = body["delivery_window_start"]
    dwe_raw = body["delivery_window_end"]
    if not isinstance(dws_raw, str) or not isinstance(dwe_raw, str):
        raise ApiError("ERR_VALIDATION", "delivery_window_start/end must be strings", 400)
    dws = parse_date(dws_raw)
    dwe = parse_date(dwe_raw)
    if not dws < dwe:
        raise ApiError("ERR_VALIDATION", "delivery_window_start must be < delivery_window_end", 400)

    # Existence
    op = DB.operations.get(operation_id)
    if op is None:
        raise ApiError("ERR_NOT_FOUND", f"GrowerOperation not found: {operation_id}", 404)
    plan = DB.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", f"MarketingPlan not found: {plan_id}", 404)
    buyer = DB.buyers.get(buyer_id)
    if buyer is None:
        raise ApiError("ERR_NOT_FOUND", f"Buyer not found: {buyer_id}", 404)
    if plan["operation_id"] != operation_id:
        raise ApiError("ERR_VALIDATION", "plan_id does not belong to operation_id", 400)

    # Grower ownership check
    check_grower_ownership(user_id, role, operation_id)

    # State: plan must be ACTIVE
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"Plan in state {plan['status']} cannot accept contracts", 409)

    # Compliance: governing agreement disclosure currently acknowledged
    agreement = governing_agreement(operation_id)
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "Operation lacks an ACTIVE AdvisoryAgreement", 409)
    ds = agreement["disclosure_status"]
    if ds in {"REQUIRED", "DELIVERED", "NONE"}:
        raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED", "Disclosure not ACKNOWLEDGED", 409)
    if ds == "STALE" or agreement.get("acknowledged_agreement_version") != agreement["version"]:
        raise ApiError("ERR_DISCLOSURE_STALE", "Disclosure acknowledgment is stale", 409)

    # Referential state: buyer must be APPROVED
    if buyer["status"] != "APPROVED":
        raise ApiError("ERR_BUYER_NOT_APPROVED", "Buyer is not APPROVED", 409)

    # Temporal: half-open window overlap vs same buyer's OPEN/PARTIALLY_DELIVERED contracts
    for c in DB.contracts.values():
        if c["buyer_id"] != buyer_id:
            continue
        if c["fulfillment_status"] not in {"OPEN", "PARTIALLY_DELIVERED"}:
            continue
        es = parse_date(c["delivery_window_start"])
        ee = parse_date(c["delivery_window_end"])
        if dws < ee and es < dwe:
            raise ApiError("ERR_DELIVERY_WINDOW_OVERLAP", "Delivery window overlaps an existing contract", 409)

    # Over-sold
    if op["over_sold_flag"]:
        raise ApiError("ERR_OVER_SOLD_POSITION", "Operation over_sold_flag is set", 409)

    # Uncommitted capacity
    if bushels > plan["uncommitted_bushels"]:
        raise ApiError("ERR_INSUFFICIENT_UNCOMMITTED_BUSHELS", "Contract bushels exceed plan uncommitted bushels", 409)

    # Coverage cap for FLAT_PRICE (born PRICED)
    pricing_status = "PRICED" if ctype == "FLAT_PRICE" else "UNPRICED"
    if ctype == "FLAT_PRICE":
        if plan["hedged_bushels"] + plan["priced_contract_bushels"] + bushels > plan["coverage_cap_bushels"]:
            raise ApiError("ERR_COVERAGE_CAP_EXCEEDED", "Coverage cap exceeded", 409)

    cid = db.new_id()
    now = db.now_iso()
    contract = {
        "id": cid,
        "operation_id": operation_id,
        "plan_id": plan_id,
        "buyer_id": buyer_id,
        "contract_type": ctype,
        "bushels": bushels,
        "fixed_price": fixed_price,
        "basis_level": basis_level,
        "contract_month": contract_month,
        "delivery_window_start": dws_raw,
        "delivery_window_end": dwe_raw,
        "fixation_price": None,
        "effective_price": fixed_price if ctype == "FLAT_PRICE" else None,
        "delivered_bushels": Decimal("0"),
        "settled_value_dollars": Decimal("0"),
        "default_penalty_dollars": None,
        "pricing_status": pricing_status,
        "fulfillment_status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.contracts[cid] = contract
    recompute_plan_counters(plan)
    return success_object(ser_contract(contract), status=201)


@bp.route("/advisory/sales-contracts/<contractId>", methods=["GET"])
def get_contract(contractId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    c = get_or_404(DB.contracts, contractId, "SalesContract")
    check_grower_ownership(user_id, role, c["operation_id"])
    return success_object(ser_contract(c))


@bp.route("/advisory/sales-contracts", methods=["GET"])
def list_contracts():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    limit, offset = pagination_params()
    operation_id = request.args.get("operation_id")
    buyer_id = request.args.get("buyer_id")
    plan_id = request.args.get("plan_id")
    fstatus = request.args.get("fulfillment_status")
    pstatus = request.args.get("pricing_status")
    items = list(DB.contracts.values())
    if role == "Grower":
        items = [c for c in items if c["operation_id"] == user_id]
    if operation_id is not None:
        items = [c for c in items if c["operation_id"] == operation_id]
    if buyer_id is not None:
        items = [c for c in items if c["buyer_id"] == buyer_id]
    if plan_id is not None:
        items = [c for c in items if c["plan_id"] == plan_id]
    if fstatus is not None:
        items = [c for c in items if c["fulfillment_status"] == fstatus]
    if pstatus is not None:
        items = [c for c in items if c["pricing_status"] == pstatus]
    items.sort(key=lambda c: c["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_contract(c) for c in slice_], limit, offset, total)


@bp.route("/advisory/sales-contracts/<contractId>/fix-price", methods=["POST"])
def fix_price(contractId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    c = get_or_404(DB.contracts, contractId, "SalesContract")
    body = req_body()
    require_fields(body, ["fixation_price"])
    fixation = req_number(body, "fixation_price", positive=True)
    # State gate: fulfillment in OPEN/PARTIALLY_DELIVERED
    if c["fulfillment_status"] not in {"OPEN", "PARTIALLY_DELIVERED"}:
        raise ApiError("ERR_INVALID_STATE", f"Contract fulfillment {c['fulfillment_status']} does not permit fix-price", 409)
    # Pricing gate
    if c["contract_type"] == "FLAT_PRICE" or c["pricing_status"] == "PRICED":
        raise ApiError("ERR_PRICING_NOT_ALLOWED", "fix-price not allowed on this contract", 409)
    # Coverage cap re-check at fixation
    plan = DB.plans[c["plan_id"]]
    if plan["hedged_bushels"] + plan["priced_contract_bushels"] + c["bushels"] > plan["coverage_cap_bushels"]:
        raise ApiError("ERR_COVERAGE_CAP_EXCEEDED", "Coverage cap exceeded at fixation", 409)
    c["fixation_price"] = fixation
    if c["contract_type"] == "HTA":
        c["effective_price"] = fixation
    else:  # BASIS
        c["effective_price"] = r2(fixation + D(c["basis_level"]))
    c["pricing_status"] = "PRICED"
    touch(c)
    recompute_plan_counters(plan)
    return success_object(ser_contract(c))


@bp.route("/advisory/sales-contracts/<contractId>/cancel", methods=["POST"])
def cancel_contract(contractId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    c = get_or_404(DB.contracts, contractId, "SalesContract")
    check_grower_ownership(user_id, role, c["operation_id"])
    if c["fulfillment_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Contract in state {c['fulfillment_status']} cannot be cancelled", 409)
    if D(c["delivered_bushels"]) != 0:
        raise ApiError("ERR_INVALID_STATE", "Contract has deliveries; cannot cancel", 409)
    c["fulfillment_status"] = "CANCELLED"
    touch(c)
    plan = DB.plans[c["plan_id"]]
    recompute_plan_counters(plan)
    evaluate_over_sold(c["operation_id"])
    return success_object(ser_contract(c))


@bp.route("/advisory/sales-contracts/<contractId>/default", methods=["POST"])
def default_contract(contractId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    c = get_or_404(DB.contracts, contractId, "SalesContract")
    if c["fulfillment_status"] not in {"OPEN", "PARTIALLY_DELIVERED"}:
        raise ApiError("ERR_INVALID_STATE", f"Contract in state {c['fulfillment_status']} cannot be defaulted", 409)
    # clock date > delivery_window_end
    now = db.logical_now().date()
    dwe = parse_date(c["delivery_window_end"])
    if not now > dwe:
        raise ApiError("ERR_INVALID_STATE", "Logical clock date is not past delivery_window_end", 409)
    if D(c["delivered_bushels"]) >= c["bushels"]:
        raise ApiError("ERR_INVALID_STATE", "Contract fully delivered; cannot default", 409)
    if c["pricing_status"] == "PRICED":
        op = DB.operations[c["operation_id"]]
        tick = latest_settlement_tick(op["primary_commodity"])
        if tick is None:
            raise ApiError("ERR_NO_SETTLEMENT_PRICE", "No SETTLEMENT MarketTick for default penalty", 409)
        latest_price = D(tick["price"])
        undelivered = D(c["bushels"]) - D(c["delivered_bushels"])
        penalty = undelivered * max(Decimal("0"), latest_price - D(c["effective_price"]))
        c["default_penalty_dollars"] = r2(penalty)
    c["fulfillment_status"] = "DEFAULTED"
    touch(c)
    plan = DB.plans[c["plan_id"]]
    recompute_plan_counters(plan)
    evaluate_over_sold(c["operation_id"])
    return success_object(ser_contract(c))
