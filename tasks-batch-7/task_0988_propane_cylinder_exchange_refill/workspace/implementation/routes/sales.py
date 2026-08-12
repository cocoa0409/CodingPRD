"""Exchange orders (swap counter) and refill tickets (refill bay)."""
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_SITE_NOT_ACTIVE, ERR_SALES_BLOCKED, ERR_NO_ACTIVE_POLICY,
    ERR_CYLINDER_CONDEMNED, ERR_CYLINDER_QUARANTINED, ERR_CYLINDER_NOT_CERTIFIED,
    ERR_NO_STOCK, ERR_INSUFFICIENT_PAYMENT, ERR_IDEMPOTENCY_CONFLICT,
    ERR_NOT_REFILLABLE, ERR_TARE_MISMATCH, ERR_OVERFILL_RISK,
    ERR_REFUND_WINDOW_CLOSED, ERR_VALIDATION, ERR_FORBIDDEN,
)
from middleware import get_actor, require_roles
from response import success_object, success_list
from services import core
from util import (
    body, req_str, opt_str, req_int, req_num, q2, round_cents, paginate,
    sorted_by_creation,
)

bp = Blueprint("sales", __name__)

ORDER_ROLES = ("SiteClerk", "PlatformAdmin", "HostSiteManager")
TICKET_ROLES = ("SiteClerk", "PlatformAdmin")


def _get_order(order_id):
    o = db.exchange_orders.get(order_id)
    if o is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Exchange order not found")
    return o


def _get_ticket(ticket_id):
    t = db.refill_tickets.get(ticket_id)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Refill ticket not found")
    return t


# ---------------------------------------------------------------------------
# Exchange orders
# ---------------------------------------------------------------------------

@bp.route("/exchange-orders", methods=["POST"])
def create_exchange_order():
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    b = body()
    site_id = req_str(b, "site_id")
    returned_id = opt_str(b, "returned_cylinder_id", None)
    idem = opt_str(b, "idempotency_key", None)

    # Stage 4: body references.
    site = db.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "site_id does not reference an existing site")
    returned = None
    if returned_id is not None:
        returned = db.cylinders.get(returned_id)
        if returned is None:
            raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "returned_cylinder_id does not reference an existing cylinder")

    # Stage 6: site must be ACTIVE for sales.
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_SITE_NOT_ACTIVE, 409, "Site is not ACTIVE")
    # Stage 7: a condemned cylinder can never be accepted as a return.
    if returned is not None and returned["cert_status"] == "CONDEMNED":
        raise ApiError(ERR_CYLINDER_CONDEMNED, 409, "Returned cylinder is CONDEMNED")
    # Stage 9: leak-blocked site refuses new sales.
    if core.sales_posture(site_id) == "SALES_BLOCKED":
        raise ApiError(ERR_SALES_BLOCKED, 409, "Site sales are blocked by a confirmed leak")
    # Stage 11: idempotent intake (unique per clerk).
    if idem is not None:
        for o in db.exchange_orders.values():
            if o["clerk_id"] == uid and o["idempotency_key"] == idem:
                if o["site_id"] == site_id and o["returned_cylinder_id"] == returned_id:
                    return success_object(core.serialize(o), 201)
                raise ApiError(ERR_IDEMPOTENCY_CONFLICT, 409, "Idempotency key reused with a different payload")
    # Stage 12: sales require a current pricing policy.
    policy = core.current_policy(site_id)
    if policy is None:
        raise ApiError(ERR_NO_ACTIVE_POLICY, 409, "No current pricing policy for the site")

    unit = policy["swap_price_cents"]
    deposit = 0 if returned_id is not None else policy["core_deposit_cents"]
    subtotal = unit + deposit
    tax = round_cents(Decimal(subtotal) * Decimal(policy["tax_rate_bps"]) / Decimal(10000))
    order = db.new_entity({
        "site_id": site_id,
        "clerk_id": uid,
        "returned_cylinder_id": returned_id,
        "issued_cylinder_id": None,
        "unit_price_cents": unit,
        "core_deposit_cents": deposit,
        "tax_cents": tax,
        "total_cents": subtotal + tax,
        "payment_cash_cents": None,
        "change_due_cents": None,
        "business_date": None,
        "sale_seq": None,
        "refunded_on": None,
        "void_reason": None,
        "idempotency_key": idem,
        "status": "DRAFT",
    })
    db.exchange_orders[order["id"]] = order
    return success_object(core.serialize(order), 201)


@bp.route("/exchange-orders/<orderId>", methods=["GET"])
def get_exchange_order(orderId):
    uid, role = get_actor()
    require_roles(role, ORDER_ROLES)
    o = _get_order(orderId)
    if role == "HostSiteManager" and o["site_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "Host-site manager may only read own site's orders")
    return success_object(core.serialize(o))


@bp.route("/exchange-orders", methods=["GET"])
def list_exchange_orders():
    uid, role = get_actor()
    require_roles(role, ORDER_ROLES)
    items = list(db.exchange_orders.values())
    if role == "HostSiteManager":
        items = [o for o in items if o["site_id"] == uid]
    for param in ("site_id", "issued_cylinder_id", "returned_cylinder_id", "status", "business_date"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[param] == v]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize(o) for o in page], total, limit, offset)


@bp.route("/exchange-orders/<orderId>/complete", methods=["POST"])
def complete_exchange_order(orderId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    o = _get_order(orderId)
    b = body()
    payment = req_int(b, "payment_cash_cents", min_v=0)
    # Stage 6.
    if o["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT order can be completed")
    # Stage 11: selector stock.
    issued = core.issue_selector(o["site_id"])
    if issued is None:
        raise ApiError(ERR_NO_STOCK, 409, "No eligible full certified fleet cylinder at the site")
    # Stage 13: payment sufficiency.
    if payment < o["total_cents"]:
        raise ApiError(ERR_INSUFFICIENT_PAYMENT, 402, "Tendered cash is below the order total")

    o["issued_cylinder_id"] = issued["id"]
    issued["current_site_id"] = None  # with the customer
    db.touch(issued)
    if o["returned_cylinder_id"] is not None:
        rc = db.cylinders[o["returned_cylinder_id"]]
        rc["owner_kind"] = "FLEET"
        rc["current_site_id"] = o["site_id"]
        rc["fill_status"] = "EMPTY"
        db.touch(rc)
    o["payment_cash_cents"] = payment
    o["change_due_cents"] = payment - o["total_cents"]
    o["business_date"] = db.current_date()
    o["sale_seq"] = db.next_sale_seq(o["site_id"])
    o["status"] = "COMPLETED"
    db.touch(o)
    core.refresh_open_sessions(o["site_id"], o["business_date"])
    return success_object(core.serialize(o))


@bp.route("/exchange-orders/<orderId>/void", methods=["POST"])
def void_exchange_order(orderId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    o = _get_order(orderId)
    if o["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT order can be voided")
    o["status"] = "VOIDED"
    o["void_reason"] = "MANUAL"
    db.touch(o)
    return success_object(core.serialize(o))


@bp.route("/exchange-orders/<orderId>/refund", methods=["POST"])
def refund_exchange_order(orderId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    o = _get_order(orderId)
    if o["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a COMPLETED order can be refunded")
    today = db.current_date()
    if o["business_date"] != today:
        raise ApiError(ERR_REFUND_WINDOW_CLOSED, 409, "Refund window closed: business date has passed")
    sess = core.find_session(o["site_id"], today)
    if sess is not None and sess["status"] not in ("OPEN", "VARIANCE_FLAGGED"):
        raise ApiError(ERR_REFUND_WINDOW_CLOSED, 409, "Refund window closed: reconciliation no longer open")
    o["refunded_on"] = today
    o["status"] = "REFUNDED"
    db.touch(o)
    issued = db.cylinders.get(o["issued_cylinder_id"])
    if issued is not None:
        issued["current_site_id"] = o["site_id"]
        issued["in_transit_run_id"] = None
        issued["fill_status"] = "QUARANTINED"
        db.touch(issued)
    core.refresh_open_sessions(o["site_id"], today)
    return success_object(core.serialize(o))


# ---------------------------------------------------------------------------
# Refill tickets
# ---------------------------------------------------------------------------

@bp.route("/refill-tickets", methods=["POST"])
def create_refill_ticket():
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    b = body()
    site_id = req_str(b, "site_id")
    cylinder_id = req_str(b, "cylinder_id")
    pre_weight = req_num(b, "pre_weight_lbs")

    site = db.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "site_id does not reference an existing site")
    cyl = db.cylinders.get(cylinder_id)
    if cyl is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "cylinder_id does not reference an existing cylinder")
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_SITE_NOT_ACTIVE, 409, "Site is not ACTIVE")
    if core.sales_posture(site_id) == "SALES_BLOCKED":
        raise ApiError(ERR_SALES_BLOCKED, 409, "Site sales are blocked by a confirmed leak")
    if cyl["owner_kind"] != "CUSTOMER":
        raise ApiError(ERR_NOT_REFILLABLE, 409, "Refills are CUSTOMER cylinders only")
    if core.current_policy(site_id) is None:
        raise ApiError(ERR_NO_ACTIVE_POLICY, 409, "No current pricing policy for the site")

    max_fill = q2(cyl["water_capacity_lbs"] * core.PROPANE_FILL_FACTOR)
    ticket = db.new_entity({
        "site_id": site_id,
        "cylinder_id": cylinder_id,
        "clerk_id": uid,
        "pre_weight_lbs": pre_weight,
        "measured_tare_lbs": None,
        "post_weight_lbs": None,
        "propane_lbs": None,
        "max_fill_lbs": max_fill,
        "tier1_cents_per_lb": None,
        "tier2_cents_per_lb": None,
        "tier1_max_lbs": None,
        "propane_charge_cents": None,
        "hazmat_fee_cents": None,
        "total_cents": None,
        "payment_cash_cents": None,
        "change_due_cents": None,
        "business_date": None,
        "sale_seq": None,
        "status": "OPEN",
    })
    db.refill_tickets[ticket["id"]] = ticket
    return success_object(core.serialize(ticket), 201)


@bp.route("/refill-tickets/<ticketId>", methods=["GET"])
def get_refill_ticket(ticketId):
    uid, role = get_actor()
    require_roles(role, TICKET_ROLES)
    return success_object(core.serialize(_get_ticket(ticketId)))


@bp.route("/refill-tickets", methods=["GET"])
def list_refill_tickets():
    uid, role = get_actor()
    require_roles(role, TICKET_ROLES)
    items = list(db.refill_tickets.values())
    for param in ("site_id", "cylinder_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t[param] == v]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize(t) for t in page], total, limit, offset)


@bp.route("/refill-tickets/<ticketId>/weigh", methods=["POST"])
def weigh_refill_ticket(ticketId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    t = _get_ticket(ticketId)
    b = body()
    measured = req_num(b, "measured_tare_lbs")
    if t["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN ticket can be weighed")
    cyl = db.cylinders[t["cylinder_id"]]
    if abs(measured - cyl["tare_weight_lbs"]) > core.TARE_TOLERANCE_LBS:
        raise ApiError(ERR_TARE_MISMATCH, 422, "Measured tare deviates from stamped tare beyond tolerance")
    if t["pre_weight_lbs"] < measured:
        raise ApiError(ERR_TARE_MISMATCH, 422, "pre_weight_lbs is below the measured tare")
    t["measured_tare_lbs"] = measured
    t["status"] = "WEIGHED"
    db.touch(t)
    return success_object(core.serialize(t))


@bp.route("/refill-tickets/<ticketId>/reweigh", methods=["POST"])
def reweigh_refill_ticket(ticketId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    t = _get_ticket(ticketId)
    b = body()
    pre = req_num(b, "pre_weight_lbs")
    if t["status"] != "WEIGHED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a WEIGHED ticket can be reweighed")
    t["pre_weight_lbs"] = pre
    t["measured_tare_lbs"] = None
    t["status"] = "OPEN"
    db.touch(t)
    return success_object(core.serialize(t))


@bp.route("/refill-tickets/<ticketId>/fill", methods=["POST"])
def fill_refill_ticket(ticketId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    t = _get_ticket(ticketId)
    b = body()
    post = req_num(b, "post_weight_lbs")
    if t["status"] != "WEIGHED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a WEIGHED ticket can be filled")
    cyl = db.cylinders[t["cylinder_id"]]
    # Stage 7: condemned / quarantined safety checks.
    if cyl["cert_status"] == "CONDEMNED":
        raise ApiError(ERR_CYLINDER_CONDEMNED, 409, "Cylinder is CONDEMNED")
    if cyl["fill_status"] == "QUARANTINED":
        raise ApiError(ERR_CYLINDER_QUARANTINED, 409, "Cylinder is QUARANTINED")
    # Stage 8: certification currency.
    if cyl["cert_status"] != "CERTIFIED":
        raise ApiError(ERR_CYLINDER_NOT_CERTIFIED, 409, "Cylinder certification is not current")
    # Stage 11: overfill (equality at the ceiling is allowed).
    propane = q2(post - t["pre_weight_lbs"])
    if propane > t["max_fill_lbs"]:
        raise ApiError(ERR_OVERFILL_RISK, 422, "propane_lbs exceeds max_fill_lbs")
    # Stage 12: tier rates pinned from the site's current policy.
    policy = core.current_policy(t["site_id"])
    if policy is None:
        raise ApiError(ERR_NO_ACTIVE_POLICY, 409, "No current pricing policy for the site")

    t1_max = policy["refill_tier1_max_lbs"]
    t1_lbs = min(propane, t1_max)
    t2_lbs = propane - t1_lbs
    t1_cents = round_cents(t1_lbs * Decimal(policy["refill_tier1_cents_per_lb"]))
    t2_cents = round_cents(t2_lbs * Decimal(policy["refill_tier2_cents_per_lb"]))
    site = db.sites[t["site_id"]]
    hazmat = 0 if site["promo_waives_hazmat"] else site["hazmat_fee_cents"]

    t["post_weight_lbs"] = post
    t["propane_lbs"] = propane
    t["tier1_cents_per_lb"] = policy["refill_tier1_cents_per_lb"]
    t["tier2_cents_per_lb"] = policy["refill_tier2_cents_per_lb"]
    t["tier1_max_lbs"] = t1_max
    t["propane_charge_cents"] = t1_cents + t2_cents
    t["hazmat_fee_cents"] = hazmat
    t["total_cents"] = t1_cents + t2_cents + hazmat
    t["status"] = "FILLED"
    db.touch(t)
    return success_object(core.serialize(t))


@bp.route("/refill-tickets/<ticketId>/close", methods=["POST"])
def close_refill_ticket(ticketId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    t = _get_ticket(ticketId)
    b = body()
    payment = req_int(b, "payment_cash_cents", min_v=0)
    if t["status"] != "FILLED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a FILLED ticket can be closed")
    if payment < t["total_cents"]:
        raise ApiError(ERR_INSUFFICIENT_PAYMENT, 402, "Tendered cash is below the ticket total")
    cyl = db.cylinders[t["cylinder_id"]]
    cyl["fill_status"] = "FULL"
    db.touch(cyl)
    t["payment_cash_cents"] = payment
    t["change_due_cents"] = payment - t["total_cents"]
    t["business_date"] = db.current_date()
    t["sale_seq"] = db.next_sale_seq(t["site_id"])
    t["status"] = "CLOSED"
    db.touch(t)
    core.refresh_open_sessions(t["site_id"], t["business_date"])
    return success_object(core.serialize(t))


@bp.route("/refill-tickets/<ticketId>/void", methods=["POST"])
def void_refill_ticket(ticketId):
    uid, role = get_actor()
    require_roles(role, ("SiteClerk",))
    t = _get_ticket(ticketId)
    if t["status"] not in ("OPEN", "WEIGHED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN or WEIGHED ticket can be voided")
    t["status"] = "VOIDED"
    db.touch(t)
    return success_object(core.serialize(t))
