"""AdmissionOrder, AdmissionTicket, Donation routes."""
from flask import Blueprint, request

import db
import serializers as S
from errors import invalid_request, not_owner
from listing import list_response
from middleware import get_identity, require_role
from response import ok, created
from routes.helpers import resolve, ensure_owns_order
from services import order_svc, pricing
import validate as V

bp = Blueprint("orders", __name__)

VALID_TICKET_TYPE = {"MEMBER", "NON_MEMBER", "GUEST", "RECIPROCAL"}


# --------------------------- AdmissionOrder ---------------------------

@bp.post("/admission-orders")
def create_order():
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    body = V.get_body()
    # Left-to-right existence: patron_id, slot_id, then optional fks.
    patron_id = V.require_str(body, "patron_id")
    patron = resolve(db.patrons, patron_id)
    slot_id = V.require_str(body, "slot_id")
    slot = resolve(db.timed_entry_slots, slot_id)
    membership_id = V.opt_str(body, "membership_id", None)
    membership = None
    if membership_id is not None:
        membership = resolve(db.memberships, membership_id)
    exhibit_session_id = V.opt_str(body, "exhibit_session_id", None)
    if exhibit_session_id is not None:
        resolve(db.exhibit_sessions, exhibit_session_id)
    if role == "Patron" and patron_id != user_id:
        raise not_owner("Patron may only create their own order")
    donation_cents = V.opt_int_nonneg(body, "donation_cents", 0)
    rec = {
        "patron_id": patron["id"],
        "slot_id": slot["id"],
        "membership_id": membership["id"] if membership else None,
        "exhibit_session_id": exhibit_session_id,
        "party_size": 0,
        "status": "DRAFT",
        "donation_cents": donation_cents,
        "quoted_total_cents": donation_cents,
        "final_total_cents": None,
    }
    db.stamp_create(rec)
    db.admission_orders[rec["id"]] = rec
    return created(S.admission_order(db.public(rec)))


@bp.get("/admission-orders/<rid>")
def read_order(rid):
    user_id, role = get_identity()
    rec = resolve(db.admission_orders, rid)
    ensure_owns_order(user_id, role, rec)
    return ok(S.admission_order(db.public(rec)))


@bp.get("/admission-orders")
def list_orders():
    _, role = get_identity()
    require_role(role, {"BoxOffice", "MembershipAdmin"})
    filters = {
        "patron_id": request.args.get("patron_id"),
        "slot_id": request.args.get("slot_id"),
        "membership_id": request.args.get("membership_id"),
        "exhibit_session_id": request.args.get("exhibit_session_id"),
        "status": request.args.get("status"),
    }
    return list_response(db.admission_orders, lambda r: S.admission_order(db.public(r)), filters)


@bp.post("/admission-orders/<rid>/tickets")
def add_ticket(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    order = resolve(db.admission_orders, rid)
    ensure_owns_order(user_id, role, order)
    body = V.get_body()
    ticket_type = V.require_enum(body, "ticket_type", VALID_TICKET_TYPE)
    person_name = V.require_str(body, "person_name")
    reciprocal_partner_id = V.opt_str(body, "reciprocal_partner_id", None)
    if reciprocal_partner_id is not None:
        resolve(db.reciprocal_partners, reciprocal_partner_id)
    # Tickets are only added while the order is DRAFT.
    if order["status"] != "DRAFT":
        from errors import invalid_state
        raise invalid_state("Tickets may only be added to a DRAFT order")
    rec = {
        "order_id": order["id"],
        "ticket_type": ticket_type,
        "person_name": person_name,
        "guest_pass_id": None,
        "reciprocal_partner_id": reciprocal_partner_id,
        "price_cents": None,
        "state": "ACTIVE",
    }
    db.stamp_create(rec)
    db.admission_tickets[rec["id"]] = rec
    # party_size += 1, recompute provisional quote.
    order_svc.recompute_party_size(order)
    order["quoted_total_cents"] = pricing.compute_provisional(order)
    db.touch(order)
    return created(S.admission_ticket(db.public(rec)))


@bp.patch("/admission-orders/<rid>")
def update_order(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    order = resolve(db.admission_orders, rid)
    ensure_owns_order(user_id, role, order)
    body = V.get_body()
    donation_cents = V.require_int_nonneg(body, "donation_cents")
    if order["status"] != "DRAFT":
        from errors import invalid_state
        raise invalid_state("Only a DRAFT order's donation may be edited")
    order["donation_cents"] = donation_cents
    order["quoted_total_cents"] = pricing.compute_provisional(order)
    db.touch(order)
    return ok(S.admission_order(db.public(order)))


@bp.post("/admission-orders/<rid>/confirm")
def confirm_order(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    order = resolve(db.admission_orders, rid)
    ensure_owns_order(user_id, role, order)
    order_svc.confirm(order)
    return ok(S.admission_order(db.public(order)))


@bp.post("/admission-orders/<rid>/check-in")
def check_in_order(rid):
    _, role = get_identity()
    require_role(role, {"BoxOffice", "GateScanner"})
    order = resolve(db.admission_orders, rid)
    order_svc.check_in(order)
    return ok(S.admission_order(db.public(order)))


@bp.post("/admission-orders/<rid>/cancel")
def cancel_order(rid):
    user_id, role = get_identity()
    require_role(role, {"Patron", "BoxOffice"})
    order = resolve(db.admission_orders, rid)
    ensure_owns_order(user_id, role, order)
    order_svc.cancel(order)
    return ok(S.admission_order(db.public(order)))


@bp.post("/admission-orders/<rid>/refund")
def refund_order(rid):
    _, role = get_identity()
    require_role(role, {"BoxOffice"})
    order = resolve(db.admission_orders, rid)
    order_svc.refund(order)
    return ok(S.admission_order(db.public(order)))


# --------------------------- AdmissionTicket ---------------------------

@bp.get("/admission-tickets/<rid>")
def read_ticket(rid):
    get_identity()
    rec = resolve(db.admission_tickets, rid)
    return ok(S.admission_ticket(db.public(rec)))


@bp.get("/admission-tickets")
def list_tickets():
    get_identity()
    filters = {
        "order_id": request.args.get("order_id"),
        "guest_pass_id": request.args.get("guest_pass_id"),
        "reciprocal_partner_id": request.args.get("reciprocal_partner_id"),
    }
    return list_response(db.admission_tickets, lambda r: S.admission_ticket(db.public(r)), filters)


# --------------------------- Donation ---------------------------

@bp.get("/donations/<rid>")
def read_donation(rid):
    _, role = get_identity()
    require_role(role, {"BoxOffice", "MembershipAdmin"})
    rec = resolve(db.donations, rid)
    return ok(S.donation(db.public(rec)))


@bp.get("/donations")
def list_donations():
    _, role = get_identity()
    require_role(role, {"BoxOffice", "MembershipAdmin"})
    filters = {
        "order_id": request.args.get("order_id"),
        "membership_id": request.args.get("membership_id"),
    }
    return list_response(db.donations, lambda r: S.donation(db.public(r)), filters)
