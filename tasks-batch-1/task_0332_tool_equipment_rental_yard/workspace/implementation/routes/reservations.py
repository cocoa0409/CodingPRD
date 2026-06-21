"""Reservation endpoints (PRD §3.4, §3.5)."""
from flask import Blueprint, request

import errors
from db import DB, LOCK
from middleware import require_auth
from services.common import (
    new_record, require_body, req_enum, req_date, opt_bool, touch,
    billed_days, clock_date_str, parse_date, parse_datetime, get_or_404,
)
from services import calculations as calc
from services import booking
from services.ledger import post_entry, recompute_balance
from services.rentals import open_agreement
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("reservations", __name__)

FULFILLMENT = {"PICKUP", "DELIVERY"}


@bp.post("/rental-yard/reservations")
def create_reservation():
    user_id, role = require_auth({"RentalAgent", "Contractor"})
    body = require_body(get_json_body())

    # --- Ownership (PRD §2.1, priority 3): Contractor must act on own account.
    contractor_account_id = body.get("contractor_account_id")
    if role == "Contractor":
        if not isinstance(contractor_account_id, str) or contractor_account_id != user_id:
            raise errors.not_account_owner()

    with LOCK:
        # --- Existence (PRD §2.5, priority 4), left to right:
        # contractor_account_id, catalog_item_id, equipment_unit_id.
        if not isinstance(contractor_account_id, str):
            raise errors.invalid_request("Field 'contractor_account_id' must be a string.")
        account = DB.contractor_accounts.get(contractor_account_id)
        if account is None:
            raise errors.not_found()

        catalog_item_id = body.get("catalog_item_id")
        if not isinstance(catalog_item_id, str):
            raise errors.invalid_request("Field 'catalog_item_id' must be a string.")
        catalog_item = DB.catalog_items.get(catalog_item_id)
        if catalog_item is None:
            raise errors.not_found()

        pinned_unit = None
        equipment_unit_id = body.get("equipment_unit_id")
        if equipment_unit_id is not None:
            if not isinstance(equipment_unit_id, str):
                raise errors.invalid_request("Field 'equipment_unit_id' must be a string.")
            pinned_unit = DB.equipment_units.get(equipment_unit_id)
            if pinned_unit is None:
                raise errors.not_found()

        # --- Body shape (PRD §3.4, priority 5).
        fulfillment_method = req_enum(body, "fulfillment_method", FULFILLMENT)
        rental_start_date = req_date(body, "rental_start_date")
        rental_end_date = req_date(body, "rental_end_date")
        if parse_date(rental_end_date) < parse_date(rental_start_date):
            raise errors.invalid_request("rental_end_date must be >= rental_start_date.")
        damage_waiver_opted = opt_bool(body, "damage_waiver_opted", False)

        rate_card = DB.rate_cards.get(catalog_item["rate_card_id"])

        # --- Unit availability (PRD §3.4, priority 8): a chosen unit must not be
        # OUT_OF_SERVICE. Only applies when a unit is pinned; selector policy only
        # ever picks AVAILABLE units.
        if pinned_unit is not None:
            if pinned_unit["availability_state"] == "OUT_OF_SERVICE":
                raise errors.unit_not_available(
                    "The chosen unit is OUT_OF_SERVICE and cannot accept new bookings.")

        # --- Fulfillment compatibility (PRD §3.4, priority 9): PICKUP rejected
        # when the catalog item requires_delivery.
        if fulfillment_method == "PICKUP" and catalog_item.get("requires_delivery", False):
            raise errors.delivery_required()

        # --- Temporal overlap (PRD §3.4, priority 10) and unit selection.
        if pinned_unit is not None:
            if booking.unit_has_overlapping_booking(
                    pinned_unit["id"], rental_start_date, rental_end_date):
                raise errors.unit_double_booked()
            chosen_unit = pinned_unit
        else:
            chosen_unit = booking.select_unit(
                catalog_item_id, rental_start_date, rental_end_date)
            if chosen_unit is None:
                raise errors.no_unit_available()

        # --- Past-date check (PRD §3.4, priority 11).
        if parse_date(rental_start_date) < parse_date(clock_date_str()):
            raise errors.start_in_past()

        # --- Account standing (PRD §3.4, priority 12).
        if account["account_status"] != "ACTIVE":
            raise errors.account_suspended()

        # --- Compute estimate figures (PRD §3.4).
        planned_days = billed_days(rental_start_date, rental_end_date)
        estimated_rental = calc.rental_charge_cents(planned_days, rate_card)
        delivery_fee = calc.delivery_fee_cents(fulfillment_method, catalog_item["category"])
        est_waiver = calc.estimated_waiver_cents(damage_waiver_opted, planned_days, rate_card)
        estimated_total = estimated_rental + est_waiver + delivery_fee

        # --- Credit projection (PRD §3.4, priority 13), before the deposit hold.
        current_balance = recompute_balance(contractor_account_id)
        would_be = current_balance + rate_card["deposit_cents"] + estimated_total
        if would_be > account["credit_limit_cents"]:
            raise errors.credit_limit_exceeded()

        # --- Commit: create the reservation.
        rec = new_record({
            "contractor_account_id": contractor_account_id,
            "equipment_unit_id": chosen_unit["id"],
            "catalog_item_id": catalog_item_id,
            "fulfillment_method": fulfillment_method,
            "rental_start_date": rental_start_date,
            "rental_end_date": rental_end_date,
            "damage_waiver_opted": damage_waiver_opted,
            "reservation_state": "CONFIRMED",
            "estimated_rental_cents": estimated_rental,
            "estimated_total_cents": estimated_total,
            "delivery_fee_cents": delivery_fee,
            "delivery_truck_id": None,
            "delivery_window_start": None,
            "delivery_window_end": None,
        })
        DB.reservations[rec["id"]] = rec

        # Post DEPOSIT_HOLD and recompute balance (PRD §3.4).
        post_entry(contractor_account_id, "DEPOSIT_HOLD",
                   rate_card["deposit_cents"], rental_agreement_id=None)
        recompute_balance(contractor_account_id)

    return single_response(rec, 201)


@bp.get("/rental-yard/reservations/<rid>")
def get_reservation(rid):
    rec = get_or_404(DB.reservations, rid)
    return single_response(rec)


@bp.get("/rental-yard/reservations")
def list_reservations():
    filters = {
        "equipment_unit_id": request.args.get("equipment_unit_id"),
        "catalog_item_id": request.args.get("catalog_item_id"),
        "contractor_account_id": request.args.get("contractor_account_id"),
        "delivery_truck_id": request.args.get("delivery_truck_id"),
        "reservation_state": request.args.get("reservation_state"),
    }
    items = DB.reservations.values()
    for field, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    return list_response(items)


@bp.post("/rental-yard/reservations/<rid>/cancel")
def cancel_reservation(rid):
    user_id, role = require_auth({"RentalAgent", "Contractor"})
    with LOCK:
        rec = get_or_404(DB.reservations, rid)
        # Ownership for Contractor (PRD §2.1).
        if role == "Contractor" and rec["contractor_account_id"] != user_id:
            raise errors.not_account_owner()
        # Only a CONFIRMED reservation may be cancelled (PRD §3.4).
        if rec["reservation_state"] != "CONFIRMED":
            raise errors.invalid_state()
        rec["reservation_state"] = "CANCELLED"
        touch(rec)
        # Reverse the deposit hold (PRD §3.4). The deposit amount comes from the
        # rate card via the catalog item.
        catalog_item = DB.catalog_items.get(rec["catalog_item_id"])
        rate_card = DB.rate_cards.get(catalog_item["rate_card_id"])
        post_entry(rec["contractor_account_id"], "DEPOSIT_REFUND",
                   -rate_card["deposit_cents"], rental_agreement_id=None)
        recompute_balance(rec["contractor_account_id"])
    return single_response(rec)


@bp.post("/rental-yard/reservations/<rid>/dispatch")
def dispatch_reservation(rid):
    require_auth({"RentalAgent"})
    body = get_json_body()
    with LOCK:
        rec = get_or_404(DB.reservations, rid)

        # State precondition (PRD §3.5, priority 7).
        if rec["reservation_state"] != "CONFIRMED":
            raise errors.invalid_state()

        # Fulfillment: dispatch requires DELIVERY (PRD §3.5, priority 14).
        if rec["fulfillment_method"] != "DELIVERY":
            raise errors.wrong_fulfillment("Dispatch requires a DELIVERY reservation.")

        # Existence of the truck (PRD §2.5).
        delivery_truck_id = body.get("delivery_truck_id")
        if not isinstance(delivery_truck_id, str):
            raise errors.invalid_request("Field 'delivery_truck_id' must be a string.")
        truck = DB.delivery_trucks.get(delivery_truck_id)
        if truck is None:
            raise errors.not_found()

        # Window fields present and well-formed (PRD §3.5).
        window_start = body.get("delivery_window_start")
        window_end = body.get("delivery_window_end")
        if not isinstance(window_start, str) or not isinstance(window_end, str):
            raise errors.invalid_request("delivery_window_start/end must be ISO 8601 strings.")
        try:
            ws = parse_datetime(window_start)
            we = parse_datetime(window_end)
        except ValueError:
            raise errors.invalid_request("delivery_window_start/end must be valid ISO 8601.")
        # end must be strictly after start (PRD §3.5, priority 15).
        if not (we > ws):
            raise errors.invalid_request("delivery_window_end must be after delivery_window_start.")

        # Unit must be AVAILABLE right now (PRD §3.5, priority 8).
        unit = DB.equipment_units.get(rec["equipment_unit_id"])
        if unit["availability_state"] != "AVAILABLE":
            raise errors.unit_not_available()

        # Clock date must be on/after rental_start_date (PRD §3.5).
        if parse_date(clock_date_str()) < parse_date(rec["rental_start_date"]):
            raise errors.invalid_state(
                "The yard clock current date is before rental_start_date.")

        # Truck window collision, buffer-padded half-open (PRD §3.5, priority 16).
        if booking.truck_window_collides(truck, window_start, window_end,
                                         truck["buffer_minutes"],
                                         exclude_reservation_id=rec["id"]):
            raise errors.truck_double_booked()

        # Commit: assign window, advance reservation, open agreement.
        rec["delivery_truck_id"] = delivery_truck_id
        rec["delivery_window_start"] = window_start
        rec["delivery_window_end"] = window_end
        rec["reservation_state"] = "DISPATCHED_DELIVERY"
        touch(rec)

        catalog_item = DB.catalog_items.get(rec["catalog_item_id"])
        rate_card = DB.rate_cards.get(catalog_item["rate_card_id"])
        open_agreement(rec, unit, catalog_item, rate_card)
    return single_response(rec)


@bp.post("/rental-yard/reservations/<rid>/pickup")
def pickup_reservation(rid):
    require_auth({"RentalAgent"})
    with LOCK:
        rec = get_or_404(DB.reservations, rid)

        # State precondition (PRD §3.5, priority 7).
        if rec["reservation_state"] != "CONFIRMED":
            raise errors.invalid_state()

        # Fulfillment: pickup requires PICKUP (PRD §3.5, priority 14).
        if rec["fulfillment_method"] != "PICKUP":
            raise errors.wrong_fulfillment("Pickup requires a PICKUP reservation.")

        catalog_item = DB.catalog_items.get(rec["catalog_item_id"])
        # Delivery-only item cannot be picked up (PRD §3.5, priority 9).
        if catalog_item.get("requires_delivery", False):
            raise errors.delivery_required()

        # Unit must be AVAILABLE right now (PRD §3.5, priority 8).
        unit = DB.equipment_units.get(rec["equipment_unit_id"])
        if unit["availability_state"] != "AVAILABLE":
            raise errors.unit_not_available()

        # Clock date must be on/after rental_start_date (PRD §3.5).
        if parse_date(clock_date_str()) < parse_date(rec["rental_start_date"]):
            raise errors.invalid_state(
                "The yard clock current date is before rental_start_date.")

        # Commit: advance reservation, open agreement.
        rec["reservation_state"] = "PICKED_UP"
        touch(rec)
        rate_card = DB.rate_cards.get(catalog_item["rate_card_id"])
        open_agreement(rec, unit, catalog_item, rate_card)
    return single_response(rec)
