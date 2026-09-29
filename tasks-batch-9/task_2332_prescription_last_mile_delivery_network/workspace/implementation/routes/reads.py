"""Read endpoints: detail reads and filtered, paginated collections."""

from flask import Blueprint

import middleware
import response
import serializers
import validation as v
from constants import (
    ALLOCATION_STATUSES,
    ALLOCATION_VARIANTS,
    ASSIGNMENT_STATUSES,
    ATTEMPT_OUTCOMES,
    CASE_STATUSES,
    COURIER_MODES,
    CUSTODY_STATUSES,
    EXCEPTION_TYPES,
    GRANT_STATUSES,
    ORDER_STATUSES,
    SETTLEMENT_STATUSES,
    WINDOW_STATUSES,
)
from db import db, sort_rows
from errors import api_error
from middleware import (
    ROLE_COURIER,
    ROLE_OPS,
    ROLE_PATIENT,
    ROLE_PHARMACY,
    ROLE_PLAN,
    require_roles,
)
from services import derive

bp = Blueprint("reads", __name__)


def _page(rows, project):
    limit, offset = v.pagination()
    page, total = response.paginate(sort_rows(rows), limit, offset)
    return response.collection([project(r) for r in page], limit, offset, total)


def _matches(row, field, value):
    return value is None or row.get(field) == value


# --------------------------------------------------------------------------
# grant pools
# --------------------------------------------------------------------------
@bp.get("/plan-grants/<grant_id>")
@require_roles(ROLE_PLAN, ROLE_OPS)
def read_grant(grant_id):
    grant = db.plan_grants.get(grant_id)
    if grant is not None:
        middleware.guard_plan_scope(grant["health_plan_id"])
    if grant is None:
        raise api_error("ERR_PLAN_GRANT_NOT_FOUND")
    return response.single(serializers.plan_grant(grant), 200)


@bp.get("/plan-grants")
@require_roles(ROLE_PLAN, ROLE_OPS)
def list_grants():
    health_plan_id = v.query_string("health_plan_id")
    benefit_year = v.query_int("benefit_year")
    status = v.query_enum("status", GRANT_STATUSES)

    if middleware.actor_role() == ROLE_PLAN:
        if health_plan_id is not None:
            middleware.guard_plan_scope(health_plan_id)
        health_plan_id = middleware.actor_id()

    rows = [g for g in db.plan_grants.values()
            if _matches(g, "health_plan_id", health_plan_id)
            and _matches(g, "benefit_year", benefit_year)
            and (status is None or derive.grant_status(g) == status)]
    return _page(rows, serializers.plan_grant)


# --------------------------------------------------------------------------
# capacity windows
# --------------------------------------------------------------------------
@bp.get("/delivery-windows/<window_id>")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT, ROLE_COURIER, ROLE_OPS)
def read_window(window_id):
    window = db.delivery_windows.get(window_id)
    if window is None:
        raise api_error("ERR_WINDOW_NOT_FOUND")
    return response.single(serializers.delivery_window(window), 200)


@bp.get("/delivery-windows")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT, ROLE_COURIER, ROLE_OPS)
def list_windows():
    zone_id = v.query_string("zone_id")
    courier_mode = v.query_enum("courier_mode", COURIER_MODES)
    status = v.query_enum("status", WINDOW_STATUSES)
    rows = [w for w in db.delivery_windows.values()
            if _matches(w, "zone_id", zone_id)
            and _matches(w, "courier_mode", courier_mode)
            and _matches(w, "status", status)]
    return _page(rows, serializers.delivery_window)


# --------------------------------------------------------------------------
# orders
# --------------------------------------------------------------------------
@bp.get("/pharmacy-orders/<order_id>")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT, ROLE_OPS)
def read_order(order_id):
    order = db.pharmacy_orders.get(order_id)
    middleware.guard_order_scope(order)
    if order is None:
        raise api_error("ERR_ORDER_NOT_FOUND")
    return response.single(serializers.pharmacy_order(order), 200)


@bp.get("/pharmacy-orders")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT, ROLE_PLAN, ROLE_OPS)
def list_orders():
    pharmacy_id = v.query_string("pharmacy_id")
    patient_id = v.query_string("patient_id")
    health_plan_id = v.query_string("health_plan_id")
    status = v.query_enum("status", ORDER_STATUSES)
    rows = [o for o in db.pharmacy_orders.values()
            if _matches(o, "pharmacy_id", pharmacy_id)
            and _matches(o, "patient_id", patient_id)
            and _matches(o, "health_plan_id", health_plan_id)
            and _matches(o, "status", status)]
    return _page(rows, serializers.pharmacy_order)


# --------------------------------------------------------------------------
# couriers
# --------------------------------------------------------------------------
@bp.get("/couriers/<courier_id>")
@require_roles(ROLE_COURIER, ROLE_OPS)
def read_courier(courier_id):
    middleware.guard_courier_scope(courier_id)
    courier = db.couriers.get(courier_id)
    if courier is None:
        raise api_error("ERR_COURIER_NOT_FOUND")
    return response.single(serializers.courier(courier), 200)


@bp.get("/couriers/<courier_id>/disclosures")
@require_roles(ROLE_COURIER, ROLE_OPS)
def courier_disclosures(courier_id):
    middleware.guard_courier_scope(courier_id)
    courier = db.couriers.get(courier_id)
    if courier is None:
        raise api_error("ERR_COURIER_NOT_FOUND")
    rows = [d for d in db.disclosures.values() if d["courier_id"] == courier_id]
    return _page(rows, serializers.disclosure)


# --------------------------------------------------------------------------
# deliveries
# --------------------------------------------------------------------------
@bp.get("/deliveries/<delivery_id>")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT, ROLE_PLAN, ROLE_OPS)
def read_delivery(delivery_id):
    delivery = db.deliveries.get(delivery_id)
    if delivery is not None:
        order = db.pharmacy_orders.get(delivery["order_id"])
        middleware.guard_order_scope(order)
        middleware.guard_plan_scope_on_order(order)
    if delivery is None:
        raise api_error("ERR_DELIVERY_NOT_FOUND")
    return response.single(serializers.delivery(delivery), 200)


@bp.get("/deliveries")
@require_roles(ROLE_PHARMACY, ROLE_PATIENT, ROLE_PLAN, ROLE_OPS)
def list_deliveries():
    order_id = v.query_string("order_id")
    window_id = v.query_string("window_id")
    courier_id = v.query_string("courier_id")
    reship_of = v.query_string("reship_of_delivery_id")
    custody_status = v.query_enum("custody_status", CUSTODY_STATUSES)
    settlement_status = v.query_enum("settlement_status", SETTLEMENT_STATUSES)
    rows = [d for d in db.deliveries.values()
            if _matches(d, "order_id", order_id)
            and _matches(d, "window_id", window_id)
            and _matches(d, "courier_id", courier_id)
            and _matches(d, "reship_of_delivery_id", reship_of)
            and _matches(d, "custody_status", custody_status)
            and _matches(d, "settlement_status", settlement_status)]
    return _page(rows, serializers.delivery)


# --------------------------------------------------------------------------
# assignments
# --------------------------------------------------------------------------
@bp.get("/courier-assignments/<assignment_id>")
@require_roles(ROLE_COURIER, ROLE_OPS)
def read_assignment(assignment_id):
    assignment = db.courier_assignments.get(assignment_id)
    if assignment is not None:
        middleware.guard_courier_scope(assignment["courier_id"])
    if assignment is None:
        raise api_error("ERR_ASSIGNMENT_NOT_FOUND")
    return response.single(serializers.courier_assignment(assignment), 200)


@bp.get("/courier-assignments")
@require_roles(ROLE_COURIER, ROLE_OPS)
def list_assignments():
    delivery_id = v.query_string("delivery_id")
    courier_id = v.query_string("courier_id")
    status = v.query_enum("status", ASSIGNMENT_STATUSES)
    rows = [a for a in db.courier_assignments.values()
            if _matches(a, "delivery_id", delivery_id)
            and _matches(a, "courier_id", courier_id)
            and _matches(a, "status", status)]
    return _page(rows, serializers.courier_assignment)


# --------------------------------------------------------------------------
# door-step attempts
# --------------------------------------------------------------------------
@bp.get("/delivery-attempts/<attempt_id>")
@require_roles(ROLE_COURIER, ROLE_PHARMACY, ROLE_OPS)
def read_attempt(attempt_id):
    attempt = db.delivery_attempts.get(attempt_id)
    if attempt is None:
        raise api_error("ERR_ATTEMPT_NOT_FOUND")
    return response.single(serializers.delivery_attempt(attempt), 200)


@bp.get("/delivery-attempts")
@require_roles(ROLE_COURIER, ROLE_PHARMACY, ROLE_OPS)
def list_attempts():
    delivery_id = v.query_string("delivery_id")
    courier_id = v.query_string("courier_id")
    outcome = v.query_enum("outcome", ATTEMPT_OUTCOMES)
    rows = [a for a in db.delivery_attempts.values()
            if _matches(a, "delivery_id", delivery_id)
            and _matches(a, "courier_id", courier_id)
            and _matches(a, "outcome", outcome)]
    return _page(rows, serializers.delivery_attempt)


# --------------------------------------------------------------------------
# fee allocations
# --------------------------------------------------------------------------
def _allocation_plan_id(allocation):
    delivery = db.deliveries.get(allocation["delivery_id"])
    if delivery is None:
        return None
    order = db.pharmacy_orders.get(delivery["order_id"])
    return order.get("health_plan_id") if order else None


@bp.get("/fee-allocations/<allocation_id>")
@require_roles(ROLE_PHARMACY, ROLE_PLAN, ROLE_OPS)
def read_allocation(allocation_id):
    allocation = db.fee_allocations.get(allocation_id)
    if allocation is not None:
        middleware.guard_plan_scope(_allocation_plan_id(allocation))
    if allocation is None:
        raise api_error("ERR_ALLOCATION_NOT_FOUND")
    return response.single(serializers.fee_allocation(allocation), 200)


@bp.get("/fee-allocations")
@require_roles(ROLE_PHARMACY, ROLE_PLAN, ROLE_OPS)
def list_allocations():
    delivery_id = v.query_string("delivery_id")
    plan_grant_id = v.query_string("plan_grant_id")
    variant = v.query_enum("variant", ALLOCATION_VARIANTS)
    status = v.query_enum("status", ALLOCATION_STATUSES)

    if middleware.actor_role() == ROLE_PLAN and plan_grant_id is not None:
        grant = db.plan_grants.get(plan_grant_id)
        if grant is not None:
            middleware.guard_plan_scope(grant["health_plan_id"])

    rows = [a for a in db.fee_allocations.values()
            if _matches(a, "delivery_id", delivery_id)
            and _matches(a, "plan_grant_id", plan_grant_id)
            and _matches(a, "variant", variant)
            and _matches(a, "status", status)]
    if middleware.actor_role() == ROLE_PLAN:
        rows = [a for a in rows if _allocation_plan_id(a) == middleware.actor_id()]
    return _page(rows, serializers.fee_allocation)


# --------------------------------------------------------------------------
# exception cases
# --------------------------------------------------------------------------
@bp.get("/exception-cases/<case_id>")
@require_roles(ROLE_OPS, ROLE_PHARMACY, ROLE_PLAN)
def read_case(case_id):
    case = db.exception_cases.get(case_id)
    if case is None:
        raise api_error("ERR_EXCEPTION_CASE_NOT_FOUND")
    return response.single(serializers.exception_case(case), 200)


@bp.get("/exception-cases")
@require_roles(ROLE_OPS, ROLE_PHARMACY, ROLE_PLAN)
def list_cases():
    delivery_id = v.query_string("delivery_id")
    reship_delivery_id = v.query_string("reship_delivery_id")
    exception_type = v.query_enum("exception_type", EXCEPTION_TYPES)
    status = v.query_enum("status", CASE_STATUSES)
    rows = [c for c in db.exception_cases.values()
            if _matches(c, "delivery_id", delivery_id)
            and _matches(c, "reship_delivery_id", reship_delivery_id)
            and _matches(c, "exception_type", exception_type)
            and _matches(c, "status", status)]
    return _page(rows, serializers.exception_case)
