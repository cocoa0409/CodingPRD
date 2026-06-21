"""Booking, AddOnLine, and CatchReport routes."""
from flask import Blueprint, request

from db import db, base_versioned, base_id_only, touch
from response import now_iso
from errors import ApiError
from middleware import require_role
from helpers import (
    get_body, require_str, require_int, opt_int, require_enum, opt_enum,
    get_pagination, paginate,
)
from response import success, list_success
from services import serializers as S
from services import calculations as calc
from services.aggregates import recompute_seats_booked
from services.lookups import (
    get_charter, get_customer, get_booking, get_add_on, get_catch_report,
)

bp = Blueprint("bookings", __name__)


def _sorted(collection):
    return sorted(collection.values(), key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
@bp.route("/bookings", methods=["POST"])
def create_booking():
    require_role({"Customer", "FleetManager"})
    body = get_body()
    # body FKs + existence (declared order: charter_id, customer_id)
    charter_id = require_str(body, "charter_id")
    customer_id = require_str(body, "customer_id")
    charter = get_charter(charter_id)
    customer = get_customer(customer_id)
    # body validation (priority 4)
    party_size = require_int(body, "party_size", minimum=1)
    expected_version = require_int(body, "expected_charter_version")
    gratuity_input_mode = opt_enum(body, "gratuity_input_mode", {"PERCENT", "FLAT"},
                                   default="PERCENT")
    gratuity_input_value = opt_int(body, "gratuity_input_value", default=0, minimum=0)

    # state (priority 5): charter must be bookable {DRAFT, SCHEDULED}
    if charter["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_CHARTER_NOT_BOOKABLE", "Charter is not bookable")

    # capacity (priority 10)
    current_booked = recompute_seats_booked(charter)
    if party_size + current_booked > charter["seats_total"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "party_size exceeds remaining seats")

    # OCC (priority 13)
    if expected_version != charter["version"]:
        raise ApiError("ERR_STALE_CHARTER_VERSION", "expected_charter_version is stale")

    seat_subtotal = calc.seat_subtotal_cents(
        charter["base_seat_price_cents"], charter["split_charter"], party_size)
    deposit_due = calc.deposit_due_cents(seat_subtotal)

    b = base_versioned()
    b.update({
        "charter_id": charter_id,
        "customer_id": customer_id,
        "party_size": party_size,
        "deposit_due_cents": deposit_due,
        "deposit_paid_cents": 0,
        "seat_subtotal_cents": seat_subtotal,
        "gratuity_cents": 0,
        "gratuity_input_mode": gratuity_input_mode,
        "gratuity_input_value": gratuity_input_value,
        "refund_cents": 0,
        "weather_waiver": False,
        "gold_reschedule_waiver_used": False,
        "reschedule_fee_total_cents": 0,
        "status": "RESERVED",
        "_seq": db.next_seq(),
    })
    db.bookings[b["id"]] = b
    # advance charter version (PRD 2.6)
    touch(charter)
    return success(S.booking_out(b), status=201)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    limit, offset = get_pagination()
    items = _sorted(db.bookings)
    for key in ("charter_id", "customer_id"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([S.booking_out(b) for b in page], limit, offset, total)


@bp.route("/bookings/<booking_id>", methods=["GET"])
def get_booking_route(booking_id):
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    b = get_booking(booking_id)
    return success(S.booking_out(b), status=200)


@bp.route("/bookings/<booking_id>/pay-deposit", methods=["POST"])
def pay_deposit(booking_id):
    require_role({"Customer", "FleetManager"})
    b = get_booking(booking_id)
    body = get_body()
    amount_cents = require_int(body, "amount_cents", minimum=0)
    # state (priority 5)
    if b["status"] != "RESERVED":
        raise ApiError("ERR_BOOKING_NOT_RESERVED", "Booking is not RESERVED")
    charter = db.charters.get(b["charter_id"])
    if charter["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_CHARTER_NOT_BOOKABLE", "Charter is not in a bookable state")
    # fiscal (priority 12)
    if amount_cents < b["deposit_due_cents"]:
        raise ApiError("ERR_DEPOSIT_UNDERPAID", "Deposit amount below deposit due")
    b["deposit_paid_cents"] = amount_cents
    b["status"] = "CONFIRMED"
    touch(b)
    return success(S.booking_out(b), status=200)


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    require_role({"Customer", "FleetManager"})
    b = get_booking(booking_id)
    # state (priority 5)
    if b["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_BOOKING_NOT_CANCELLABLE", "Booking is not cancellable")
    charter = db.charters.get(b["charter_id"])
    if charter["status"] in ("SAILED", "SETTLED"):
        raise ApiError("ERR_CHARTER_ALREADY_SAILED", "Charter has already sailed/settled")
    # refund
    now = db.now()
    lead_hours = (charter["_depart_dt"] - now).total_seconds() / 3600
    b["refund_cents"] = calc.cancellation_refund_cents(
        b["weather_waiver"], b["deposit_paid_cents"], lead_hours)
    # void addons
    for a in db.add_on_lines.values():
        if a["booking_id"] == booking_id and a["status"] in ("PENDING", "FULFILLED"):
            a["status"] = "VOIDED"
            touch(a)
    b["status"] = "CANCELLED"
    touch(b)
    # decrement seats_booked: stored field tracking handled by recompute, but
    # bump charter version per cascade? PRD: booking cancel decrements
    # seats_booked; seats_booked is computed, so nothing to store. Charter
    # version is NOT bumped by booking cancel (only create bumps it).
    return success(S.booking_out(b), status=200)


# ---------------------------------------------------------------------------
# AddOnLine
# ---------------------------------------------------------------------------
@bp.route("/add-on-lines", methods=["POST"])
def create_add_on_line():
    require_role({"Customer", "FleetManager"})
    body = get_body()
    booking_id = require_str(body, "booking_id")
    booking = get_booking(booking_id)
    addon_kind = require_enum(body, "addon_kind",
                              {"BAIT", "ROD_RENTAL", "FISH_CLEANING", "COOLER_ICE"})
    quantity = require_int(body, "quantity", minimum=1)
    unit_price, line_total = calc.addon_line_total_cents(addon_kind, quantity)
    a = base_versioned()
    a.update({
        "booking_id": booking_id,
        "addon_kind": addon_kind,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "status": "PENDING",
        "_seq": db.next_seq(),
    })
    db.add_on_lines[a["id"]] = a
    return success(S.add_on_line_out(a), status=201)


@bp.route("/add-on-lines", methods=["GET"])
def list_add_on_lines():
    require_role({"DockMaster", "FleetManager", "Captain", "Customer"})
    limit, offset = get_pagination()
    items = _sorted(db.add_on_lines)
    val = request.args.get("booking_id")
    if val is not None:
        items = [a for a in items if a.get("booking_id") == val]
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([S.add_on_line_out(a) for a in page], limit, offset, total)


@bp.route("/add-on-lines/<add_on_id>", methods=["GET"])
def get_add_on_route(add_on_id):
    require_role({"DockMaster", "FleetManager", "Customer"})
    a = get_add_on(add_on_id)
    return success(S.add_on_line_out(a), status=200)


@bp.route("/add-on-lines/<add_on_id>/fulfill", methods=["POST"])
def fulfill_add_on(add_on_id):
    require_role({"FleetManager"})
    a = get_add_on(add_on_id)
    booking = db.bookings.get(a["booking_id"])
    if booking is None or booking["status"] not in ("CONFIRMED", "SETTLED"):
        raise ApiError("ERR_ADDON_BOOKING_NOT_FULFILLABLE",
                       "Owning booking is not CONFIRMED/SETTLED")
    a["status"] = "FULFILLED"
    touch(a)
    return success(S.add_on_line_out(a), status=200)


# ---------------------------------------------------------------------------
# CatchReport (write-once: id + created_at only)
# ---------------------------------------------------------------------------
@bp.route("/catch-reports", methods=["POST"])
def create_catch_report():
    require_role({"Captain"})
    body = get_body()
    charter_id = require_str(body, "charter_id")
    charter = get_charter(charter_id)
    species = require_str(body, "species")
    fish_count = require_int(body, "fish_count", minimum=1)
    released_count = opt_int(body, "released_count", default=0, minimum=0)
    if released_count > fish_count:
        raise ApiError("ERR_INVALID_REQUEST", "released_count exceeds fish_count")
    r = base_id_only()
    r.update({
        "charter_id": charter_id,
        "species": species,
        "fish_count": fish_count,
        "released_count": released_count,
        "reported_at": now_iso(),
        "_seq": db.next_seq(),
    })
    db.catch_reports[r["id"]] = r
    return success(S.catch_report_out(r), status=201)


@bp.route("/catch-reports", methods=["GET"])
def list_catch_reports():
    require_role({"DockMaster", "FleetManager", "Captain"})
    limit, offset = get_pagination()
    items = _sorted(db.catch_reports)
    val = request.args.get("charter_id")
    if val is not None:
        items = [r for r in items if r.get("charter_id") == val]
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([S.catch_report_out(r) for r in page], limit, offset, total)


@bp.route("/catch-reports/<report_id>", methods=["GET"])
def get_catch_report_route(report_id):
    require_role({"DockMaster", "FleetManager", "Captain"})
    r = get_catch_report(report_id)
    return success(S.catch_report_out(r), status=200)
