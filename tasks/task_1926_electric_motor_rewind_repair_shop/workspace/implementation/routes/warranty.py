"""Warranty claims."""
from flask import Blueprint, request
from middleware import require_role
from errors import (
    err_invalid_state, err_invalid_input, err_segregation,
    err_warranty_out_of_window, err_warranty_excluded_mode,
)
from db import store, new_id
from response import success_object, success_list
from serializers import warranty_claim_view
from services import calc
from services.lazy import bump
from routes.common import (
    get_json_body, parse_enum_field, get_shop_or_404, get_work_order_or_404,
    get_claim_or_404, get_pagination, paginate,
)

bp = Blueprint("warranty", __name__)

COVERED_MODES = {"WINDING_SHORT", "GROUND_FAULT", "BEARING_FAILURE"}
ALL_MODES = COVERED_MODES | {"OVERLOAD", "INGRESS", "MISAPPLICATION", "UNAUTHORIZED_REPAIR"}


@bp.route("/shops/<shopId>/work-orders/<woId>/warranty-claims", methods=["POST"])
def file_claim(shopId, woId):
    user_id, role = require_role("Customer", "ServiceManager")
    get_shop_or_404(shopId)
    wo = get_work_order_or_404(woId, shopId)
    body = get_json_body()
    failure_mode = parse_enum_field(body, "failure_mode", ALL_MODES, required=True)

    if wo["status"] not in ("DELIVERED", "CLOSED"):
        raise err_invalid_state("Warranty claim requires delivered work order")

    now = store.now()
    months_elapsed = calc.compute_months_elapsed(wo["delivered_at"], now)
    claim = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "work_order_id": woId,
        "customer_id": wo["customer_id"],
        "failure_mode": failure_mode,
        "filed_at": now,
        "months_elapsed": months_elapsed,
        "remedy": None,
        "credit_cents": 0,
        "status": "FILED",
        "reviewed_by": None,
        "resolution_work_order_id": None,
        "_filed_by_user_id": user_id,
        "_filed_by_role": role,
    }
    store.warranty_claims[claim["id"]] = claim
    return success_object(warranty_claim_view(claim), status=201)


def _list_claims(wo_id_filter, shop_id_filter):
    items = list(store.warranty_claims.values())
    if wo_id_filter is not None:
        items = [c for c in items if c["work_order_id"] == wo_id_filter]
    if shop_id_filter is not None:
        items = [
            c for c in items
            if store.work_orders.get(c["work_order_id"], {}).get("shop_id") == shop_id_filter
        ]
    if request.args.get("customer_id"):
        items = [c for c in items if c["customer_id"] == request.args["customer_id"]]
    if request.args.get("status"):
        items = [c for c in items if c["status"] == request.args["status"]]
    if request.args.get("resolution_work_order_id"):
        items = [c for c in items if c.get("resolution_work_order_id") == request.args["resolution_work_order_id"]]
    items.sort(key=lambda c: c["created_at"])
    return items


@bp.route("/shops/<shopId>/work-orders/<woId>/warranty-claims", methods=["GET"])
def list_claims(shopId, woId):
    require_role("ShopAdmin", "Technician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    get_work_order_or_404(woId, shopId)
    limit, offset = get_pagination()
    items = _list_claims(woId, None)
    page, total = paginate(items, limit, offset)
    return success_list([warranty_claim_view(c) for c in page], limit, offset, total)


@bp.route("/shops/<shopId>/warranty-claims/<claimId>", methods=["GET"])
def get_claim(shopId, claimId):
    require_role("ShopAdmin", "Technician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    c = get_claim_or_404(claimId, shop_id=shopId)
    return success_object(warranty_claim_view(c))


@bp.route("/shops/warranty-claims-flat", methods=["GET"])
def list_claims_flat():
    require_role("ShopAdmin", "Technician", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    wo_id = request.args.get("work_order_id")
    items = _list_claims(wo_id, None)
    page, total = paginate(items, limit, offset)
    return success_list([warranty_claim_view(c) for c in page], limit, offset, total)


@bp.route("/shops/warranty-claims-flat/<claimId>", methods=["GET"])
def get_claim_flat(claimId):
    require_role("ShopAdmin", "Technician", "Estimator", "ServiceManager", "Customer")
    c = get_claim_or_404(claimId)
    return success_object(warranty_claim_view(c))


@bp.route("/shops/<shopId>/warranty-claims/<claimId>/start-review", methods=["POST"])
def start_review(shopId, claimId):
    user_id, _ = require_role("ServiceManager")
    get_shop_or_404(shopId)
    c = get_claim_or_404(claimId, shop_id=shopId)
    if c["status"] != "FILED":
        raise err_invalid_state("Claim must be FILED to start review")
    c["status"] = "UNDER_REVIEW"
    c["reviewed_by"] = user_id
    bump(c)
    return success_object(warranty_claim_view(c))


@bp.route("/shops/<shopId>/warranty-claims/<claimId>/approve", methods=["POST"])
def approve_claim(shopId, claimId):
    user_id, _ = require_role("ServiceManager")
    shop = get_shop_or_404(shopId)
    c = get_claim_or_404(claimId, shop_id=shopId)
    body = get_json_body()
    remedy = parse_enum_field(body, "remedy", {"FREE_REWIND", "PRORATED_CREDIT"}, required=True)

    if c["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Claim must be UNDER_REVIEW to approve")

    # Segregation: approver may not equal filer when filer was a ServiceManager
    if c.get("_filed_by_role") == "ServiceManager" and c.get("_filed_by_user_id") == user_id:
        raise err_segregation("Approver may not be the same X-User-ID that filed the claim")

    # Window: months_elapsed < warranty_months
    if c["months_elapsed"] >= shop["warranty_months"]:
        raise err_warranty_out_of_window()

    # Covered mode
    if c["failure_mode"] not in COVERED_MODES:
        raise err_warranty_excluded_mode()

    c["remedy"] = remedy
    wo = store.work_orders[c["work_order_id"]]
    customer = store.customers[c["customer_id"]]

    if remedy == "PRORATED_CREDIT":
        credit = calc.compute_prorated_credit(
            wo["invoice_total_cents"], c["months_elapsed"], shop["warranty_months"]
        )
        c["credit_cents"] = credit
        customer["account_credit_cents"] += credit
        bump(customer)
        c["status"] = "RESOLVED"
    else:  # FREE_REWIND
        # create a new work order: priority STANDARD, no_charge True, same motor/customer
        now = store.now()
        new_wo = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "shop_id": shopId,
            "customer_id": wo["customer_id"],
            "motor_id": wo["motor_id"],
            "priority": "STANDARD",
            "no_charge": True,
            "status": "INTAKE",
            "failure_diagnosis": None,
            "rewind_hours": None,
            "materials_cents": None,
            "replacement_cost_cents": None,
            "active_quote_id": None,
            "invoice_total_cents": 0,
            "delivered_at": None,
            "closed_at": None,
            "_reached_balancing": False,
            "_incoming_recorder": None,
            "_coil_recorder": None,
        }
        store.work_orders[new_wo["id"]] = new_wo
        c["resolution_work_order_id"] = new_wo["id"]
        motor = store.motors[wo["motor_id"]]
        motor["custody"] = "IN_SHOP"
        bump(motor)
        c["status"] = "APPROVED"

    bump(c)
    return success_object(warranty_claim_view(c))


@bp.route("/shops/<shopId>/warranty-claims/<claimId>/deny", methods=["POST"])
def deny_claim(shopId, claimId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    c = get_claim_or_404(claimId, shop_id=shopId)
    if c["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Claim must be UNDER_REVIEW to deny")
    c["status"] = "DENIED"
    bump(c)
    return success_object(warranty_claim_view(c))
