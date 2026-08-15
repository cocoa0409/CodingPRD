"""AbstractOrder endpoints: placement, read, scope amendment (OCC),
cancellation cascade, and delivery cascade."""

import db
from errors import (
    ApiError,
    ERR_ORDER_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_SCOPE_LOCKED,
    ERR_STALE_VERSION,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    TERMINAL_ORDER_STATES,
    compute_scope_start,
    compute_provisional,
    compute_initial_accrued,
    compute_liability_cap,
    compute_due_at,
    recompute_order_fees,
    order_view,
    assignments_of_order,
    reports_of_order,
    retrievals_of_order,
)
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
    rhu,
    dt_of_stored,
)

bp = make_blueprint("orders")

_CREATE_SPEC = {
    "client_ref": {"type": "string", "required": True},
    "property_address": {"type": "string", "required": True},
    "county": {"type": "string", "required": True},
    "state_code": {"type": "state_code", "required": True},
    "legal_description_text": {"type": "string", "required": True},
    "search_period_years": {"type": "integer", "required": True, "min": 1, "max": 60},
    "effective_date": {"type": "date", "required": True},
    "sla_tier": {"type": "enum", "values": {"STANDARD", "RUSH"}},
    "liability_tier": {"type": "enum", "values": {"STANDARD", "EXTENDED"}},
}

_PATCH_SPEC = {
    "expected_abstract_order_version": {"type": "integer", "required": True},
    "search_period_years": {"type": "integer", "min": 1, "max": 60},
    "effective_date": {"type": "date"},
    "sla_tier": {"type": "enum", "values": {"STANDARD", "RUSH"}},
    "liability_tier": {"type": "enum", "values": {"STANDARD", "EXTENDED"}},
    "legal_description_text": {"type": "string"},
}

_CANCEL_SPEC = {
    "reason": {"type": "string"},
}


@bp.post("/abstract-orders")
def create_order():
    uid, role = authenticate(["Client"])
    body = body_json()
    # Attribute-ownership (priority 2): client_ref must equal X-User-ID.
    client_ref = body.get("client_ref")
    if isinstance(client_ref, str) and client_ref != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "client_ref must equal X-User-ID")
    check_shape(body, _CREATE_SPEC)
    if body["client_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "client_ref must equal X-User-ID")

    sla_tier = body.get("sla_tier") or "STANDARD"
    liability_tier = body.get("liability_tier") or "STANDARD"
    received_dt = db.now()
    received_at = db.fmt_ts_sec(received_dt)
    due_at = db.fmt_ts_sec(compute_due_at(received_dt, sla_tier))
    accrued = compute_initial_accrued(sla_tier)
    order = db.new_entity("orders", {
        "client_ref": body["client_ref"],
        "property_address": body["property_address"],
        "county": body["county"],
        "state_code": body["state_code"],
        "legal_description_text": body["legal_description_text"],
        "search_period_years": body["search_period_years"],
        "effective_date": body["effective_date"],
        "sla_tier": sla_tier,
        "liability_tier": liability_tier,
        "scope_start_date": compute_scope_start(body["effective_date"], body["search_period_years"]),
        "received_at": received_at,
        "due_at": due_at,
        "delivered_at": None,
        "status": "RECEIVED",
        "provisional_fee_cents": compute_provisional(sla_tier),
        "accrued_fees_cents": accrued,
        "final_fee_cents": None,
        "late_credit_cents": 0,
        "billed_fee_cents": None,
        "liability_cap_cents": compute_liability_cap(liability_tier, accrued),
    })
    return success_obj(order_view(order), 201)


@bp.get("/abstract-orders/<oid>")
def get_order(oid):
    uid, role = authenticate(ALL_ROLES)
    order = require_fk("orders", oid, ERR_ORDER_NOT_FOUND, "order")
    if role == "Client" and order["client_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "clients may only read their own orders")
    return success_obj(order_view(order), 200)


@bp.get("/abstract-orders")
def list_orders():
    uid, role = authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("orders")
    if role == "Client":
        items = [o for o in items if o["client_ref"] == uid]
    items = apply_filters(items, ["client_ref", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([order_view(o) for o in page], limit, offset, total, has_more)


@bp.patch("/abstract-orders/<oid>")
def patch_order(oid):
    uid, role = authenticate(["OperationsManager"])
    body = body_json()
    check_shape(body, _PATCH_SPEC)
    order = require_fk("orders", oid, ERR_ORDER_NOT_FOUND, "order")
    # Priority 19 (scope lock) fires before priority 21 (OCC staleness).
    if order["status"] not in ("RECEIVED", "SEARCH_IN_PROGRESS"):
        raise ApiError(ERR_SCOPE_LOCKED, 409, "order scope is locked beyond SEARCH_IN_PROGRESS")
    if body["expected_abstract_order_version"] != order["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_abstract_order_version does not match current version")

    scope_changed = False
    if "search_period_years" in body and body["search_period_years"] is not None:
        if body["search_period_years"] != order["search_period_years"]:
            scope_changed = True
        order["search_period_years"] = body["search_period_years"]
    if "effective_date" in body and body["effective_date"] is not None:
        if body["effective_date"] != order["effective_date"]:
            scope_changed = True
        order["effective_date"] = body["effective_date"]
    if "sla_tier" in body and body["sla_tier"] is not None:
        order["sla_tier"] = body["sla_tier"]
    if "liability_tier" in body and body["liability_tier"] is not None:
        order["liability_tier"] = body["liability_tier"]
    if "legal_description_text" in body and body["legal_description_text"] is not None:
        order["legal_description_text"] = body["legal_description_text"]

    # Re-derive everything the amended terms touch. in_scope is derived at
    # read time, so every non-VOID recorded document reflects the new window.
    order["scope_start_date"] = compute_scope_start(order["effective_date"], order["search_period_years"])
    order["due_at"] = db.fmt_ts_sec(compute_due_at(dt_of_stored(order["received_at"]), order["sla_tier"]))
    order["provisional_fee_cents"] = compute_provisional(order["sla_tier"])
    recompute_order_fees(order)
    db.touch(order)
    return success_obj(order_view(order), 200)


@bp.post("/abstract-orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = authenticate(["Client", "OperationsManager"])
    body = body_json()
    check_shape(body, _CANCEL_SPEC)
    order = require_fk("orders", oid, ERR_ORDER_NOT_FOUND, "order")
    if role == "Client" and order["client_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "clients may only cancel their own orders")
    if order["status"] in TERMINAL_ORDER_STATES:
        raise ApiError(ERR_INVALID_STATE, 409, "a terminal order cannot be cancelled")

    # Downward cascade (PRD section 2.9).
    for a in assignments_of_order(order["id"]):
        if a["status"] in ("IN_PROGRESS", "SUBMITTED", "RETURNED_FOR_CORRECTION"):
            a["status"] = "CANCELLED"
            db.touch(a)
    for r in reports_of_order(order["id"]):
        if r["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUIRED"):
            r["status"] = "CANCELLED"
            db.touch(r)
    for r in retrievals_of_order(order["id"]):
        if r["status"] == "FEE_POSTED":
            r["status"] = "FEE_REVERSED"
            db.touch(r)
    order["status"] = "CANCELLED"
    recompute_order_fees(order)
    db.touch(order)
    return success_obj(order_view(order), 200)


@bp.post("/abstract-orders/<oid>/deliver")
def deliver_order(oid):
    uid, role = authenticate(["OperationsManager"])
    body_json()
    order = require_fk("orders", oid, ERR_ORDER_NOT_FOUND, "order")
    if order["status"] != "READY_FOR_DELIVERY":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not READY_FOR_DELIVERY")

    delivered_dt = db.now()
    order["delivered_at"] = db.fmt_ts_sec(delivered_dt)

    # Cascade link 1: APPROVED report -> DELIVERED.
    for r in reports_of_order(order["id"]):
        if r["status"] == "APPROVED":
            r["status"] = "DELIVERED"
            db.touch(r)
    # Cascade link 2: every FEE_POSTED retrieval -> INVOICED.
    for r in retrievals_of_order(order["id"]):
        if r["status"] == "FEE_POSTED":
            r["status"] = "INVOICED"
            db.touch(r)
    # Cascade link 3: closing computations. final := accrued as it stands.
    recompute_order_fees(order)
    order["final_fee_cents"] = order["accrued_fees_cents"]
    # Late credit: strictly later than due_at; exactly AT due_at is on time.
    if delivered_dt > dt_of_stored(order["due_at"]):
        order["late_credit_cents"] = rhu(order["final_fee_cents"] * 10, 100)
    else:
        order["late_credit_cents"] = 0
    order["billed_fee_cents"] = order["final_fee_cents"] - order["late_credit_cents"]
    order["liability_cap_cents"] = compute_liability_cap(order["liability_tier"], order["final_fee_cents"])
    order["status"] = "DELIVERED"
    db.touch(order)
    return success_obj(order_view(order), 200)
