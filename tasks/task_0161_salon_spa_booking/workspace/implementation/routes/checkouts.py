"""Checkout routes: create (complete + settle), fetch, list, void (PRD §3.5-§3.6).

Checkout is the central ledger event. Creating it completes the appointment and
atomically fans out: service-revenue recognition, stylist/salon split, tip
distribution, retail line pricing + inventory decrement, package redemption,
and deposit consumption. All preconditions are checked BEFORE any mutation so
the whole operation is atomic (PRD §3.5).
"""
from flask import Blueprint, request

import db
from errors import err
from lookups import get_or_404
from response import success
from util import stamp_create, touch, public
import validate as v
from calculations import (
    service_revenue_recognized,
    stylist_service_split,
    tip_distribution,
    retail_line_total,
    active_membership_for_client,
)
from cascades import (
    redeem_package_session,
    restore_package_session,
    apply_no_show_cascade,
)
from routes.common import auth, json_body, list_response

bp = Blueprint("checkouts", __name__)

NON_TERMINAL = {"BOOKED", "CONFIRMED"}


def _has_settled_checkout(appointment_id):
    for c in db.checkouts.values():
        if c["appointment_id"] == appointment_id and c["status"] == "SETTLED":
            return True
    return False


@bp.post("/checkouts")
def create_checkout():
    auth(("SalonOwner", "FrontDesk"))
    body = json_body()
    v.require_object(body)

    appointment_id = v.req_str(body, "appointment_id")
    appointment = get_or_404(db.appointments, appointment_id)
    salon = db.salons[appointment["salon_id"]]

    # --- already-checked-out takes precedence over generic state (PRD §3.5) ---
    # A second checkout for an appointment that already has a settled checkout
    # is specifically ERR_ALREADY_CHECKED_OUT, whereas any *other* wrong state
    # (e.g. CANCELLED / NO_SHOW, which never have a settled checkout) is the
    # generic ERR_INVALID_STATE.
    if _has_settled_checkout(appointment["id"]):
        raise err("ERR_ALREADY_CHECKED_OUT", "appointment already has a settled checkout")

    # --- state eligibility (priority 4 -> ERR_INVALID_STATE) ---
    # current_utc must be >= start, and appointment must be BOOKED/CONFIRMED.
    from util import parse_dt
    current_utc = parse_dt(salon["current_utc"])
    start_utc = parse_dt(appointment["start_utc"])
    if appointment["status"] not in NON_TERMINAL:
        raise err("ERR_INVALID_STATE", "appointment not in a checkoutable state")
    if not (current_utc >= start_utc):
        raise err("ERR_INVALID_STATE", "cannot checkout before the slot has begun")

    tip_cents = v.opt_int(body, "tip_cents", default=0, minimum=0)

    retail_lines = body.get("retail_lines")
    if retail_lines is None:
        retail_lines = []
    if not isinstance(retail_lines, list):
        raise err("ERR_INVALID_REQUEST", "retail_lines must be a list")

    # Parse + existence-check retail lines and pre-validate stock.
    client = db.clients[appointment["client_id"]]
    membership = active_membership_for_client(client["id"])
    retail_disc_pct = None
    if membership is not None:
        plan = db.membership_plans[membership["plan_id"]]
        retail_disc_pct = plan["retail_discount_pct"]

    parsed_lines = []
    running_on_hand = {}  # sku_id -> remaining available within this request
    for raw in retail_lines:
        if not isinstance(raw, dict):
            raise err("ERR_INVALID_REQUEST", "each retail line must be an object")
        product_sku_id = v.req_str(raw, "product_sku_id")
        quantity = v.req_int(raw, "quantity", minimum=1)
        sku = db.product_skus.get(product_sku_id)
        if sku is None:
            raise err("ERR_NOT_FOUND", "product sku not found")
        # Cumulative oversell check within the request (priority 12).
        avail = running_on_hand.get(sku["id"], sku["qty_on_hand"])
        if quantity > avail:
            raise err("ERR_INSUFFICIENT_STOCK", "insufficient stock for retail line")
        running_on_hand[sku["id"]] = avail - quantity
        line_total = retail_line_total(sku["unit_price_cents"], quantity, retail_disc_pct)
        parsed_lines.append((sku, quantity, line_total))

    # --- all preconditions passed: commit atomically ---

    # Service revenue + split.
    service_revenue = service_revenue_recognized(appointment)
    stylist = db.stylists[appointment["stylist_id"]]
    stylist_earning, salon_earning = stylist_service_split(stylist, service_revenue)

    # Tip distribution.
    stylist_tip = tip_distribution(salon, stylist, tip_cents)

    # Retail revenue (per-line rounded, then summed).
    retail_revenue = sum(line_total for (_sku, _qty, line_total) in parsed_lines)

    checkout = {
        "appointment_id": appointment["id"],
        "tip_cents": tip_cents,
        "service_revenue_cents": service_revenue,
        "retail_revenue_cents": retail_revenue,
        "stylist_service_earning_cents": stylist_earning,
        "salon_service_earning_cents": salon_earning,
        "stylist_tip_cents": stylist_tip,
        "status": "SETTLED",
    }
    stamp_create(checkout)
    db.checkouts[checkout["id"]] = checkout

    # Create ProductSale records + decrement inventory.
    for sku, quantity, line_total in parsed_lines:
        sale = {
            "checkout_id": checkout["id"],
            "product_sku_id": sku["id"],
            "quantity": quantity,
            "line_total_cents": line_total,
        }
        stamp_create(sale, with_version=False)  # ProductSale: id + created_at only
        db.product_sales[sale["id"]] = sale
        sku["qty_on_hand"] -= quantity
        touch(sku)

    # Redeem package session if any. Mark the appointment so a later void can
    # restore exactly the session this checkout consumed (PRD §3.5/§3.6).
    if appointment.get("package_purchase_id"):
        redeem_package_session(appointment.get("package_purchase_id"))
        appointment["_session_redeemed"] = True

    # Complete the appointment (deposit is consumed, not refunded).
    appointment["status"] = "COMPLETED"
    touch(appointment)

    return success(public(checkout), status=201)


@bp.get("/checkouts/<checkout_id>")
def get_checkout(checkout_id):
    auth(("SalonOwner", "FrontDesk", "Stylist"))
    checkout = get_or_404(db.checkouts, checkout_id)
    return success(public(checkout), status=200)


@bp.get("/checkouts")
def list_checkouts():
    auth(("SalonOwner", "FrontDesk", "Stylist"))
    appointment_id = request.args.get("appointment_id")
    status = request.args.get("status")

    def pred(c):
        if appointment_id is not None and c["appointment_id"] != appointment_id:
            return False
        if status is not None and c["status"] != status:
            return False
        return True

    page, meta = list_response(db.checkouts, pred)
    return success(page, status=200, response_type="array", pagination=meta)


@bp.post("/checkouts/<checkout_id>/void")
def void_checkout(checkout_id):
    auth(("SalonOwner",))
    checkout = get_or_404(db.checkouts, checkout_id)
    if checkout["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "only a SETTLED checkout may be voided")

    checkout["status"] = "VOIDED"

    # Restore inventory for each child ProductSale (units conserved).
    for sale in db.product_sales.values():
        if sale["checkout_id"] != checkout["id"]:
            continue
        sku = db.product_skus.get(sale["product_sku_id"])
        if sku is not None:
            sku["qty_on_hand"] += sale["quantity"]
            touch(sku)

    appointment = db.appointments[checkout["appointment_id"]]

    # Restore package session if this checkout had redeemed one (sessions
    # conserved, PRD §3.6). Clear the flag so the reclassified NO_SHOW below
    # does not double-restore.
    if appointment.get("_session_redeemed"):
        restore_package_session(appointment.get("package_purchase_id"))
        appointment["_session_redeemed"] = False

    # Reclassify the visit as a missed one: appointment -> NO_SHOW + full no-show
    # cascade (strike, conditional suspend, deposit forfeit/refund) (PRD §3.6).
    appointment["status"] = "NO_SHOW"
    client = db.clients[appointment["client_id"]]
    salon = db.salons[appointment["salon_id"]]
    apply_no_show_cascade(appointment, salon, client)
    touch(appointment)

    touch(checkout)
    return success(public(checkout), status=200)


@bp.get("/checkouts/<checkout_id>/product-sales")
def list_checkout_sales(checkout_id):
    auth(("SalonOwner", "FrontDesk", "Stylist"))
    get_or_404(db.checkouts, checkout_id)  # existence

    def pred(s):
        return s["checkout_id"] == checkout_id

    page, meta = list_response(db.product_sales, pred)
    return success(page, status=200, response_type="array", pagination=meta)
