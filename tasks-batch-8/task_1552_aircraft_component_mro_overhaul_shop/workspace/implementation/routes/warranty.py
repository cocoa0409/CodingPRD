from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store
from errors import ApiError
from helpers import (
    add_trace,
    base_fields,
    create_compliance_records,
    get_claim_or_404,
    get_wo_or_404,
    list_response,
    pub,
    touch,
)
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok
from routes.work_orders import _new_work_order

bp = Blueprint("warranty", __name__, url_prefix="/mro")


@bp.route("/warranty-claims", methods=["POST"])
@require_roles("Customer")
def create_claim():
    body = validate_body(
        get_json_body(),
        {
            "original_work_order_id": ("str", True),
            "claim_cycles_used": ("int", True, None, 0, None),
            "claim_months_used": ("int", True, None, 0, None),
            "failure_description": ("str", True),
        },
    )
    wo = get_wo_or_404(body["original_work_order_id"])
    # Order: original work order must be CLOSED before limits are evaluated.
    if wo["status"] != "CLOSED":
        raise ApiError(
            "ERR_WARRANTY_REQUIRES_CLOSED_WO", 409, "Original work order is not CLOSED"
        )
    unit = store.units[wo["unit_id"]]
    part = store.parts[unit["part_id"]]
    if (
        body["claim_cycles_used"] > part["warranty_cycle_limit"]
        or body["claim_months_used"] > part["warranty_month_limit"]
    ):
        raise ApiError(
            "ERR_WARRANTY_LIMIT_EXCEEDED", 422, "Claim exceeds warranty coverage ceilings"
        )
    claim = dict(base_fields())
    claim.update(
        {
            "customer_id": request.user_id,
            "original_work_order_id": wo["id"],
            "unit_id": wo["unit_id"],
            "claim_cycles_used": body["claim_cycles_used"],
            "claim_months_used": body["claim_months_used"],
            "failure_description": body["failure_description"],
            "status": "SUBMITTED",
            "credit_variant": None,
            "credit_cents": None,
            "rework_work_order_id": None,
            "denial_reason": None,
        }
    )
    store.claims[claim["id"]] = claim
    return ok(pub(claim), 201)


@bp.route("/warranty-claims/<claimId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_claim(claimId):
    return ok(pub(get_claim_or_404(claimId)))


@bp.route("/warranty-claims", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_claims():
    return list_response(
        store.claims.values(),
        filters={
            "customer_id": "customer_id",
            "original_work_order_id": "original_work_order_id",
            "rework_work_order_id": "rework_work_order_id",
            "status": "status",
        },
    )


@bp.route("/warranty-claims/<claimId>/review", methods=["POST"])
@require_roles("ShopManager")
def review_claim(claimId):
    claim = get_claim_or_404(claimId)
    body = validate_body(
        get_json_body(),
        {"decision": ("enum", True, ["ACCEPT", "DENY"]), "denial_reason": ("str", False)},
    )
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", 409, "Warranty claim not SUBMITTED")
    if body["decision"] == "DENY":
        if not body["denial_reason"]:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "denial_reason is required when decision=DENY"
            )
        claim["status"] = "DENIED"
        claim["denial_reason"] = body["denial_reason"]
        touch(claim)
        return ok(pub(claim))
    # ACCEPT: compute credit, then cascade.
    unit = store.units[claim["unit_id"]]
    part = store.parts[unit["part_id"]]
    original = store.work_orders[claim["original_work_order_id"]]
    invoice = None
    for inv in store.invoices.values():
        if inv["source_type"] == "WORK_ORDER" and inv["work_order_id"] == original["id"]:
            invoice = inv
            break
    base_credit = (invoice["labor_cents"] or 0) + (invoice["parts_cents"] or 0) if invoice else 0
    cycle_limit = part["warranty_cycle_limit"]
    if claim["claim_cycles_used"] * 2 <= cycle_limit:
        credit_variant = "FULL"
        credit = base_credit
    else:
        credit_variant = "PRORATED"
        remaining = max(0, cycle_limit - claim["claim_cycles_used"])
        credit = int(
            (Decimal(base_credit) * Decimal(remaining) / Decimal(cycle_limit)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    claim["credit_variant"] = credit_variant
    claim["credit_cents"] = credit
    claim["status"] = "ACCEPTED"
    # Hop 2: rework work order auto-created directly in REPAIR_IN_PROGRESS.
    original_labor = original["labor_charge_cents"]
    if original_labor is None:
        original_labor = original["labor_estimate_cents"] or 0
    rework = _new_work_order(
        claim["customer_id"],
        claim["unit_id"],
        "WARRANTY_REWORK",
        "REPAIR_IN_PROGRESS",
        labor_estimate=original_labor,
        labor_charge=original_labor,
    )
    claim["rework_work_order_id"] = rework["id"]
    # Hop 3: induction engages the unit.
    unit["custody_status"] = "IN_SHOP"
    unit["condition_status"] = "UNSERVICEABLE"
    touch(unit)
    add_trace(unit["id"], "WARRANTY_INDUCT", work_order_id=rework["id"], notes=claim["id"])
    create_compliance_records(rework["id"], unit["part_id"])
    touch(claim)
    return ok(pub(claim))
