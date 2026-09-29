"""Bookings: two independent state dimensions plus refund pass-through (PRD 3.8)."""
from flask import Blueprint

import auth
import calc
import clock
import response
import store
import validate
from errors import ApiError
from store import db, touch

from routes import common

bp = Blueprint("bookings", __name__)

PAYMENT_STATUSES = ("AUTHORIZED", "CAPTURED", "REFUNDED_PARTIAL", "REFUNDED_FULL", "CHARGEBACK")
FULFILLMENT_STATUSES = ("RESERVED", "CONFIRMED", "CANCELLED", "COMPLETED")


def _package_money(package):
    """Package sales conserve charged_total = payable + margin + taxes; margin absorbs the discount."""
    taxes = 0
    payable = 0
    for component in db["components"].values():
        if component["package_id"] != package["id"]:
            continue
        offer = db["offers"].get(component["offer_id"])
        if offer is None:
            continue
        taxes += int(offer["taxes_fees_cents"])
        payable += int(offer["supplier_payable_cents"])
    total = int(package["package_total_cents"])
    return {
        "charged_total_cents": total,
        "taxes_fees_cents": taxes,
        "supplier_payable_cents": payable,
        "marketplace_margin_cents": total - taxes - payable,
    }


@bp.post("/bookings")
def create_booking():
    actor = auth.authenticate(("BookingAgent",))
    data = validate.body()
    raw_offer = data.get("offer_id")
    raw_package = data.get("package_id")
    if isinstance(raw_offer, str) and raw_offer:
        common.find("offers", raw_offer)
    if isinstance(raw_package, str) and raw_package:
        common.find("packages", raw_package)
    offer_id = validate.id_opt(data, "offer_id")
    package_id = validate.id_opt(data, "package_id")
    traveler_reference = validate.str_req(data, "traveler_reference")
    quoted_total_cents = validate.int_req(data, "quoted_total_cents")
    payment_token = validate.str_req(data, "payment_token")

    offer = db["offers"].get(offer_id) if offer_id else None
    package = db["packages"].get(package_id) if package_id else None
    hotel_leg = None
    if offer is not None and package is None and offer["status"] != "LIVE":
        raise ApiError("ERR_OFFER_NOT_LIVE")
    if package is not None and offer is None and package["status"] != "PUBLISHED":
        raise ApiError("ERR_PACKAGE_NOT_PUBLISHED")
    if (offer is None) == (package is None):
        raise ApiError("ERR_BOOKING_TARGET_INVALID")

    if offer is not None:
        money = {
            "charged_total_cents": int(offer["display_total_cents"]),
            "taxes_fees_cents": int(offer["taxes_fees_cents"]),
            "marketplace_margin_cents": int(offer["marketplace_margin_cents"]),
            "supplier_payable_cents": int(offer["supplier_payable_cents"]),
        }
        offers = [offer]
        travel_date = offer["travel_date"]
        governing = offer
    else:
        money = _package_money(package)
        offers = []
        governing = None
        for component in sorted(db["components"].values(), key=lambda r: r["_seq"]):
            if component["package_id"] != package["id"]:
                continue
            leg = db["offers"].get(component["offer_id"])
            if leg is None:
                continue
            offers.append(leg)
            if governing is None:
                governing = leg
            if component["component_type"] == "HOTEL" and hotel_leg is None:
                hotel_leg = leg
        travel_date = package["travel_date"]
        if hotel_leg is not None:
            governing = hotel_leg
    if quoted_total_cents != money["charged_total_cents"]:
        raise ApiError("ERR_PRICE_CHANGED")
    for leg in offers:
        if int(leg["allotment_remaining"]) < 1:
            raise ApiError("ERR_ALLOTMENT_EXHAUSTED")

    fields = {
        "offer_id": offer["id"] if offer else None,
        "package_id": package["id"] if package else None,
        "traveler_reference": traveler_reference,
        "quoted_total_cents": quoted_total_cents,
        "payment_token": payment_token,
        "refunded_cents": 0,
        "last_refund_clawback_cents": 0,
        "last_refund_supplier_debit_cents": 0,
        "last_refund_tax_cents": 0,
        "payment_status": "AUTHORIZED",
        "fulfillment_status": "RESERVED",
        "collection_model": governing["pricing_model"] if governing else None,
        "arrival_at": clock.iso(clock.date_at_hour(clock.parse_date(travel_date),
                                                  calc.ARRIVAL_HOUR_UTC)),
        "cancellation_refund_pct": None,
        "cancelled_at": None,
        "supplier_confirmation_code": None,
        "booked_by_user_id": actor.user_id,
    }
    fields.update(money)
    booking = store.new_row("bookings", fields)
    for leg in offers:
        leg["allotment_remaining"] = int(leg["allotment_remaining"]) - 1
        leg["allotment_held"] = int(leg["allotment_held"]) + 1
        touch(leg)
    return response.obj(booking, 201)


@bp.get("/bookings/<booking_id>")
def read_booking(booking_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("bookings", booking_id), 200)


@bp.get("/bookings")
def list_bookings():
    auth.authenticate(auth.ALL_ROLES)
    offer_id = validate.filter_str("offer_id")
    package_id = validate.filter_str("package_id")
    payment_status = validate.filter_enum("payment_status", PAYMENT_STATUSES)
    fulfillment_status = validate.filter_enum("fulfillment_status", FULFILLMENT_STATUSES)
    rows = []
    for row in db["bookings"].values():
        if offer_id is not None and row["offer_id"] != offer_id:
            continue
        if package_id is not None and row["package_id"] != package_id:
            continue
        if payment_status is not None and row["payment_status"] != payment_status:
            continue
        if fulfillment_status is not None and row["fulfillment_status"] != fulfillment_status:
            continue
        rows.append(row)
    return common.paged(rows)


@bp.post("/bookings/<booking_id>/capture")
def capture(booking_id):
    auth.authenticate(("BookingAgent",))
    booking = common.find("bookings", booking_id)
    data = validate.body()
    validate.str_opt(data, "note")
    if booking["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_BOOKING_ALREADY_CANCELLED")
    if booking["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_PAYMENT_NOT_AUTHORIZED")
    booking["payment_status"] = "CAPTURED"
    touch(booking)
    return response.obj(booking, 200)


@bp.post("/bookings/<booking_id>/confirm")
def confirm(booking_id):
    actor = auth.authenticate(("SupplierUser",))
    booking = common.find("bookings", booking_id)
    auth.require_supplier_scope_any(actor, common.booking_supplier_ids(booking))
    data = validate.body()
    code = validate.str_req(data, "supplier_confirmation_code")
    if booking["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_BOOKING_NOT_RESERVED")
    if booking["payment_status"] not in ("AUTHORIZED", "CAPTURED"):
        raise ApiError("ERR_PAYMENT_NOT_AUTHORIZED")
    booking["fulfillment_status"] = "CONFIRMED"
    booking["supplier_confirmation_code"] = code
    touch(booking)
    for leg in common.booking_components(booking):
        leg["allotment_held"] = int(leg["allotment_held"]) - 1
        leg["allotment_sold"] = int(leg["allotment_sold"]) + 1
        touch(leg)
    return response.obj(booking, 200)


@bp.post("/bookings/<booking_id>/cancel")
def cancel(booking_id):
    auth.authenticate(("BookingAgent",))
    booking = common.find("bookings", booking_id)
    data = validate.body()
    validate.str_req(data, "cancellation_reason")
    was = booking["fulfillment_status"]
    if was not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_BOOKING_ALREADY_CANCELLED")
    if was == "CONFIRMED" and booking["payment_status"] == "CHARGEBACK":
        raise ApiError("ERR_BOOKING_ALREADY_CANCELLED")

    offer = common.booking_governing_offer(booking)
    plan = common.offer_plan(offer) if offer else None
    hours = calc.hours_to_arrival(booking["arrival_at"], clock.now())
    policy = plan["cancellation_policy_code"] if plan else "NON_REF"
    cutoff = plan["free_cancel_cutoff_hours"] if plan else 0
    pct = calc.refund_pct_for(policy, hours, cutoff)
    parts = calc.refund_breakdown(booking, pct)

    booking["fulfillment_status"] = "CANCELLED"
    booking["cancelled_at"] = clock.now_iso()
    booking["cancellation_refund_pct"] = calc.num(pct)
    booking["refunded_cents"] = int(booking["refunded_cents"]) + parts["refund_cents"]
    booking["marketplace_margin_cents"] -= parts["clawback_cents"]
    booking["supplier_payable_cents"] -= parts["supplier_debit_cents"]
    booking["taxes_fees_cents"] -= parts["tax_refund_cents"]
    booking["last_refund_clawback_cents"] = parts["clawback_cents"]
    booking["last_refund_supplier_debit_cents"] = parts["supplier_debit_cents"]
    booking["last_refund_tax_cents"] = parts["tax_refund_cents"]
    if pct == 1:
        booking["payment_status"] = "REFUNDED_FULL"
    elif pct > 0:
        booking["payment_status"] = "REFUNDED_PARTIAL"
    touch(booking)
    for leg in common.booking_components(booking):
        if was == "RESERVED":
            leg["allotment_held"] = int(leg["allotment_held"]) - 1
        else:
            leg["allotment_sold"] = int(leg["allotment_sold"]) - 1
        leg["allotment_remaining"] = int(leg["allotment_remaining"]) + 1
        touch(leg)
    return response.obj(booking, 200)


@bp.post("/bookings/<booking_id>/complete")
def complete(booking_id):
    actor = auth.authenticate(("SupplierUser",))
    booking = common.find("bookings", booking_id)
    auth.require_supplier_scope_any(actor, common.booking_supplier_ids(booking))
    data = validate.body()
    validate.str_opt(data, "note")
    if booking["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_BOOKING_NOT_CONFIRMED")
    arrival = clock.parse_instant(booking["arrival_at"])
    if arrival is not None and clock.now() < arrival:
        raise ApiError("ERR_BOOKING_NOT_CONFIRMED",
                       "The logical clock has not yet reached arrival_at.")
    if booking["payment_status"] not in ("CAPTURED", "CHARGEBACK", "REFUNDED_PARTIAL"):
        raise ApiError("ERR_PAYMENT_NOT_CAPTURED")
    booking["fulfillment_status"] = "COMPLETED"
    touch(booking)
    return response.obj(booking, 200)
