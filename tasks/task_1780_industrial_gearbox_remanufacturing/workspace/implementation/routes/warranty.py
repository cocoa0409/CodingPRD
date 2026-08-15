"""Warranty claims and dual-basis eligibility (PRD 3.7)."""
from flask import Blueprint

from db import store, new_id, new_common, touch, set_field
from errors import ApiError
from middleware import (get_context, require_roles, check_customer_scope,
                        owning_customer_id_of_order,
                        owning_customer_id_of_claim, ALL_ROLES)
from response import ok, created, paginate
from services import workflow
from validation import parse_body, no_body, require_path_entity, schema_field

bp = Blueprint("warranty", __name__)


def _load_claim(claim_id):
    return require_path_entity(store.warranty_claims, claim_id)


def _require_state(claim, allowed):
    if claim["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Claim status %s does not admit this action" % claim["status"])


@bp.post("/reman/orders/<order_id>/warranty-claims")
def create_claim(order_id):
    uid, role, _ = get_context()
    require_roles(["Customer"])
    order = require_path_entity(store.orders, order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    body = parse_body({
        "reported_hours": schema_field("integer"),
        "claim_reason": schema_field("string"),
    }, allow_empty=False)
    if order["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A CANCELLED order is locked against any further action")
    unit = workflow.order_unit(order)
    if body["reported_hours"] < unit["cumulative_service_hours"]:
        raise ApiError("ERR_HOURS_REGRESSION", 422,
                       "reported_hours is below the unit's current "
                       "cumulative_service_hours odometer")
    claim = {
        "id": new_id(),
        "reman_order_id": order["id"],
        "reported_hours": body["reported_hours"],
        "claim_reason": body["claim_reason"],
        "hours_since_reman": None,
        "warranty_clock_start_hours": None,
        "eligibility": None,
        "status": "OPEN",
    }
    new_common(claim)
    store.warranty_claims[claim["id"]] = claim
    if order["status"] == "COMPLETED":
        # Resolve the dual-basis verdict at filing time (PRD 3.7).
        workflow.resolve_claim_eligibility(claim, order)
        set_field(unit, "commercial_status", "UNDER_WARRANTY_REVIEW")
    return created(claim)


@bp.get("/reman/orders/<order_id>/warranty-claims")
def list_claims(order_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    order = require_path_entity(store.orders, order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    return ok(paginate(workflow.claims_of_order(order_id)),
              rtype="array", pagination=paginate)


@bp.get("/reman/warranty-claims/<claim_id>")
def get_claim(claim_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    claim = _load_claim(claim_id)
    check_customer_scope(uid, role, owning_customer_id_of_claim(claim))
    return ok(claim)


@bp.post("/reman/warranty-claims/<claim_id>/review")
def review_claim(claim_id):
    uid, role, _ = get_context()
    require_roles(["QualityInspector"])
    claim = _load_claim(claim_id)
    no_body()
    _require_state(claim, ["OPEN"])
    order = store.orders.get(claim["reman_order_id"])
    if order is None or order["status"] != "COMPLETED":
        raise ApiError("ERR_ORDER_NOT_COMPLETED", 422,
                       "A claim may be reviewed only once its order is COMPLETED")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    unit = workflow.order_unit(order)
    set_field(unit, "commercial_status", "UNDER_WARRANTY_REVIEW")
    return ok(claim)


@bp.post("/reman/warranty-claims/<claim_id>/approve")
def approve_claim(claim_id):
    uid, role, _ = get_context()
    require_roles(["ServiceManager"])
    claim = _load_claim(claim_id)
    no_body()
    _require_state(claim, ["UNDER_REVIEW"])
    if claim["eligibility"] != "COVERED":
        raise ApiError("ERR_WARRANTY_EXPIRED", 422,
                       "Only a COVERED claim may be approved")
    claim["status"] = "APPROVED"
    touch(claim)
    order = store.orders.get(claim["reman_order_id"])
    unit = workflow.order_unit(order)
    set_field(unit, "commercial_status", "WARRANTY_FLAGGED")
    return ok(claim)


@bp.post("/reman/warranty-claims/<claim_id>/deny")
def deny_claim(claim_id):
    uid, role, _ = get_context()
    require_roles(["ServiceManager"])
    claim = _load_claim(claim_id)
    no_body()
    _require_state(claim, ["UNDER_REVIEW"])
    claim["status"] = "DENIED"
    touch(claim)
    order = store.orders.get(claim["reman_order_id"])
    unit = workflow.order_unit(order)
    set_field(unit, "commercial_status", "STANDARD")
    return ok(claim)
