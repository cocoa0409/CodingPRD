"""GownOrder endpoints — parallel state axes, lifecycle, cancel cascade (PRD §3.3, §3.4)."""
from flask import Blueprint, request

import db
import common
import errors
import services
import calculations
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")

bp = Blueprint("gown_orders", __name__)


@bp.route("/gown-orders", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def create_order():
    body = common.get_body()
    gown_style_code = common.as_str(body, "gown_style_code")
    ordered_size = common.as_int(body, "ordered_size", minimum=0)
    base_price_cents = common.as_int(body, "base_price_cents", minimum=0)
    standard_lead_days = common.as_int(body, "standard_lead_days", minimum=1)
    is_rush = common.as_bool(body, "is_rush", required=False, default=False)
    bridal_party_id = body.get("bridal_party_id")
    origin_appointment_id = body.get("origin_appointment_id")

    # Existence resolution for body FKs in declaration order (party, then appointment).
    party = None
    if bridal_party_id is not None:
        party = services.get_party(bridal_party_id)
    if origin_appointment_id is not None:
        services.get_appointment(origin_appointment_id)

    # Membership-state guard: a LOCKED party rejects new membership (priority 9).
    if party is not None and party["coordination_status"] != "FORMING":
        errors.raise_error(errors.ERR_PARTY_NOT_FORMING, "Party is not FORMING")

    quoted = calculations.quoted_total_cents(base_price_cents, ordered_size, is_rush)
    obj = {
        "id": db.new_id(),
        "bridal_party_id": bridal_party_id,
        "origin_appointment_id": origin_appointment_id,
        "gown_style_code": gown_style_code,
        "ordered_size": ordered_size,
        "base_price_cents": base_price_cents,
        "standard_lead_days": standard_lead_days,
        "is_rush": is_rush,
        "quoted_total_cents": quoted,
        "final_total_cents": None,
        "required_by_date": None,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
    }
    db.stamp_create(obj)
    db.gown_orders[obj["id"]] = obj

    if bridal_party_id is not None:
        services.recompute_member_order_count(bridal_party_id)

    return success(common.serialize(obj), status=201)


@bp.route("/gown-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_orders():
    limit, offset = common.paginate(request.args)
    rows = list(db.gown_orders.values())
    bridal_party_id = request.args.get("bridal_party_id")
    origin_appointment_id = request.args.get("origin_appointment_id")
    if bridal_party_id is not None:
        rows = [o for o in rows if o.get("bridal_party_id") == bridal_party_id]
    if origin_appointment_id is not None:
        rows = [o for o in rows if o.get("origin_appointment_id") == origin_appointment_id]
    window, meta = common.page_slice(rows, limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/gown-orders/<oid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_order(oid):
    obj = services.get_order(oid)
    return success(common.serialize(obj))


@bp.route("/gown-orders/<oid>/submit", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def submit_order(oid):
    obj = services.get_order(oid)
    if obj["fulfillment_status"] != "DRAFT":
        errors.raise_error(errors.ERR_ORDER_NOT_DRAFT, "Order is not DRAFT")
    # Cross-entity precondition: a non-cancelled PaymentPlan must exist.
    has_plan = any(
        p["gown_order_id"] == oid and p["status"] != "CANCELLED"
        for p in db.payment_plans.values()
    )
    if not has_plan:
        errors.raise_error(errors.ERR_PAYMENT_PLAN_REQUIRED, "A non-cancelled payment plan is required")
    obj["fulfillment_status"] = "ORDERED"
    eff_days = calculations.effective_lead_days(obj["standard_lead_days"], obj["is_rush"])
    obj["required_by_date"] = common.add_days_iso(obj["created_at"], eff_days)
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/gown-orders/<oid>/receive", methods=["POST"])
@require_roles("ShopManager")
def receive_order(oid):
    obj = services.get_order(oid)
    if obj["fulfillment_status"] != "ORDERED":
        errors.raise_error(errors.ERR_ORDER_NOT_ORDERED, "Order is not ORDERED")
    obj["fulfillment_status"] = "RECEIVED"
    active_prices = services.active_accessory_prices(oid)
    obj["final_total_cents"] = calculations.final_total_cents(
        obj["base_price_cents"], obj["ordered_size"], obj["is_rush"], active_prices
    )
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/gown-orders/<oid>/mark-ready", methods=["POST"])
@require_roles("Seamstress", "ShopManager")
def mark_ready(oid):
    obj = services.get_order(oid)
    if obj["fulfillment_status"] != "RECEIVED":
        errors.raise_error(errors.ERR_ORDER_NOT_RECEIVED, "Order is not RECEIVED")
    # Every alteration job must be COMPLETED or CANCELLED.
    outstanding = any(
        j["gown_order_id"] == oid and j["status"] not in ("COMPLETED", "CANCELLED")
        for j in db.alteration_jobs.values()
    )
    if outstanding:
        errors.raise_error(errors.ERR_ALTERATIONS_OUTSTANDING, "Alterations outstanding")
    obj["fulfillment_status"] = "READY"
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/gown-orders/<oid>/pickup", methods=["POST"])
@require_roles("BridalConsultant", "ShopManager")
def pickup_order(oid):
    obj = services.get_order(oid)
    body = common.get_body()
    # Request-shape: final_steam_done must be present and a boolean (priority 4).
    final_steam_done = common.as_bool(body, "final_steam_done")
    # State guard (priority 5).
    if obj["fulfillment_status"] != "READY":
        errors.raise_error(errors.ERR_ORDER_NOT_READY, "Order is not READY")
    # Fiscal: paid in full (priority 12).
    if obj["payment_status"] != "PAID_IN_FULL":
        errors.raise_error(errors.ERR_BALANCE_OUTSTANDING, "Balance outstanding")
    # Final steam guard (priority 13).
    if final_steam_done is not True:
        errors.raise_error(errors.ERR_FINAL_STEAM_REQUIRED, "Final steam required")
    obj["fulfillment_status"] = "PICKED_UP"
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/gown-orders/<oid>/cancel", methods=["POST"])
@require_roles("ShopManager")
def cancel_order(oid):
    obj = services.get_order(oid)
    if obj["fulfillment_status"] in ("PICKED_UP", "CANCELLED"):
        errors.raise_error(errors.ERR_ORDER_NOT_CANCELLABLE, "Order is not cancellable")

    obj["fulfillment_status"] = "CANCELLED"
    db.touch(obj)

    # Cascade hop 1: alteration jobs not terminal -> CANCELLED.
    for job in db.alteration_jobs.values():
        if job["gown_order_id"] != oid:
            continue
        if job["status"] in ("COMPLETED", "CANCELLED"):
            continue
        job["status"] = "CANCELLED"
        db.touch(job)
        # Cascade hop 2: any HELD booking on the job's fitting_room_id -> RELEASED.
        room_id = job.get("fitting_room_id")
        if room_id is not None:
            for b in db.fitting_room_bookings.values():
                if (
                    b["fitting_room_id"] == room_id
                    and b["status"] == "HELD"
                ):
                    b["status"] = "RELEASED"
                    db.touch(b)  # hop 3: room capacity freed

    # PaymentPlan with amount_paid_cents == 0 and not already CANCELLED -> CANCELLED.
    for plan in db.payment_plans.values():
        if plan["gown_order_id"] != oid:
            continue
        if plan["status"] == "CANCELLED":
            continue
        amount_paid, _ = services.compute_plan_ledger(plan)
        if amount_paid == 0:
            plan["status"] = "CANCELLED"
            services.refresh_plan_ledger(plan)
            db.touch(plan)

    # Recompute the linked party's member tally (derived-field reconciliation).
    if obj.get("bridal_party_id") is not None:
        services.recompute_member_order_count(obj["bridal_party_id"])

    return success(common.serialize(obj))
