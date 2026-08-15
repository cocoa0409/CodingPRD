"""Order and OrderLine endpoints (PRD §3.5)."""

from flask import Blueprint, request

import db
import services.domain as domain
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list

bp = Blueprint("orders", __name__)

READ_ROLES = (
    "TenantAdmin", "ComplianceOfficer", "Auditor",
    "OrderClerk", "FulfillmentClerk", "BillingClerk",
)


@bp.route("/tenants/<tid>/customers/<cid>/orders", methods=["POST"])
def create_order(tid, cid):
    require_role("OrderClerk")
    tenant = domain.get_tenant(tid)
    cust = domain.get_scoped("customers", cid, tenant["id"])
    body = request.get_json(silent=True) or {}
    # Priority 4: body FKs resolve within the tenant.
    domain.require_reason(tenant["id"], body.get("exemption_reason_code"))
    link_id = body.get("drop_ship_link_id")
    if link_id is not None:
        link = db.stores["drop_ship_links"].get(link_id)
        if not link or link["tenant_id"] != tenant["id"]:
            raise ApiError(
                "ERR_CROSS_TENANT_REFERENCE",
                "drop_ship_link_id does not resolve to a record of this tenant",
                404,
            )
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "customer_id": cust["id"],
        "order_ref": body.get("order_ref"),
        "ship_to_state": body.get("ship_to_state"),
        "exemption_reason_code": body.get("exemption_reason_code"),
        "subtotal_cents": 0,
        "exempt_amount_cents": 0,
        "covered_amount_cents": 0,
        "uncovered_amount_cents": 0,
        "applied_tax_engine_code": None,
        "drop_ship_link_id": link_id,
        "status": "DRAFT",
    })
    db.stores["orders"][rec["id"]] = rec
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/orders", methods=["GET"])
def list_orders(tid):
    require_role("TenantAdmin", "ComplianceOfficer", "Auditor", "OrderClerk")
    tenant = domain.get_tenant(tid)
    items = [o for o in db.stores["orders"].values() if o["tenant_id"] == tenant["id"]]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda o: o["_seq"])
    return ok_list([db.pub(o) for o in items])


@bp.route("/tenants/<tid>/orders/<oid>", methods=["GET"])
def get_order(tid, oid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    order = domain.get_scoped("orders", oid, tenant["id"])
    return ok(db.pub(order))


@bp.route("/tenants/<tid>/orders/<oid>/lines", methods=["POST"])
def add_line(tid, oid):
    require_role("OrderClerk")
    tenant = domain.get_tenant(tid)
    order = domain.get_scoped("orders", oid, tenant["id"])
    body = request.get_json(silent=True) or {}
    quantity = body.get("quantity") or 0
    unit_price = body.get("unit_price_cents") or 0
    rec = db.make_record({
        "tenant_id": tenant["id"],
        "order_id": order["id"],
        "sku": body.get("sku"),
        "quantity": quantity,
        "unit_price_cents": unit_price,
        # Exact integer product of quantity and unit price (PRD §2.7).
        "extended_cents": int(quantity) * int(unit_price),
        "is_exempt_claimed": bool(body.get("is_exempt_claimed")),
    })
    db.stores["order_lines"][rec["id"]] = rec
    order["subtotal_cents"] = sum(l["extended_cents"] for l in domain.order_lines_of(order["id"]))
    bump(order)
    return created(db.pub(rec))


@bp.route("/tenants/<tid>/orders/<oid>/lines", methods=["GET"])
def list_lines(tid, oid):
    require_role(*READ_ROLES)
    tenant = domain.get_tenant(tid)
    order = domain.get_scoped("orders", oid, tenant["id"])
    items = domain.order_lines_of(order["id"])
    return ok_list([db.pub(l) for l in items])


@bp.route("/tenants/<tid>/orders/<oid>/submit", methods=["POST"])
def submit_order(tid, oid):
    require_role("OrderClerk")
    tenant = domain.get_tenant(tid)
    order = domain.get_scoped("orders", oid, tenant["id"])
    cust = domain.get_scoped("customers", order["customer_id"], tenant["id"])
    # Priority 5: state check.
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT order can be submitted", 409)
    # Priority 15: at least one line (precedes the onboarding check).
    if not domain.order_lines_of(order["id"]):
        raise ApiError("ERR_ORDER_EMPTY", "Order has no lines", 422)
    # Priority 16: onboarding complete.
    if cust["onboarding_completed_at"] is None:
        raise ApiError("ERR_ONBOARDING_INCOMPLETE", "Customer onboarding is not complete", 409)
    # Coverage computation.
    domain.recompute_order_amounts(order, tenant)
    reason = domain.find_reason(tenant["id"], order["exemption_reason_code"])
    # requires_certificate must be true, or the exempt amount must be zero.
    if not (reason and reason["requires_certificate"]) and order["exempt_amount_cents"] != 0:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Claimed exemption reason does not require a certificate and the exempt amount is non-zero",
            409,
        )
    # The order passes through SUBMITTED momentarily and lands per coverage.
    if order["covered_amount_cents"] < order["exempt_amount_cents"]:
        order["status"] = "HELD_FOR_CERT"
    else:
        order["status"] = "READY_TO_SHIP"
    bump(order)
    if order["status"] == "HELD_FOR_CERT":
        domain.recompute_blocked_exposure(cust)
        bump(cust)
        domain.recompute_open_exposure(tenant)
        bump(tenant)
    return ok(db.pub(order))


@bp.route("/tenants/<tid>/orders/<oid>/ship", methods=["POST"])
def ship_order(tid, oid):
    require_role("FulfillmentClerk")
    tenant = domain.get_tenant(tid)
    order = domain.get_scoped("orders", oid, tenant["id"])
    if order["status"] != "READY_TO_SHIP":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a READY_TO_SHIP order can be shipped", 409)
    cust = domain.get_scoped("customers", order["customer_id"], tenant["id"])
    # Priority 19: block at equality — exactly $100,000.00 of blocked
    # exposure cannot ship; $99,999.99 can.
    if cust["blocked_exposure_cents"] >= domain.BLOCK_THRESHOLD_CENTS:
        raise ApiError(
            "ERR_BLOCKED_EXPOSURE_AT_LIMIT",
            "Customer blocked_exposure_cents is at or over the shipping threshold",
            409,
        )
    order["status"] = "SHIPPED"
    bump(order)
    return ok(db.pub(order))


@bp.route("/tenants/<tid>/orders/<oid>/invoice", methods=["POST"])
def invoice_order(tid, oid):
    require_role("BillingClerk")
    tenant = domain.get_tenant(tid)
    order = domain.get_scoped("orders", oid, tenant["id"])
    if order["status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a SHIPPED order can be invoiced", 409)
    reason = domain.find_reason(tenant["id"], order["exemption_reason_code"])
    order["applied_tax_engine_code"] = reason["tax_engine_code"] if reason else None
    order["status"] = "INVOICED"
    bump(order)
    return ok(db.pub(order))


@bp.route("/tenants/<tid>/orders/<oid>/cancel", methods=["POST"])
def cancel_order(tid, oid):
    require_role("OrderClerk")
    tenant = domain.get_tenant(tid)
    order = domain.get_scoped("orders", oid, tenant["id"])
    if order["status"] not in ("DRAFT", "HELD_FOR_CERT"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT or HELD_FOR_CERT order can be cancelled", 409)
    was_held = order["status"] == "HELD_FOR_CERT"
    order["status"] = "CANCELLED"
    bump(order)
    if was_held:
        cust = domain.get_scoped("customers", order["customer_id"], tenant["id"])
        domain.recompute_blocked_exposure(cust)
        bump(cust)
        domain.recompute_open_exposure(tenant)
        bump(tenant)
    return ok(db.pub(order))
