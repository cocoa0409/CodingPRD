"""FinancingApplication origination, underwriting, rate lock, funding
(PRD 3.5). Creation is OCC-guarded on SalesOrder.version (PRD 2.7)."""

from datetime import timedelta

from flask import Blueprint

import calc
from db import bump, clock, create_record, store
from errors import fail
from middleware import ALL_ROLES, require
from response import ok, ok_list
from services import (bubble_financing_approved, bubble_financing_funded,
                      find_issued_title, get_or_404, ser)
from validate import Shape, get_body, pagination_params

bp = Blueprint("financing", __name__)

FINANCING_TYPES = ["CHATTEL", "REAL_PROPERTY"]
DECISIONS = ["APPROVE", "CONDITIONAL", "DENY"]
ACTIVE_APP_STATUSES = ("DRAFT", "SUBMITTED", "CONDITIONALLY_APPROVED", "APPROVED")
RATE_LOCK_DAYS = 14


def _list(rows):
    limit, offset = pagination_params()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return ok_list([ser(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/sales-orders/<rid>/financing-applications")
@require("SalesConsultant")
def create_financing_application(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    shape = Shape(get_body())
    shape.req_enum("financing_type", FINANCING_TYPES)
    shape.req_str("lender_name")
    shape.req_int("term_months", minimum=1)
    shape.req_int("down_payment_cents", minimum=0)
    shape.req_int("expected_sales_order_version")
    # (6) optimistic concurrency on the parent order
    if shape.ok("expected_sales_order_version"):
        if shape.value("expected_sales_order_version") != order["version"]:
            fail("ERR_STALE_VERSION",
                 "expected_sales_order_version does not match the order's current version")
    # (7) state gate: the first application opens once the site is approved;
    # subsequent applications self-loop PENDING_FINANCING
    if order["deal_status"] not in ("SITE_APPROVED", "PENDING_FINANCING"):
        fail("ERR_INVALID_STATE",
             "Financing may be originated only from SITE_APPROVED or PENDING_FINANCING")
    # (21) term cap
    if shape.ok("financing_type") and shape.ok("term_months"):
        if shape.value("term_months") > calc.term_cap_months(shape.value("financing_type")):
            fail("ERR_TERM_EXCEEDS_CAP", "term_months exceeds the financing type's cap")
    # (28) type coherence: application type must equal the order's type
    if shape.ok("financing_type") and shape.value("financing_type") != order["financing_type"]:
        fail("ERR_FINANCING_TYPE_INCOMPATIBLE",
             "Application financing_type must equal the order's financing_type")
    # field shape: down payment must cover the recorded deposit
    if shape.ok("down_payment_cents") and shape.value("down_payment_cents") < order["deposit_cents"]:
        shape._err("down_payment_cents", "must be >= the order's deposit_cents")
    shape.raise_if_errors()

    # supersede the order's prior active application
    for a in store.financing_applications.values():
        if a["sales_order_id"] == order["id"] and a["status"] in ACTIVE_APP_STATUSES:
            a["status"] = "SUPERSEDED"
            bump(a)
    rec = create_record(store.financing_applications, {
        "sales_order_id": order["id"],
        "financing_type": shape.value("financing_type"),
        "lender_name": shape.value("lender_name"),
        "term_months": shape.value("term_months"),
        "down_payment_cents": shape.value("down_payment_cents"),
        "requested_amount_cents": None,
        "apr_bps": None,
        "estimated_payment_cents": None,
        "monthly_payment_cents": None,
        "rate_lock_expires_at": None,
        "status": "DRAFT",
        "decided_by": None,
    })
    if order["deal_status"] == "SITE_APPROVED":
        order["deal_status"] = "PENDING_FINANCING"
    bump(order)
    return ok(ser(rec), 201)


@bp.get("/sales-orders/<rid>/financing-applications")
@require(*ALL_ROLES)
def list_financing_applications(rid, actor_id, actor_role):
    order = get_or_404(store.sales_orders, rid, "ERR_SALES_ORDER_NOT_FOUND", "Sales order")
    return _list([a for a in store.financing_applications.values()
                  if a["sales_order_id"] == order["id"]])


@bp.get("/financing-applications/<rid>")
@require(*ALL_ROLES)
def get_financing_application(rid, actor_id, actor_role):
    return ok(ser(get_or_404(store.financing_applications, rid,
                             "ERR_FINANCING_APPLICATION_NOT_FOUND", "Financing application")))


@bp.post("/financing-applications/<rid>/submit")
@require("SalesConsultant")
def submit_application(rid, actor_id, actor_role):
    app = get_or_404(store.financing_applications, rid,
                     "ERR_FINANCING_APPLICATION_NOT_FOUND", "Financing application")
    # (7) state precondition
    if app["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT application can be submitted")
    order = store.sales_orders.get(app["sales_order_id"])
    # (21) term cap re-verified at submission
    if app["term_months"] > calc.term_cap_months(app["financing_type"]):
        fail("ERR_TERM_EXCEEDS_CAP", "term_months exceeds the financing type's cap")
    # (28) REAL_PROPERTY requires PRIVATE_LAND placement
    if app["financing_type"] == "REAL_PROPERTY" and (
            order is None or order["placement_type"] != "PRIVATE_LAND"):
        fail("ERR_FINANCING_TYPE_INCOMPATIBLE",
             "REAL_PROPERTY financing requires PRIVATE_LAND placement")
    app["requested_amount_cents"] = order["amount_financed_cents"] if order else 0
    app["estimated_payment_cents"] = calc.annuity_payment_cents(
        app["requested_amount_cents"], calc.rate_floor_bps(app["financing_type"]),
        app["term_months"])
    app["status"] = "SUBMITTED"
    bump(app)
    return ok(ser(app))


@bp.post("/financing-applications/<rid>/decide")
@require("LenderAgent")
def decide_application(rid, actor_id, actor_role):
    app = get_or_404(store.financing_applications, rid,
                     "ERR_FINANCING_APPLICATION_NOT_FOUND", "Financing application")
    shape = Shape(get_body())
    shape.req_enum("decision", DECISIONS)
    shape.opt_int("apr_bps", minimum=0)
    # (7) state precondition
    decision = shape.value("decision") if shape.ok("decision") else None
    if app["status"] == "SUBMITTED":
        pass  # APPROVE / CONDITIONAL / DENY all exist from SUBMITTED
    elif app["status"] == "CONDITIONALLY_APPROVED":
        if decision == "APPROVE":
            pass  # second decide after conditions satisfied
        elif decision is not None:
            fail("ERR_INVALID_STATE",
                 "A CONDITIONALLY_APPROVED application accepts only a second APPROVE")
        else:
            fail("ERR_INVALID_STATE", "Application is not decidable in its current state")
    else:
        fail("ERR_INVALID_STATE", "Application is not decidable in its current state")
    # (20) rate floor on approve-style decisions carrying an APR
    floor = calc.rate_floor_bps(app["financing_type"])
    if decision in ("APPROVE", "CONDITIONAL") and shape.ok("apr_bps") \
            and shape.value("apr_bps") is not None:
        if shape.value("apr_bps") < floor:
            fail("ERR_RATE_BELOW_FLOOR", "apr_bps below the financing type's rate floor")
    # field shape: APPROVE/CONDITIONAL need an APR unless one is already recorded
    if decision in ("APPROVE", "CONDITIONAL"):
        apr = shape.value("apr_bps") if shape.ok("apr_bps") else None
        if apr is None and app["apr_bps"] is None:
            shape._err("apr_bps", "is required for an approval decision")
    shape.raise_if_errors()

    if decision == "DENY":
        app["status"] = "DENIED"
        app["decided_by"] = actor_id
        bump(app)
        return ok(ser(app))

    if shape.ok("apr_bps") and shape.value("apr_bps") is not None:
        app["apr_bps"] = shape.value("apr_bps")
    app["decided_by"] = actor_id
    if decision == "CONDITIONAL":
        # freezes requested_amount_cents against the trade-in cascade
        app["status"] = "CONDITIONALLY_APPROVED"
        bump(app)
        return ok(ser(app))

    # APPROVE (from SUBMITTED or CONDITIONALLY_APPROVED)
    app["status"] = "APPROVED"
    app["monthly_payment_cents"] = calc.annuity_payment_cents(
        app["requested_amount_cents"] or 0, app["apr_bps"], app["term_months"])
    app["rate_lock_expires_at"] = clock.now() + timedelta(days=RATE_LOCK_DAYS)
    bump(app)
    bubble_financing_approved(app)
    return ok(ser(app))


@bp.post("/financing-applications/<rid>/fund")
@require("LenderAgent")
def fund_application(rid, actor_id, actor_role):
    app = get_or_404(store.financing_applications, rid,
                     "ERR_FINANCING_APPLICATION_NOT_FOUND", "Financing application")
    shape = Shape(get_body())
    shape.req_int("funded_amount_cents", minimum=0)
    # (7) state precondition: APPROVED only
    if app["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED application can be funded")
    order = store.sales_orders.get(app["sales_order_id"])
    # (7) unit gate: still RESERVED under this order
    unit = store.home_units.get(order["home_unit_id"]) if order else None
    if (order is None or unit is None or unit["status"] != "RESERVED"
            or unit["sales_order_id"] != order["id"]):
        fail("ERR_INVALID_STATE", "The order's unit is no longer RESERVED under this order")
    # (7) title gate: ISSUED record whose title_type matches the financing type
    required_title = ("MANUFACTURED_CERTIFICATE" if app["financing_type"] == "CHATTEL"
                      else "REAL_PROPERTY_AFFIXED")
    if find_issued_title(unit["id"], required_title) is None:
        fail("ERR_INVALID_STATE",
             "No ISSUED title record of the required type exists for the unit")
    # (24) rate lock — on breach the application transitions to EXPIRED
    if app["rate_lock_expires_at"] is not None and clock.now() > app["rate_lock_expires_at"]:
        app["status"] = "EXPIRED"
        bump(app)
        fail("ERR_RATE_LOCK_EXPIRED", "Rate lock has expired")
    # (31) funded amount must equal the requested amount exactly
    if shape.ok("funded_amount_cents"):
        if shape.value("funded_amount_cents") != app["requested_amount_cents"]:
            fail("ERR_FUNDING_AMOUNT_MISMATCH",
                 "funded_amount_cents differs from requested_amount_cents")
    shape.raise_if_errors()
    app["status"] = "FUNDED"
    bump(app)
    bubble_financing_funded(app)
    return ok(ser(app))
