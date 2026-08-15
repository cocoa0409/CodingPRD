"""WarrantyClaim filing, review, resubmission/appeal, resolution (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
from db import bump, clock, create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import get_or_404, ser
from validate import Shape, get_body, pagination_params

bp = Blueprint("warranty", __name__)

CLAIM_TYPES = ["FACTORY_DEFECT", "TRANSPORT_DAMAGE", "INSTALLATION_DAMAGE"]
REVIEW_DECISIONS = ["APPROVE", "DENY", "REQUEST_INFO"]


def _list(rows, filters):
    limit, offset = pagination_params()
    rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/warranty-claims")
@require("Customer", "ServiceManager")
def create_warranty_claim(actor_id, actor_role):
    shape = Shape(get_body())
    shape.req_str("home_unit_id")
    shape.req_str("sales_order_id")
    shape.req_enum("claim_type", CLAIM_TYPES)
    shape.req_str("description")
    shape.req_int("estimated_cost_cents", minimum=0)
    # (3) ownership: Customer callers act only on their own orders
    order = None
    if shape.ok("sales_order_id"):
        order = store.sales_orders.get(shape.value("sales_order_id"))
    if actor_role == "Customer" and order is not None and order["customer_id"] != actor_id:
        fail("ERR_UNAUTHORIZED", "Customers may act only on their own orders")
    # (5) body foreign-key existence
    unit = None
    if shape.ok("home_unit_id"):
        unit = store.home_units.get(shape.value("home_unit_id"))
        if unit is None:
            fail("ERR_HOME_UNIT_NOT_FOUND", "Home unit not found")
    if shape.ok("sales_order_id") and order is None:
        fail("ERR_SALES_ORDER_NOT_FOUND", "Sales order not found")
    # (25) warranty coverage: anchor per claim type; inclusive window ends;
    # TRANSPORT_DAMAGE is state-gated instead of windowed. Priority 25 runs
    # before field-shape validation (33).
    now = clock.now()
    claim_type = shape.value("claim_type") if shape.ok("claim_type") else None
    coverage_end = None
    if unit is not None and claim_type == "FACTORY_DEFECT":
        if unit["status"] not in ("ON_SITE", "INSTALLED") or unit["delivered_at"] is None:
            fail("ERR_WARRANTY_EXPIRED",
                 "Factory-defect claims require a delivered unit within coverage")
        coverage_end = unit["delivered_at"] + timedelta(days=calc.FACTORY_COVERAGE_DAYS)
        if now > coverage_end:
            fail("ERR_WARRANTY_EXPIRED", "Claim is past the factory-defect coverage window")
    elif unit is not None and claim_type == "INSTALLATION_DAMAGE":
        if unit["status"] != "INSTALLED" or unit["set_completed_at"] is None:
            fail("ERR_WARRANTY_EXPIRED",
                 "Installation-damage claims require an installed unit within coverage")
        coverage_end = unit["set_completed_at"] + timedelta(days=calc.INSTALL_COVERAGE_DAYS)
        if now > coverage_end:
            fail("ERR_WARRANTY_EXPIRED", "Claim is past the installation coverage window")
    elif unit is not None and claim_type == "TRANSPORT_DAMAGE":
        # no window at all — state gate instead
        if unit["status"] not in ("IN_TRANSIT", "ON_SITE"):
            fail("ERR_WARRANTY_EXPIRED",
                 "Transport-damage claims are reportable only while IN_TRANSIT or ON_SITE")
    shape.raise_if_errors()
    rec = create_record(store.warranty_claims, {
        "home_unit_id": unit["id"],
        "sales_order_id": order["id"],
        "claim_type": claim_type,
        "description": shape.value("description"),
        "estimated_cost_cents": shape.value("estimated_cost_cents"),
        "approved_cost_cents": None,
        "coverage_window_end": coverage_end,
        "status": "UNDER_REVIEW",
        "reviewed_by": None,
        "resolved_by": None,
    })
    return ok(ser(rec), 201)


@bp.get("/warranty-claims/<rid>")
@require(*ALL_ROLES)
def get_warranty_claim(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.warranty_claims, rid, "ERR_WARRANTY_CLAIM_NOT_FOUND",
                             "Warranty claim")))


@bp.get("/home-units/<rid>/warranty-claims")
@require(*ALL_ROLES)
def list_unit_warranty_claims(rid, actor_id, actor_role):
    unit = get_or_404(store.home_units, rid, "ERR_HOME_UNIT_NOT_FOUND", "Home unit")
    return _list([c for c in store.warranty_claims.values()
                  if c["home_unit_id"] == unit["id"]], {})


@bp.get("/warranty-claims")
@require(*ALL_ROLES)
def list_warranty_claims(actor_id, actor_role):
    filters = {}
    for k in ("sales_order_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return _list(store.warranty_claims.values(), filters)


def _get_claim(rid):
    return get_or_404(store.warranty_claims, rid, "ERR_WARRANTY_CLAIM_NOT_FOUND",
                      "Warranty claim")


@bp.post("/warranty-claims/<rid>/review")
@require("ServiceManager")
def review_claim(rid, actor_id, actor_role):
    claim = _get_claim(rid)
    # (7) state precondition
    if claim["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW claim can be reviewed")
    shape = Shape(get_body())
    shape.req_enum("decision", REVIEW_DECISIONS)
    shape.opt_int("approved_cost_cents", minimum=0)
    decision = shape.value("decision") if shape.ok("decision") else None
    # (32) claim approval cap
    if decision == "APPROVE" and shape.ok("approved_cost_cents") \
            and shape.value("approved_cost_cents") is not None:
        if shape.value("approved_cost_cents") > claim["estimated_cost_cents"]:
            fail("ERR_CLAIM_AMOUNT_EXCESS",
                 "approved_cost_cents exceeds estimated_cost_cents")
    if decision == "APPROVE" and (
            not shape.ok("approved_cost_cents") or shape.value("approved_cost_cents") is None):
        shape._err("approved_cost_cents", "is required for an APPROVE decision")
    shape.raise_if_errors()
    if decision == "APPROVE":
        claim["approved_cost_cents"] = shape.value("approved_cost_cents")
        claim["status"] = "APPROVED"
    elif decision == "DENY":
        claim["status"] = "DENIED"
    else:
        claim["status"] = "INFO_REQUESTED"
    claim["reviewed_by"] = actor_id
    bump(claim)
    return ok(ser(claim))


@bp.post("/warranty-claims/<rid>/resubmit")
@require("Customer")
def resubmit_claim(rid, actor_id, actor_role):
    claim = _get_claim(rid)
    # (3) ownership: only the order's own customer
    order = store.sales_orders.get(claim["sales_order_id"])
    if order is None or order["customer_id"] != actor_id:
        fail("ERR_UNAUTHORIZED", "Customers may act only on their own orders")
    # (7) review loop (INFO_REQUESTED) and appeal loop (DENIED)
    if claim["status"] not in ("INFO_REQUESTED", "DENIED"):
        fail("ERR_INVALID_STATE", "Only INFO_REQUESTED or DENIED claims can be resubmitted")
    shape = Shape(get_body())
    shape.req_str("description")
    shape.raise_if_errors()
    claim["description"] = shape.value("description")
    claim["status"] = "UNDER_REVIEW"
    bump(claim)
    return ok(ser(claim))


@bp.post("/warranty-claims/<rid>/resolve")
@require("ServiceManager")
def resolve_claim(rid, actor_id, actor_role):
    claim = _get_claim(rid)
    # (7) state precondition
    if claim["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED claim can be resolved")
    # (19) segregation of duties: resolver must differ from the reviewer
    if claim["reviewed_by"] == actor_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The resolving user must differ from the claim's reviewer")
    claim["status"] = "RESOLVED"
    claim["resolved_by"] = actor_id
    bump(claim)
    return ok(ser(claim))
