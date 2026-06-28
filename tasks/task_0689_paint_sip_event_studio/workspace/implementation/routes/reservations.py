"""Reservation endpoints + lifecycle (PRD §3.4–§3.6, §3.9).

Two independent state dimensions on the same row: booking status (HELD,
CONFIRMED, CHECKED_IN, CANCELLED, NO_SHOW) and payment_status (UNPAID, PAID,
REFUNDED).
"""
from flask import Blueprint, g, request

import db
import errors
import helpers
import middleware
import models
from clock import clock
from errors import err
from response import object_response, array_response
from services import calc, core

bp = Blueprint("reservations", __name__)

BOOKING_MODES = {"PUBLIC", "PRIVATE"}

# event_type -> allowed booking_mode (PRD §3.4).
PUBLIC_EVENT_TYPES = {"PUBLIC_CLASS", "FUNDRAISER"}
PRIVATE_EVENT_TYPES = {"PRIVATE_PARTY", "CORPORATE"}


def _owns_or_raise(reservation):
    """A Customer may act only on reservations they own."""
    if middleware.is_customer() and g.user_id != reservation["customer_id"]:
        raise err(errors.ERR_FORBIDDEN, "Customer does not own this reservation")


@bp.post("/studio-ops/reservations")
def create_reservation():
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()

    # Priority 2 (ownership) precedes body well-formedness (PRD §2.6): a Customer
    # may only book with their own customer_id. Read the raw value early so this
    # 403 surfaces ahead of any ERR_VALIDATION on the rest of the body.
    if middleware.is_customer():
        raw_customer_id = body.get("customer_id")
        if g.user_id != raw_customer_id:
            raise err(errors.ERR_FORBIDDEN, "Customer must book with own customer_id")

    # Priority 4: well-formedness.
    event_id = helpers.as_str(body, "event_id")
    customer_id = helpers.as_str(body, "customer_id")
    booking_mode = helpers.as_enum(body, "booking_mode", BOOKING_MODES)
    seats = helpers.as_int(body, "seats", min_value=1)
    expected_version = helpers.as_int(body, "expected_event_version")
    include_kit = helpers.as_bool(body, "include_supply_kit", required=False, default=False)

    # Priority 5: body FK existence.
    event = db.events.get(event_id)
    if not event:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "event_id does not exist")
    customer = db.customers.get(customer_id)
    if not customer:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "customer_id does not exist")

    # Priority 7: parent event must be OPEN or FULL.
    if event["status"] not in {"OPEN", "FULL"}:
        raise err(errors.ERR_INVALID_STATE, "Event is not OPEN/FULL")

    # Priority 9: booking_mode / event_type compatibility.
    if booking_mode == "PUBLIC" and event["event_type"] not in PUBLIC_EVENT_TYPES:
        raise err(errors.ERR_BOOKING_MODE_MISMATCH,
                  "PUBLIC only on PUBLIC_CLASS/FUNDRAISER")
    if booking_mode == "PRIVATE" and event["event_type"] not in PRIVATE_EVENT_TYPES:
        raise err(errors.ERR_BOOKING_MODE_MISMATCH,
                  "PRIVATE only on PRIVATE_PARTY/CORPORATE")

    # Priority 16: seat capacity.
    if seats > event["seats_available"]:
        raise err(errors.ERR_INSUFFICIENT_SEATS, "Requested seats exceed availability")

    # Priority 18: OCC on event version.
    if expected_version != event["version"]:
        raise err(errors.ERR_STALE_EVENT_VERSION,
                  "expected_event_version does not match current event version")

    # Pricing (reservation_pricing).
    base, pct, kit_charge, total = calc.reservation_pricing(
        seats, event["price_cents_per_seat"], event["kit_fee_cents"], include_kit)

    rec = models.make_reservation(event_id, customer_id, booking_mode, seats, include_kit)
    rec["base_cents"] = base
    rec["group_discount_pct"] = pct
    rec["kit_charge_cents"] = kit_charge
    rec["total_cents"] = total
    db.reservations[rec["id"]] = rec

    # Parent event side effects: ledger, FULL flip, pledged donation, version++.
    core.recompute_seat_ledger(event)
    core.apply_full_flip(event)
    core.recompute_pledged_donation(event)
    models.touch(event)

    return object_response(models.serialize_reservation(rec), 201)


@bp.get("/studio-ops/reservations/<rid>")
def get_reservation(rid):
    middleware.authenticate()
    middleware.require_roles("Customer", "FrontDesk", "StudioManager", "PlatformAdmin")
    rec = db.reservations.get(rid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Reservation not found")
    _owns_or_raise(rec)
    return object_response(models.serialize_reservation(rec), 200)


@bp.get("/studio-ops/reservations")
def list_reservations():
    middleware.authenticate()
    middleware.require_roles("FrontDesk", "StudioManager", "PlatformAdmin")
    limit, offset = helpers.parse_pagination()
    event_id = request.args.get("event_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    payment_status = request.args.get("payment_status")
    rows = list(db.reservations.values())
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if payment_status:
        rows = [r for r in rows if r["payment_status"] == payment_status]
    page, total = helpers.sort_and_page(rows, limit, offset)
    return array_response([models.serialize_reservation(r) for r in page],
                          limit, offset, total, 200)


@bp.get("/studio-ops/reservations/<rid>/cancellation-quote")
def cancellation_quote(rid):
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    rec = db.reservations.get(rid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Reservation not found")
    _owns_or_raise(rec)
    event = db.events.get(rec["event_id"])
    hrs = calc.hours_before(event["_start_dt"], clock.now())
    pct, credit = calc.cancellation_credit(rec["total_cents"], hrs)
    return object_response({
        "hours_before": hrs,
        "credit_pct": pct,
        "credit_granted_cents": credit,
    }, 200)


@bp.post("/studio-ops/reservations/<rid>/pay")
def pay_reservation(rid):
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    rec = db.reservations.get(rid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Reservation not found")
    _owns_or_raise(rec)
    body = helpers.get_json_body()

    # Well-formedness of optional inputs.
    gift_card_ids = body.get("gift_card_ids")
    if gift_card_ids is None:
        gift_card_ids = []
    if not isinstance(gift_card_ids, list) or not all(isinstance(x, str) for x in gift_card_ids):
        raise err(errors.ERR_VALIDATION, "gift_card_ids must be a list of strings")
    use_credit = helpers.as_bool(body, "use_studio_credit", required=False, default=False)

    # Priority 7: payable only while HELD or CONFIRMED.
    if rec["status"] not in {"HELD", "CONFIRMED"}:
        raise err(errors.ERR_INVALID_STATE, "Reservation is not HELD/CONFIRMED")

    # Priority 5: supplied gift cards must exist.
    cards = []
    for gid in gift_card_ids:
        gc = db.gift_cards.get(gid)
        if not gc:
            raise err(errors.ERR_REFERENCE_NOT_FOUND, "gift_card_id does not exist")
        cards.append(gc)

    # Priority 15: every supplied gift card must be ACTIVE (non-DEPLETED).
    for gc in cards:
        if gc["status"] != "ACTIVE":
            raise err(errors.ERR_GIFT_CARD_DEPLETED, "Supplied gift card is DEPLETED")

    customer = db.customers.get(rec["customer_id"])

    # Waterfall (gift_card_payment_waterfall). Gift cards in created_at ASC.
    remaining = rec["total_cents"]
    cards_sorted = sorted(cards, key=lambda c: c["_seq"])
    for gc in cards_sorted:
        if remaining <= 0:
            break
        draw = min(gc["balance_cents"], remaining)
        if draw > 0:
            p = models.make_payment(rec["id"], "GIFT_CARD", gc["id"], draw)
            db.payments[p["id"]] = p
            gc["balance_cents"] -= draw
            gc["redeemed_cents"] += draw
            if gc["balance_cents"] == 0:
                gc["status"] = "DEPLETED"
            models.touch(gc)
            remaining -= draw

    if use_credit and customer and customer["credit_balance_cents"] > 0 and remaining > 0:
        draw = min(customer["credit_balance_cents"], remaining)
        if draw > 0:
            p = models.make_payment(rec["id"], "STUDIO_CREDIT", None, draw)
            db.payments[p["id"]] = p
            customer["credit_balance_cents"] -= draw
            customer["credit_redeemed_cents"] += draw
            models.touch(customer)
            remaining -= draw

    if remaining > 0:
        p = models.make_payment(rec["id"], "CARD", None, remaining)
        db.payments[p["id"]] = p
        remaining = 0

    core.recompute_amount_paid(rec)
    rec["payment_status"] = "PAID"
    models.touch(rec)
    return object_response(models.serialize_reservation(rec), 200)


@bp.post("/studio-ops/reservations/<rid>/confirm")
def confirm_reservation(rid):
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    rec = db.reservations.get(rid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Reservation not found")
    _owns_or_raise(rec)
    # State: must be HELD, payment PAID, and parent event OPEN/FULL.
    if rec["status"] != "HELD":
        raise err(errors.ERR_INVALID_STATE, "Reservation is not HELD")
    if rec["payment_status"] != "PAID":
        raise err(errors.ERR_INVALID_STATE, "Reservation is not PAID")
    event = db.events.get(rec["event_id"])
    if event["status"] not in {"OPEN", "FULL"}:
        raise err(errors.ERR_INVALID_STATE, "Event is not OPEN/FULL")
    rec["status"] = "CONFIRMED"
    models.touch(rec)
    return object_response(models.serialize_reservation(rec), 200)


@bp.post("/studio-ops/reservations/<rid>/check-in")
def check_in_reservation(rid):
    middleware.authenticate()
    middleware.require_roles("FrontDesk", "StudioManager", "PlatformAdmin")
    rec = db.reservations.get(rid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Reservation not found")
    # State: must be CONFIRMED.
    if rec["status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Reservation is not CONFIRMED")
    event = db.events.get(rec["event_id"])
    # Parent event OPEN/FULL.
    if event["status"] not in {"OPEN", "FULL"}:
        raise err(errors.ERR_INVALID_STATE, "Event is not OPEN/FULL")

    attendees = core.reservation_attendees(rid)
    # Priority 14: roster completeness — attendee count == seats.
    if len(attendees) != rec["seats"]:
        raise err(errors.ERR_ATTENDEE_ROSTER_INCOMPLETE,
                  "Attendee count does not equal reservation.seats")
    # Priority 13: BYOB age/waiver gate.
    if event["byob_allowed"]:
        for a in attendees:
            if not a["waiver_signed"] or a["age_years"] < event["min_age"]:
                raise err(errors.ERR_WAIVER_OR_AGE_FAIL,
                          "Attendee fails BYOB waiver/age gate")

    rec["status"] = "CHECKED_IN"
    models.touch(rec)

    # Kit consumption (capped at prepared_count).
    if rec["include_supply_kit"]:
        for kb in db.kit_batches.values():
            if kb["event_id"] == event["id"]:
                room = kb["prepared_count"] - kb["consumed_count"]
                take = min(rec["seats"], max(0, room))
                if take > 0:
                    kb["consumed_count"] += take
                    models.touch(kb)
                break

    return object_response(models.serialize_reservation(rec), 200)


@bp.post("/studio-ops/reservations/<rid>/cancel")
def cancel_reservation(rid):
    middleware.authenticate()
    middleware.require_roles("Customer", "StudioManager", "PlatformAdmin")
    rec = db.reservations.get(rid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Reservation not found")
    _owns_or_raise(rec)
    # State: must be HELD or CONFIRMED.
    if rec["status"] not in {"HELD", "CONFIRMED"}:
        raise err(errors.ERR_INVALID_STATE, "Reservation is not HELD/CONFIRMED")
    event = db.events.get(rec["event_id"])
    # Parent event must not be CLOSED or CANCELLED.
    if event["status"] in {"CLOSED", "CANCELLED"}:
        raise err(errors.ERR_INVALID_STATE, "Event is CLOSED/CANCELLED")

    # Credit ladder.
    hrs = calc.hours_before(event["_start_dt"], clock.now())
    rec["cancelled_at_hours_before"] = hrs
    pct, credit = calc.cancellation_credit(rec["total_cents"], hrs)
    rec["credit_granted_cents"] = credit

    # hop 2: reverse CARD payments + REFUNDED.
    core.reverse_card_payments_and_refund(rec)
    # hop 3: credit the customer's wallet.
    customer = db.customers.get(rec["customer_id"])
    if customer and credit > 0:
        customer["credit_balance_cents"] += credit
        models.touch(customer)

    rec["status"] = "CANCELLED"
    models.touch(rec)

    # Parent event: release seats, FULL->OPEN, recompute pledged, version++.
    core.recompute_seat_ledger(event)
    core.apply_full_flip(event)
    core.recompute_pledged_donation(event)
    models.touch(event)

    return object_response(models.serialize_reservation(rec), 200)
