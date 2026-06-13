"""Booking lifecycle: create / confirm / pay / cancel / exchange, plus the
service-date cancel cascade and ticket voiding.

Implements PRD 3.3-3.10 and the scaffold state machines. Validation ordering
follows PRD 2.11 (priority 1-15).
"""
from datetime import timedelta

import clock
from timeutil import iso_now, parse_iso
from errors import err
import db
from constants import HOLD_TTL_MIN
from services import pricing, inventory, passes as pass_svc
from services.connections import connection_buffer_ok


# ---------------------------------------------------------------------------
# Ticket helpers
# ---------------------------------------------------------------------------
def _issue_ticket(booking, leg):
    tid = db.new_id()
    rec = {
        "id": tid,
        "booking_id": booking["id"],
        "booking_leg_id": leg["id"],
        "barcode": "bc_" + db.new_id().replace("-", ""),
        "state": "ISSUED",
    }
    db.stamp_create(rec)
    db.tickets[tid] = rec
    return rec


def _void_issued_tickets_for_booking(booking_id):
    for t in db.tickets.values():
        if t["booking_id"] == booking_id and t["state"] == "ISSUED":
            t["state"] = "VOID"
            db.touch(t)


def _legs_of(booking_id):
    return [lg for lg in db.booking_legs.values() if lg["booking_id"] == booking_id]


def _active_legs_of(booking_id):
    return [lg for lg in _legs_of(booking_id) if lg["leg_state"] == "ACTIVE"]


def _booking_has_scanned_ticket(booking_id):
    return any(
        t["booking_id"] == booking_id and t["state"] == "SCANNED"
        for t in db.tickets.values()
    )


def _min_active_leg_departure_date(booking_id):
    legs = _active_legs_of(booking_id)
    dates = [db.service_dates[lg["service_date_id"]]["departure_date"] for lg in legs]
    return min(dates) if dates else None


# ---------------------------------------------------------------------------
# Create (HELD)  — PRD 3.3
# ---------------------------------------------------------------------------
def create_booking(passenger_id, funding_kind, pass_id, legs_payload):
    """Create a HELD/UNPAID booking with one BookingLeg per legs[] entry,
    placing seat holds.

    Caller has already done: auth, ownership, NOT_FOUND on passenger, and
    ERR_INVALID_REQUEST body-shape checks (funding/pass and seat/seating mode
    presence). This function performs existence (priority 3) on referenced
    legs, then the remaining business validations in priority order.
    """
    # --- Priority 3: existence of every referenced resource, left-to-right ---
    # pass existence first (it appears in the body before legs conceptually);
    # the route layer validates the passenger already.
    travel_pass = None
    if funding_kind == "PASS":
        travel_pass = db.travel_passes.get(pass_id)
        if travel_pass is None:
            raise err("ERR_NOT_FOUND", "pass_id does not resolve")

    resolved = []
    for entry in legs_payload:
        sd = db.service_dates.get(entry.get("service_date_id"))
        if sd is None:
            raise err("ERR_NOT_FOUND", "service_date_id does not resolve")
        fc = db.fare_classes.get(entry.get("fare_class_id"))
        if fc is None:
            raise err("ERR_NOT_FOUND", "fare_class_id does not resolve")
        resolved.append((entry, sd, fc))

    # --- Priority 5 (body shape) for each leg: seat_number presence vs mode ---
    for entry, sd, fc in resolved:
        seat = entry.get("seat_number")
        if fc["seating_mode"] == "RESERVED" and (seat is None or seat == ""):
            raise err("ERR_INVALID_REQUEST", "seat_number required for RESERVED leg")
        if fc["seating_mode"] == "OPEN" and seat not in (None, ""):
            raise err("ERR_INVALID_REQUEST", "seat_number forbidden for OPEN leg")

    # --- Priority 7: cross-entity preconditions (RETIRED fare class, sales gate) ---
    for entry, sd, fc in resolved:
        if fc["status"] == "RETIRED":
            raise err("ERR_FARE_CLASS_RETIRED", "fare class is retired")
    for entry, sd, fc in resolved:
        if sd["sales"] != "OPEN":
            raise err("ERR_PRECONDITION_NOT_MET", "service date sales not OPEN")
        if sd["lifecycle"] not in ("SCHEDULED", "DELAYED"):
            raise err("ERR_PRECONDITION_NOT_MET", "service date lifecycle not bookable")

    # --- Priority 8: pass not EXPIRED at redemption ---
    if funding_kind == "PASS":
        if travel_pass["status"] == "EXPIRED" or pass_svc.is_expired_by_clock(travel_pass):
            pass_svc.mark_expired(travel_pass)
            raise err("ERR_PASS_EXPIRED", "travel pass is expired")

    # --- Priority 9: connection buffer (multi-leg) ---
    pseudo_legs = [
        {"service_date_id": sd["id"], "leg_order": entry["leg_order"]}
        for entry, sd, fc in resolved
    ]
    if not connection_buffer_ok(pseudo_legs):
        raise err("ERR_CONNECTION_TOO_TIGHT", "connection buffer not satisfied")

    # --- Priority 11: reserved-seat uniqueness ---
    seen_seats = {}  # (service_date_id, seat) -> True within this request
    for entry, sd, fc in resolved:
        seat = entry.get("seat_number")
        if fc["seating_mode"] == "RESERVED":
            key = (sd["id"], seat)
            if key in seen_seats or inventory.seat_taken(sd["id"], seat):
                raise err("ERR_SEAT_TAKEN", "reserved seat already taken")
            seen_seats[key] = True

    # --- Priority 13: aggregate seat capacity (per service date) ---
    requested_per_sd = {}
    for entry, sd, fc in resolved:
        requested_per_sd[sd["id"]] = requested_per_sd.get(sd["id"], 0) + 1
    for sd_id, want in requested_per_sd.items():
        sd = db.service_dates[sd_id]
        if sd["seats_available"] < want:
            raise err("ERR_SOLD_OUT", "service date has no available seats")

    # --- All checks passed: commit ---
    bid = db.new_id()
    hold_expires = clock.now() + timedelta(minutes=HOLD_TTL_MIN)
    booking = {
        "id": bid,
        "passenger_id": passenger_id,
        "booking_status": "HELD",
        "payment_status": "UNPAID",
        "funding_kind": funding_kind,
        "pass_id": pass_id if funding_kind == "PASS" else None,
        "total_fare_cents": 0,
        "total_paid_cents": 0,
        "hold_expires_at": iso_now(hold_expires),
    }
    db.stamp_create(booking)
    db.bookings[bid] = booking

    for entry, sd, fc in resolved:
        lid = db.new_id()
        leg = {
            "id": lid,
            "booking_id": bid,
            "service_date_id": sd["id"],
            "fare_class_id": fc["id"],
            "leg_order": entry["leg_order"],
            "seat_number": entry.get("seat_number"),
            "fare_cents": 0,
            "leg_state": "ACTIVE",
        }
        db.stamp_create(leg)
        db.booking_legs[lid] = leg

    # Recompute inventory for each affected service date (seats_held +1 each).
    for sd_id in {sd["id"] for _, sd, _ in resolved}:
        inventory.recompute(db.service_dates[sd_id])

    return booking


# ---------------------------------------------------------------------------
# Confirm (HELD -> CONFIRMED)  — PRD 3.4
# ---------------------------------------------------------------------------
def confirm_booking(booking, expected_service_date_version):
    # --- Priority 6: generic state ---
    if booking["booking_status"] != "HELD":
        raise err("ERR_INVALID_STATE", "booking not HELD")

    legs = _active_legs_of(booking["id"])

    # --- Priority 7: cross-entity preconditions (sales OPEN, lifecycle ok) ---
    for leg in legs:
        sd = db.service_dates[leg["service_date_id"]]
        if sd["sales"] != "OPEN":
            raise err("ERR_PRECONDITION_NOT_MET", "service date sales not OPEN")
        if sd["lifecycle"] not in ("SCHEDULED", "DELAYED"):
            raise err("ERR_PRECONDITION_NOT_MET", "service date lifecycle not bookable")

    # --- Priority 8: hold not expired ---
    if clock.now() >= parse_iso(booking["hold_expires_at"]):
        raise err("ERR_HOLD_EXPIRED", "hold has expired")
    # Pass-funded: pass must not be expired (same temporal family) ---
    travel_pass = None
    if booking["funding_kind"] == "PASS":
        travel_pass = db.travel_passes.get(booking["pass_id"])
        if travel_pass is not None and (
            travel_pass["status"] == "EXPIRED" or pass_svc.is_expired_by_clock(travel_pass)
        ):
            pass_svc.mark_expired(travel_pass)
            raise err("ERR_HOLD_EXPIRED", "travel pass is expired")

    # --- Priority 9: connection buffer re-check ---
    if not connection_buffer_ok(legs):
        raise err("ERR_CONNECTION_TOO_TIGHT", "connection buffer not satisfied")

    # --- Priority 11: reserved seat still free ---
    for leg in legs:
        sd = db.service_dates[leg["service_date_id"]]
        fc = db.fare_classes[leg["fare_class_id"]]
        if fc["seating_mode"] == "RESERVED":
            if inventory.seat_taken(sd["id"], leg.get("seat_number"), exclude_leg_id=leg["id"]):
                raise err("ERR_SEAT_TAKEN", "reserved seat already taken")

    # --- Priority 13: seat availability re-checked ---
    # This booking's HELD legs already occupy seats in seats_held; confirming
    # moves them held->sold without increasing total occupancy, so a leg's own
    # held seat counts as room for itself. Sufficient capacity on a service date
    # means seats_available (free seats beyond holds) plus this booking's held
    # legs there is at least the number of legs this booking confirms there.
    held_here = {}
    for leg in legs:
        held_here[leg["service_date_id"]] = held_here.get(leg["service_date_id"], 0) + 1
    for sd_id, want in held_here.items():
        sd = db.service_dates[sd_id]
        if sd["seats_available"] + want < want:  # i.e. seats_available < 0; invariant guards
            raise err("ERR_SOLD_OUT", "service date has no available seats")

    # --- Priority 14: pass balance ---
    if booking["funding_kind"] == "PASS":
        if travel_pass is None:
            raise err("ERR_NOT_FOUND", "pass not found")
        if travel_pass["rides_remaining"] < len(legs):
            raise err("ERR_PASS_DEPLETED", "pass has insufficient rides")

    # --- Priority 15: OCC on each referenced service date ---
    for leg in legs:
        sd = db.service_dates[leg["service_date_id"]]
        if sd["version"] != expected_service_date_version:
            raise err("ERR_STALE_VERSION", "service date version is stale")

    # --- Commit: price legs (demand measured BEFORE moving seats to sold) ---
    is_pass = booking["funding_kind"] == "PASS"
    total = 0
    for leg in legs:
        sd = db.service_dates[leg["service_date_id"]]
        fc = db.fare_classes[leg["fare_class_id"]]
        if is_pass:
            leg["fare_cents"] = 0
        else:
            leg["fare_cents"] = pricing.leg_fare_cents(sd, fc)
            total += leg["fare_cents"]
        db.touch(leg)

    booking["booking_status"] = "CONFIRMED"
    booking["total_fare_cents"] = 0 if is_pass else total
    db.touch(booking)

    # Move held->sold: recompute inventory (CONFIRMED legs now count as sold).
    for sd_id in {leg["service_date_id"] for leg in legs}:
        inventory.recompute(db.service_dates[sd_id])

    # Issue one ticket per leg.
    for leg in legs:
        _issue_ticket(booking, leg)

    # Pass-funded: consume rides and re-derive status.
    if is_pass:
        pass_svc.recompute(travel_pass)

    return booking


# ---------------------------------------------------------------------------
# Pay (UNPAID -> PAID)  — PRD 3.5
# ---------------------------------------------------------------------------
def pay_booking(booking):
    # funding kind disqualifies -> ERR_PRECONDITION_NOT_MET (PRD 3.5).
    if booking["funding_kind"] != "CASH":
        raise err("ERR_PRECONDITION_NOT_MET", "only cash bookings can be paid")
    if booking["booking_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "booking not CONFIRMED")
    if booking["payment_status"] != "UNPAID":
        raise err("ERR_INVALID_STATE", "booking not UNPAID")

    booking["total_paid_cents"] = booking["total_fare_cents"]
    booking["payment_status"] = "PAID"
    db.touch(booking)
    return booking


# ---------------------------------------------------------------------------
# Cancel (HELD or CONFIRMED -> CANCELLED)  — PRD 3.6
# ---------------------------------------------------------------------------
def cancel_booking(booking, refund_destination):
    status = booking["booking_status"]
    if status not in ("HELD", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "booking not cancellable")

    if status == "CONFIRMED":
        # --- Priority 7: no SCANNED ticket blocks cancel ---
        if _booking_has_scanned_ticket(booking["id"]):
            raise err("ERR_PRECONDITION_NOT_MET", "scanned ticket blocks cancel")

    # Settlement decision for PAID cash bookings (PRD 3.6).
    is_paid_cash = (booking["payment_status"] == "PAID" and booking["funding_kind"] == "CASH")
    if is_paid_cash:
        if refund_destination is None:
            raise err("ERR_NOT_PAID", "refund_destination required for a paid booking")
        if refund_destination not in ("CASH", "TRAVEL_CREDIT"):
            raise err("ERR_INVALID_REQUEST", "invalid refund_destination")
        # --- Priority 12: refund eligibility for CASH ---
        if refund_destination == "CASH":
            for leg in _active_legs_of(booking["id"]):
                fc = db.fare_classes[leg["fare_class_id"]]
                if not fc["refundable"]:
                    raise err("ERR_REFUND_NOT_ALLOWED", "fare class is non-refundable")

    # --- Commit ---
    affected_sd = set()
    legs = _active_legs_of(booking["id"])
    for leg in legs:
        leg["leg_state"] = "RELEASED"
        db.touch(leg)
        affected_sd.add(leg["service_date_id"])

    # Void issued tickets (only for confirmed bookings will any exist).
    _void_issued_tickets_for_booking(booking["id"])

    # Settlement for PAID cash bookings.
    if is_paid_cash:
        min_dep = _min_active_leg_departure_date_pre_release(legs)
        gross = booking["total_paid_cents"]
        penalty, net = pricing.cancel_settlement(gross, min_dep, refund_destination)
        kind = "CASH" if refund_destination == "CASH" else "TRAVEL_CREDIT"
        _create_settlement_note(booking, kind, gross, penalty, net)
        booking["payment_status"] = "REFUNDED" if refund_destination == "CASH" else "CREDITED"

    booking["booking_status"] = "CANCELLED"
    db.touch(booking)

    # Restore pass rides if pass-funded.
    if booking["funding_kind"] == "PASS" and booking.get("pass_id"):
        tp = db.travel_passes.get(booking["pass_id"])
        if tp is not None:
            pass_svc.recompute(tp)

    # Recompute inventory for affected service dates.
    for sd_id in affected_sd:
        inventory.recompute(db.service_dates[sd_id])

    return booking


def _min_active_leg_departure_date_pre_release(legs):
    dates = [db.service_dates[lg["service_date_id"]]["departure_date"] for lg in legs]
    return min(dates) if dates else None


def _create_settlement_note(booking, kind, gross, penalty, net):
    nid = db.new_id()
    rec = {
        "id": nid,
        "booking_id": booking["id"],
        "settlement_kind": kind,
        "gross_cents": gross,
        "penalty_cents": penalty,
        "net_cents": net,
    }
    db.stamp_create(rec, with_version=False)
    db.settlement_notes[nid] = rec
    return rec


# ---------------------------------------------------------------------------
# Exchange (CONFIRMED -> EXCHANGED)  — PRD 3.8
# ---------------------------------------------------------------------------
def exchange_booking(booking, target_sd_id, target_fc_id, target_seat_number,
                     expected_booking_version):
    # --- Priority 6: generic state ---
    if booking["booking_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "booking not CONFIRMED")

    # funding kind must be CASH (PRD 3.8).
    if booking["funding_kind"] != "CASH":
        raise err("ERR_PRECONDITION_NOT_MET", "only cash bookings can be exchanged")

    # Booking must be PAID to settle an exchange against total_paid_cents.
    if booking["payment_status"] != "PAID":
        raise err("ERR_NOT_PAID", "booking is not paid")

    # --- Priority 3 (target existence) ---
    target_sd = db.service_dates.get(target_sd_id)
    if target_sd is None:
        raise err("ERR_NOT_FOUND", "target_service_date_id does not resolve")
    target_fc = db.fare_classes.get(target_fc_id)
    if target_fc is None:
        raise err("ERR_NOT_FOUND", "target_fare_class_id does not resolve")

    # --- Priority 5: seat presence vs target seating mode ---
    if target_fc["seating_mode"] == "RESERVED" and (target_seat_number in (None, "")):
        raise err("ERR_INVALID_REQUEST", "target_seat_number required for RESERVED")
    if target_fc["seating_mode"] == "OPEN" and target_seat_number not in (None, ""):
        raise err("ERR_INVALID_REQUEST", "target_seat_number forbidden for OPEN")

    # --- Priority 7: SCANNED ticket blocks; target trip suitability ---
    if _booking_has_scanned_ticket(booking["id"]):
        raise err("ERR_PRECONDITION_NOT_MET", "scanned ticket blocks exchange")
    if target_fc["status"] == "RETIRED":
        raise err("ERR_FARE_CLASS_RETIRED", "target fare class is retired")
    if target_sd["sales"] != "OPEN":
        raise err("ERR_PRECONDITION_NOT_MET", "target sales not OPEN")
    if target_sd["lifecycle"] not in ("SCHEDULED", "DELAYED"):
        raise err("ERR_PRECONDITION_NOT_MET", "target lifecycle not bookable")

    # --- Priority 11: reserved seat free on target ---
    if target_fc["seating_mode"] == "RESERVED":
        if inventory.seat_taken(target_sd_id, target_seat_number):
            raise err("ERR_SEAT_TAKEN", "target reserved seat already taken")

    # --- Priority 13: target seat availability ---
    if target_sd["seats_available"] < 1:
        raise err("ERR_SOLD_OUT", "target service date has no available seats")

    # --- Priority 15: OCC on Booking ---
    if booking["version"] != expected_booking_version:
        raise err("ERR_STALE_VERSION", "booking version is stale")

    # --- Commit ---
    old_legs = _active_legs_of(booking["id"])
    old_sd_ids = {lg["service_date_id"] for lg in old_legs}

    # Step 1: price new leg against target (fresh demand+advance).
    new_leg_fare = pricing.leg_fare_cents(target_sd, target_fc)
    # Step 2: amount due (informational; surplus -> travel credit).
    operator = db.operators[db.routes[target_sd["route_id"]]["operator_id"]]
    amount_due = new_leg_fare - booking["total_paid_cents"] + operator["exchange_fee_cents"]

    # Release old legs and void old tickets.
    for leg in old_legs:
        leg["leg_state"] = "RELEASED"
        db.touch(leg)
    _void_issued_tickets_for_booking(booking["id"])

    # Create the replacement booking (CONFIRMED + PAID).
    new_bid = db.new_id()
    new_booking = {
        "id": new_bid,
        "passenger_id": booking["passenger_id"],
        "booking_status": "CONFIRMED",
        "payment_status": "PAID",
        "funding_kind": "CASH",
        "pass_id": None,
        "total_fare_cents": new_leg_fare,
        "total_paid_cents": new_leg_fare,
        "hold_expires_at": booking["hold_expires_at"],
    }
    db.stamp_create(new_booking)
    db.bookings[new_bid] = new_booking

    new_lid = db.new_id()
    new_leg = {
        "id": new_lid,
        "booking_id": new_bid,
        "service_date_id": target_sd_id,
        "fare_class_id": target_fc_id,
        "leg_order": 1,
        "seat_number": target_seat_number if target_fc["seating_mode"] == "RESERVED" else None,
        "fare_cents": new_leg_fare,
        "leg_state": "ACTIVE",
    }
    db.stamp_create(new_leg)
    db.booking_legs[new_lid] = new_leg

    _issue_ticket(new_booking, new_leg)

    # Old booking -> EXCHANGED (terminal).
    booking["booking_status"] = "EXCHANGED"
    db.touch(booking)

    # If surplus (amount_due < 0), issue a TRAVEL_CREDIT note for the surplus.
    if amount_due < 0:
        surplus = -amount_due
        _create_settlement_note(booking, "TRAVEL_CREDIT", surplus, 0, surplus)

    # Recompute inventory for old + target service dates.
    for sd_id in old_sd_ids | {target_sd_id}:
        inventory.recompute(db.service_dates[sd_id])

    # PRD 3.8 / 2.3: the exchange's created resource is the new CONFIRMED+PAID
    # booking holding the replacement leg; per the envelope convention an
    # operation that creates a resource returns the created resource.
    return new_booking


# ---------------------------------------------------------------------------
# Service-date cancel cascade  — PRD 3.2
# ---------------------------------------------------------------------------
def cascade_cancel_service_date(service_date):
    """Depth-3 cascade triggered by ServiceDate cancel. Caller has already set
    lifecycle=CANCELLED, sales=SUSPENDED, and bumped the service date version."""
    # Hop 1: every ACTIVE leg on this service date -> force-cancel its booking.
    affected_booking_ids = []
    for leg in db.booking_legs.values():
        if leg["service_date_id"] != service_date["id"]:
            continue
        if leg["leg_state"] != "ACTIVE":
            continue
        b = db.bookings.get(leg["booking_id"])
        if b is None:
            continue
        if b["booking_status"] in ("HELD", "CONFIRMED") and b["id"] not in affected_booking_ids:
            affected_booking_ids.append(b["id"])

    touched_sd = set()
    touched_passes = set()

    for bid in affected_booking_ids:
        booking = db.bookings[bid]
        was_paid_cash = (booking["payment_status"] == "PAID" and booking["funding_kind"] == "CASH")

        # Hop 2: release all legs of this booking.
        for leg in _active_legs_of(bid):
            leg["leg_state"] = "RELEASED"
            db.touch(leg)
            touched_sd.add(leg["service_date_id"])

        # Hop 3a: void issued tickets.
        _void_issued_tickets_for_booking(bid)

        # Hop 3b: PAID cash booking -> full CASH refund (penalty 0), REFUNDED.
        if was_paid_cash:
            gross = booking["total_paid_cents"]
            penalty, net = pricing.cancel_settlement_full_cash(gross)
            _create_settlement_note(booking, "CASH", gross, penalty, net)
            booking["payment_status"] = "REFUNDED"

        booking["booking_status"] = "CANCELLED"
        db.touch(booking)

        # Hop 3c: pass-funded -> restore rides.
        if booking["funding_kind"] == "PASS" and booking.get("pass_id"):
            touched_passes.add(booking["pass_id"])

    # Recompute inventory for every touched service date (incl. this one).
    touched_sd.add(service_date["id"])
    for sd_id in touched_sd:
        inventory.recompute(db.service_dates[sd_id])

    # Restore pass balances.
    for pid in touched_passes:
        tp = db.travel_passes.get(pid)
        if tp is not None:
            pass_svc.recompute(tp)
