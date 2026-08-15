"""Cascade services: flight delay/retime misconnect protection, flight cancel
four-link cascade, record-actuals rollup + compensation sweeps, booking cancel."""

from db import db, now

from services.core import (
    MIN_CONNECT_MINUTES,
    booking_completion_rollup,
    booking_segments,
    compensation_base_cents,
    create_case_for_booking,
    crew_legality_reeval,
    original_segments,
    queue_comm,
    recompute_event_affected,
    recompute_refund_credit,
    touch,
)

COMP_DELAY_THRESHOLD_MINUTES = 180
REDUCTION_THRESHOLD_MINUTES = 240


def _grant_eligibility(booking, basis):
    """NONE -> ELIGIBLE_PENDING with timestamps, deadline, amount init."""
    if booking["compensation_status"] != "NONE":
        return
    booking["compensation_status"] = "ELIGIBLE_PENDING"
    booking["eligible_at"] = now()
    from datetime import timedelta
    booking["election_deadline"] = booking["eligible_at"] + timedelta(hours=72)
    booking["compensation_amount_cents"] = compensation_base_cents(booking["id"])
    booking["compensation_basis"] = basis
    booking["updated_at"] = now()


def disrupt_booking(booking, event_id, disrupted_segment, comm_template):
    """Shared booking-disruption cascade: booking -> DISRUPTED, case, comm."""
    became_disrupted = booking["booking_status"] != "DISRUPTED"
    if became_disrupted:
        booking["booking_status"] = "DISRUPTED"
        touch(booking)
    if became_disrupted:
        case = create_case_for_booking(booking, event_id, disrupted_segment)
        if case is not None:
            queue_comm(booking["id"], event_id, comm_template)
    return became_disrupted


def run_misconnect_cascade(flight):
    """Second pass of flight delay/retime (PRD §3.3): for every CONFIRMED segment
    on this flight, if the booking's next CONFIRMED segment departs < 45 min after
    the new arrival, the next segment becomes DISRUPTED; its booking becomes
    DISRUPTED; a case is created under the no-open-case rule; DISRUPTION_DETECTED
    comm queued per created case."""
    affected_event_id = flight["disruption_event_id"]
    for seg in list(db.booking_segments.values()):
        if seg["flight_id"] != flight["id"] or seg["segment_status"] != "CONFIRMED":
            continue
        booking = db.bookings.get(seg["booking_id"])
        if booking is None:
            continue
        segs = sorted(booking_segments(booking["id"]), key=lambda s: s["seq_no"])
        nxt = None
        for i, s in enumerate(segs):
            if s["id"] == seg["id"] and i + 1 < len(segs):
                nxt = segs[i + 1]
                break
        if nxt is None or nxt["segment_status"] != "CONFIRMED":
            continue
        next_flight = db.flights.get(nxt["flight_id"])
        if next_flight is None or next_flight["sched_dep_utc"] is None:
            continue
        gap = (next_flight["sched_dep_utc"] - flight["sched_arr_utc"]).total_seconds() / 60.0
        if gap < MIN_CONNECT_MINUTES:
            nxt["segment_status"] = "DISRUPTED"
            touch(nxt)
            event_id = (next_flight["disruption_event_id"] or affected_event_id)
            disrupt_booking(booking, event_id, nxt, "DISRUPTION_DETECTED")
            if event_id:
                recompute_event_affected(event_id)
            if affected_event_id and affected_event_id != event_id:
                recompute_event_affected(affected_event_id)


def run_cancel_cascade(flight, event):
    """Four-link cancellation cascade (PRD §3.3)."""
    event_id = event["id"]
    # Link 1: every CONFIRMED segment on this flight becomes CANCELLED.
    # Seats are retained in seats_sold for audit until rebooked.
    cancelled_segments = []
    for seg in list(db.booking_segments.values()):
        if seg["flight_id"] == flight["id"] and seg["segment_status"] == "CONFIRMED":
            seg["segment_status"] = "CANCELLED"
            touch(seg)
            cancelled_segments.append(seg)
    # Link 2: each booking owning such a segment becomes DISRUPTED unless already.
    disrupted_bookings = []
    seen = set()
    for seg in cancelled_segments:
        booking = db.bookings.get(seg["booking_id"])
        if booking is None or booking["id"] in seen:
            continue
        seen.add(booking["id"])
        if booking["booking_status"] != "DISRUPTED":
            booking["booking_status"] = "DISRUPTED"
            touch(booking)
            disrupted_bookings.append((booking, seg))
        else:
            disrupted_bookings.append((booking, seg))
    # Link 3: case creation + compensation eligibility when controllable.
    new_cases = []
    for booking, seg in disrupted_bookings:
        case = create_case_for_booking(booking, event_id, seg)
        if event["is_controllable"]:
            _grant_eligibility(booking, "PROVISIONAL")
        if case is not None:
            new_cases.append((case, booking))
    # Link 4: comms + affected counters.
    for case, booking in new_cases:
        queue_comm(booking["id"], event_id, "CANCELLATION")
    recompute_event_affected(event_id)


def run_record_actuals(flight):
    """Arrival side effects (PRD §3.1, §3.7): segments FLOWN; booking completion
    rollup; refund/credit recompute; final compensation recompute; arrival-delay
    eligibility sweep."""
    # Flow CONFIRMED segments on this flight.
    flown_bookings = []
    for seg in list(db.booking_segments.values()):
        if seg["flight_id"] == flight["id"] and seg["segment_status"] == "CONFIRMED":
            seg["segment_status"] = "FLOWN"
            touch(seg)
            booking = db.bookings.get(seg["booking_id"])
            if booking is not None:
                flown_bookings.append(booking)
    seen = set()
    for booking in flown_bookings:
        if booking["id"] in seen:
            continue
        seen.add(booking["id"])
        recompute_refund_credit(booking)
        booking_completion_rollup(booking)

    event = (db.disruption_events.get(flight["disruption_event_id"])
             if flight["disruption_event_id"] else None)

    # Final compensation recompute: for every booking with compensation_status in
    # {ELIGIBLE_PENDING, ELECTED_REFUND, ELECTED_CREDIT} whose current itinerary
    # ends on this flight, recompute from actual arrival vs original final arr.
    for booking in list(db.bookings.values()):
        if booking["compensation_status"] not in ("ELIGIBLE_PENDING", "ELECTED_REFUND", "ELECTED_CREDIT"):
            continue
        segs = booking_segments(booking["id"])
        if not segs:
            continue
        current_final = max(segs, key=lambda s: (s["seq_no"], s["created_at"]))
        if current_final["flight_id"] != flight["id"]:
            continue
        orig_segs = original_segments(booking["id"])
        if not orig_segs:
            continue
        orig_final_seg = max(orig_segs, key=lambda s: s["seq_no"])
        orig_final_flight = db.flights.get(orig_final_seg["flight_id"])
        if orig_final_flight is None or orig_final_flight["orig_sched_arr_utc"] is None:
            continue
        delay_min = (flight["act_arr_utc"] - orig_final_flight["orig_sched_arr_utc"]).total_seconds() / 60.0
        delay_min = int(delay_min)
        base = compensation_base_cents(booking["id"])
        # reduction: REBOOKED via own-metal option AND delay < 240
        rebooked_own_metal = _rebooked_via_own_metal(booking)
        if rebooked_own_metal and delay_min < REDUCTION_THRESHOLD_MINUTES:
            from decimal import Decimal, ROUND_HALF_UP
            amount = int((Decimal(base) * Decimal("0.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        else:
            amount = base
        booking["compensation_amount_cents"] = amount
        booking["compensation_basis"] = "FINAL"
        booking["updated_at"] = now()

    # Arrival-delay eligibility sweep.
    if event is not None and event["is_controllable"] and flight["act_arr_utc"] and flight["orig_sched_arr_utc"]:
        delay = (flight["act_arr_utc"] - flight["orig_sched_arr_utc"]).total_seconds() / 60.0
        if delay >= COMP_DELAY_THRESHOLD_MINUTES:
            for seg in list(db.booking_segments.values()):
                if seg["flight_id"] != flight["id"]:
                    continue
                # PRD: every booking holding a segment on this flight in CONFIRMED
                # gains eligibility. Segments just flowed to FLOWN above; the sweep
                # targets bookings whose segment was CONFIRMED at arrival time,
                # which now reads as FLOWN. Treat FLOWN from this arrival as the
                # swept set, plus any still-CONFIRMED (defensive).
                if seg["segment_status"] not in ("CONFIRMED", "FLOWN"):
                    continue
                booking = db.bookings.get(seg["booking_id"])
                if booking is None:
                    continue
                if booking["compensation_status"] == "NONE":
                    _grant_eligibility(booking, "FINAL")


def _rebooked_via_own_metal(booking):
    """True when the booking reached REBOOKED via an own-metal (non-interline)
    committed option."""
    for case in db.reaccommodation_cases.values():
        if case["booking_id"] != booking["id"]:
            continue
        if case["case_status"] != "COMMITTED" or not case["committed_option_id"]:
            continue
        opt = db.reaccommodation_options.get(case["committed_option_id"])
        if opt is not None and not opt["is_interline"]:
            return True
    return False


def run_booking_cancel(booking):
    """Voluntary/involuntary booking cancel (PRD §3.4): non-FLOWN segments become
    CANCELLED and release seats; open case VOIDED; its PROPOSED options EXPIRED."""
    for seg in booking_segments(booking["id"]):
        if seg["segment_status"] == "FLOWN":
            continue
        if seg["segment_status"] in ("CANCELLED",):
            continue
        # release seats for this segment if it currently holds seats
        if seg["segment_status"] in ("CONFIRMED", "DISRUPTED"):
            _release_segment_seats(seg, booking["party_size"])
        seg["segment_status"] = "CANCELLED"
        touch(seg)
    # open case voided
    for case in db.reaccommodation_cases.values():
        if case["booking_id"] == booking["id"] and case["case_status"] in ("QUEUED", "OFFERED", "ESCALATED"):
            for opt in db.reaccommodation_options.values():
                if opt["case_id"] == case["id"] and opt["option_status"] == "PROPOSED":
                    opt["option_status"] = "EXPIRED"
                    touch(opt)
            case["case_status"] = "VOIDED"
            touch(case)
    booking["booking_status"] = "CANCELLED"
    touch(booking)
    recompute_refund_credit(booking)
    # event affected counters may change (booking no longer DISRUPTED)
    for ev in db.disruption_events.values():
        recompute_event_affected(ev["id"])


def _release_segment_seats(seg, party_size):
    """Decrease seats_sold (or interline committed) on the segment's flight cabin."""
    flight = db.flights.get(seg["flight_id"])
    if flight is None:
        return
    for ci in db.cabin_inventories.values():
        if ci["flight_id"] == flight["id"] and ci["cabin"] == seg["cabin"]:
            # interline segments were committed via interline_seats_committed
            if seg["reaccommodation_case_id"]:
                case = db.reaccommodation_cases.get(seg["reaccommodation_case_id"])
                opt = (db.reaccommodation_options.get(case["committed_option_id"])
                       if case and case["committed_option_id"] else None)
                if opt is not None and opt["is_interline"]:
                    ci["interline_seats_committed"] = max(0, ci["interline_seats_committed"] - party_size)
                    touch(ci)
                    return
            ci["seats_sold"] = max(0, ci["seats_sold"] - party_size)
            touch(ci)
            return
