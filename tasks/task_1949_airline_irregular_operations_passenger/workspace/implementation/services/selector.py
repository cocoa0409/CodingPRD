"""Recovery option selection (calculation recovery_option_selection), case commit,
and voucher entitlement services."""

from datetime import timedelta

import errors
from db import db, new_id, now

from services.core import (
    MIN_CONNECT_MINUTES,
    booking_segments,
    compensation_base_cents,
    crew_legality_reeval,
    original_segments,
    post_cost_entry,
    queue_comm,
    recompute_crew_coverage,
    recompute_event_affected,
    round_half_up_cents,
    stamp_new,
    touch,
)

RECOVERY_WINDOW_HOURS = 48
MAX_OPTIONS = 3
INTERLINE_KM_RATE_CENTS = 5

CABINS = {"ECONOMY", "PREMIUM", "BUSINESS", "FIRST"}


def _cabin_inventory(flight_id, cabin):
    for ci in db.cabin_inventories.values():
        if ci["flight_id"] == flight_id and ci["cabin"] == cabin:
            return ci
    return None


def _seats_available(ci):
    return ci["capacity"] - ci["seats_sold"] - ci["interline_seats_committed"]


def _find_disrupted_segment(case):
    """The disrupted segment anchoring option generation: the booking's segment in
    DISRUPTED status. Falls back to the highest-seq original non-terminal segment."""
    booking = db.bookings.get(case["booking_id"])
    if booking is None:
        return None
    segs = booking_segments(booking["id"])
    disrupted = [s for s in segs if s["segment_status"] == "DISRUPTED"]
    if disrupted:
        disrupted.sort(key=lambda s: s["seq_no"])
        return disrupted[0]
    cancelled = [s for s in segs if s["segment_status"] == "CANCELLED"
                 and s["reaccommodation_case_id"] is None]
    if cancelled:
        cancelled.sort(key=lambda s: s["seq_no"])
        return cancelled[0]
    return None


def _booking_final_destination(booking):
    orig = original_segments(booking["id"])
    if not orig:
        return None
    last = max(orig, key=lambda s: s["seq_no"])
    f = db.flights.get(last["flight_id"])
    return f["destination"] if f else None


def _original_final_arr(booking):
    orig = original_segments(booking["id"])
    if not orig:
        return None
    last = max(orig, key=lambda s: s["seq_no"])
    f = db.flights.get(last["flight_id"])
    return f["orig_sched_arr_utc"] if f else None


def _original_dep_anchor(booking, disrupted_seg):
    """Original scheduled departure anchor for the 48h recovery window: the
    disrupted segment's flight's orig_sched_dep_utc."""
    f = db.flights.get(disrupted_seg["flight_id"])
    return f["orig_sched_dep_utc"] if f else None


def generate_options(case, include_interline):
    """Run the selector. Returns list of newly created option rows.
    Raises ERR_NO_REACCOM_OPTIONS when the candidate set is empty."""
    booking = db.bookings.get(case["booking_id"])
    if booking is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Booking not found")
    disrupted_seg = _find_disrupted_segment(case)
    if disrupted_seg is None:
        errors.raise_error(errors.ERR_NO_REACCOM_OPTIONS, "No disrupted segment to reaccommodate")
    disrupted_flight = db.flights.get(disrupted_seg["flight_id"])
    if disrupted_flight is None:
        errors.raise_error(errors.ERR_NO_REACCOM_OPTIONS, "No disrupted flight")
    origin = disrupted_flight["origin"]
    final_dest = _booking_final_destination(booking)
    dep_anchor = _original_dep_anchor(booking, disrupted_seg)
    orig_final_arr = _original_final_arr(booking)
    window_end = dep_anchor + timedelta(hours=RECOVERY_WINDOW_HOURS) if dep_anchor else None
    cabin = booking["cabin"]
    party = booking["party_size"]

    candidates = []  # each: dict(legs=[(flight, cabin, agreement|None)], is_interline, agreement)

    # --- one-leg own-metal candidates ---
    for f in db.flights.values():
        if f["flight_status"] not in ("SCHEDULED", "DELAYED"):
            continue
        if f["origin"] != origin or f["destination"] != final_dest:
            continue
        if f["operating_carrier"] != "OC":
            continue
        if window_end is not None and f["sched_dep_utc"] > window_end:
            continue
        ci = _cabin_inventory(f["id"], cabin)
        if ci is None or _seats_available(ci) < party:
            continue
        candidates.append({
            "legs": [{"flight": f, "cabin": cabin, "agreement": None}],
            "is_interline": False,
            "agreement": None,
        })

    # --- two-leg own-metal candidates (connections respect MIN_CONNECT_MINUTES) ---
    first_legs = [f for f in db.flights.values()
                  if f["flight_status"] in ("SCHEDULED", "DELAYED")
                  and f["origin"] == origin and f["operating_carrier"] == "OC"
                  and (window_end is None or f["sched_dep_utc"] <= window_end)]
    second_legs = [f for f in db.flights.values()
                   if f["flight_status"] in ("SCHEDULED", "DELAYED")
                   and f["destination"] == final_dest and f["operating_carrier"] == "OC"]
    for f1 in first_legs:
        if f1["destination"] == final_dest:
            continue  # that's the one-leg case
        ci1 = _cabin_inventory(f1["id"], cabin)
        if ci1 is None or _seats_available(ci1) < party:
            continue
        for f2 in second_legs:
            if f2["id"] == f1["id"]:
                continue
            if f2["origin"] != f1["destination"]:
                continue
            gap = (f2["sched_dep_utc"] - f1["sched_arr_utc"]).total_seconds() / 60.0
            if gap < MIN_CONNECT_MINUTES:
                continue
            ci2 = _cabin_inventory(f2["id"], cabin)
            if ci2 is None or _seats_available(ci2) < party:
                continue
            candidates.append({
                "legs": [{"flight": f1, "cabin": cabin, "agreement": None},
                         {"flight": f2, "cabin": cabin, "agreement": None}],
                "is_interline": False,
                "agreement": None,
            })

    # --- interline candidates (first leg on partner metal under an agreement) ---
    if include_interline:
        for f in db.flights.values():
            if f["flight_status"] not in ("SCHEDULED", "DELAYED"):
                continue
            if f["origin"] != origin or f["destination"] != final_dest:
                continue
            if f["operating_carrier"] == "OC":
                continue
            if window_end is not None and f["sched_dep_utc"] > window_end:
                continue
            for ag in db.interline_agreements.values():
                if ag["agreement_status"] != "ACTIVE":
                    continue
                if ag["partner_carrier"] != f["operating_carrier"]:
                    continue
                if ag["origin"] != origin or ag["destination"] != final_dest:
                    continue
                if cabin not in ag["cabin_map"]:
                    continue
                ci = _cabin_inventory(f["id"], cabin)
                committed = ci["interline_seats_committed"] if ci else 0
                if committed + party > ag["seats_quota_per_flight"]:
                    continue
                candidates.append({
                    "legs": [{"flight": f, "cabin": cabin, "agreement": ag}],
                    "is_interline": True,
                    "agreement": ag,
                })

    if not candidates:
        errors.raise_error(errors.ERR_NO_REACCOM_OPTIONS, "Selector candidate set is empty")

    # rank: stops*1e6 + minutes_until_final_arrival*10 + (1 if interline else 0)
    gen_now = now()

    def rank_key(cand):
        legs = cand["legs"]
        stops = len(legs) - 1
        final_arr = legs[-1]["flight"]["sched_arr_utc"]
        minutes_until = (final_arr - gen_now).total_seconds() / 60.0
        score = stops * 1000000 + int(minutes_until * 10) + (1 if cand["is_interline"] else 0)
        first_dep_created = legs[0]["flight"]["created_at"]
        return (score, first_dep_created)

    candidates.sort(key=rank_key)
    candidates = candidates[:MAX_OPTIONS]

    # supersede prior PROPOSED options
    for opt in db.reaccommodation_options.values():
        if opt["case_id"] == case["id"] and opt["option_status"] == "PROPOSED":
            opt["option_status"] = "EXPIRED"
            touch(opt)

    new_options = []
    for cand in candidates:
        legs = cand["legs"]
        first_f = legs[0]["flight"]
        last_f = legs[-1]["flight"]
        proj_delay = 0
        if orig_final_arr is not None and last_f["sched_arr_utc"] is not None:
            proj_delay = int((last_f["sched_arr_utc"] - orig_final_arr).total_seconds() // 60)
        interline_fare = 0
        agreement_id = None
        if cand["is_interline"]:
            agreement_id = cand["agreement"]["id"]
            interline_fare = party * first_f["distance_km"] * INTERLINE_KM_RATE_CENTS
        score, _ = rank_key(cand)
        opt = stamp_new({
            "case_id": case["id"],
            "interline_agreement_id": agreement_id,
            "is_interline": cand["is_interline"],
            "legs": [{"flight_id": leg["flight"]["id"], "cabin": leg["cabin"]} for leg in legs],
            "est_first_dep_utc": first_f["sched_dep_utc"],
            "est_final_arr_utc": last_f["sched_arr_utc"],
            "projected_arrival_delay_minutes": proj_delay,
            "interline_fare_cents": interline_fare,
            "rank_score": score,
            "option_status": "PROPOSED",
        })
        db.reaccommodation_options[opt["id"]] = opt
        new_options.append(opt)

    case["case_status"] = "OFFERED"
    touch(case)
    queue_comm(case["booking_id"], case["disruption_event_id"], "REBOOK_OFFER")
    return new_options


def commit_option(case, option):
    """Execute the commit side effects (preconditions already checked by route)."""
    booking = db.bookings.get(case["booking_id"])
    party = booking["party_size"]

    # option ACCEPTED; siblings REJECTED
    option["option_status"] = "ACCEPTED"
    touch(option)
    for opt in db.reaccommodation_options.values():
        if opt["case_id"] == case["id"] and opt["id"] != option["id"] and opt["option_status"] == "PROPOSED":
            opt["option_status"] = "REJECTED"
            touch(opt)
    case["committed_option_id"] = option["id"]
    case["case_status"] = "COMMITTED"
    touch(case)

    # Booking DISRUPTED -> REBOOKED: old DISRUPTED segments become REBOOKED
    old_segments = [s for s in booking_segments(booking["id"]) if s["segment_status"] == "DISRUPTED"]
    replaced_cancelled = [s for s in booking_segments(booking["id"])
                          if s["segment_status"] == "CANCELLED"
                          and s["reaccommodation_case_id"] is None]
    # seat move out of old flights: segments being replaced release seats_sold
    for seg in old_segments + replaced_cancelled:
        _decrement_seats(seg, party)
    for seg in old_segments:
        seg["segment_status"] = "REBOOKED"
        touch(seg)

    # new CONFIRMED segments from the option legs
    existing = booking_segments(booking["id"])
    max_seq = max((s["seq_no"] for s in existing), default=0)
    for i, leg in enumerate(option["legs"]):
        seg = stamp_new({
            "booking_id": booking["id"],
            "flight_id": leg["flight_id"],
            "seq_no": max_seq + 1 + i,
            "cabin": leg["cabin"],
            "segment_status": "CONFIRMED",
            "reaccommodation_case_id": case["id"],
        })
        db.booking_segments[seg["id"]] = seg
        ci = _cabin_inventory(leg["flight_id"], leg["cabin"])
        if ci is not None:
            if option["is_interline"]:
                ci["interline_seats_committed"] += party
            else:
                ci["seats_sold"] += party
            touch(ci)

    booking["booking_status"] = "REBOOKED"
    touch(booking)

    # provisional compensation recompute from projected delay — only when the
    # booking's money axis is already engaged (eligibility granted). Reduction:
    # own-metal rebooking with delay < 240 -> half base.
    if booking["compensation_status"] in ("ELIGIBLE_PENDING", "ELECTED_REFUND", "ELECTED_CREDIT"):
        base = compensation_base_cents(booking["id"])
        delay = option["projected_arrival_delay_minutes"]
        if not option["is_interline"] and delay < 240:
            from decimal import Decimal, ROUND_HALF_UP
            amount = int((Decimal(base) * Decimal("0.5")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        else:
            amount = base
        booking["compensation_amount_cents"] = amount
        booking["compensation_basis"] = "PROVISIONAL"
        booking["updated_at"] = now()

    # interline cost accrual
    if option["is_interline"]:
        agreement = db.interline_agreements.get(option["interline_agreement_id"])
        rate = agreement["settlement_rate_pct"] if agreement else 0
        amount = round_half_up_cents(option["interline_fare_cents"] * rate / 100.0)
        post_cost_entry(case["disruption_event_id"], "INTERLINE", option["id"],
                        "ACCRUAL", amount, note="interline commit")

    # crew coverage recomputed on every leg flight
    for leg in option["legs"]:
        f = db.flights.get(leg["flight_id"])
        if f is not None:
            crew_legality_reeval(f)

    queue_comm(booking["id"], case["disruption_event_id"], "REBOOK_CONFIRMED")
    if case["disruption_event_id"]:
        recompute_event_affected(case["disruption_event_id"])


def _decrement_seats(seg, party):
    ci = _cabin_inventory(seg["flight_id"], seg["cabin"])
    if ci is None:
        return
    ci["seats_sold"] = max(0, ci["seats_sold"] - party)
    touch(ci)


# ---------------------------------------------------------------------------
# Voucher entitlement (calculation voucher_entitlement)
# ---------------------------------------------------------------------------

HOTEL_WINDOW_THRESHOLD_HOURS = 8
HOTEL_NIGHT_CAP_CENTS = 15000
MAX_HOTEL_NIGHTS = 3
MEAL_WINDOW_HOURS = 4
MEAL_RATE_CENTS = 1500
TRANSPORT_FLAT_CENTS = 5000
BOOKING_VOUCHER_CAP_CENTS = 40000


def disruption_window_hours(booking):
    """Whole hours from the disrupted flight's cancelled_at (or, for delay-only,
    the moment the booking first became DISRUPTED) to the committed option's
    est_first_dep_utc. Floor for partial hours."""
    committed_case = None
    for case in db.reaccommodation_cases.values():
        if case["booking_id"] == booking["id"] and case["case_status"] == "COMMITTED":
            committed_case = case
            break
    if committed_case is None or not committed_case["committed_option_id"]:
        return None
    option = db.reaccommodation_options.get(committed_case["committed_option_id"])
    if option is None or option["est_first_dep_utc"] is None:
        return None
    start = _disruption_start(booking)
    if start is None:
        return None
    delta = (option["est_first_dep_utc"] - start).total_seconds() / 3600.0
    return int(delta) if delta >= 0 else int(delta)


def _disruption_start(booking):
    """Cancelled flight's cancelled_at, else the booking's first-disruption time
    (approximated by the queued_at of its earliest reaccommodation case)."""
    segs = booking_segments(booking["id"])
    # cancelled flight anchor
    for seg in segs:
        f = db.flights.get(seg["flight_id"])
        if f is not None and f["flight_status"] == "CANCELLED" and f["cancelled_at"] is not None:
            return f["cancelled_at"]
    cases = [c for c in db.reaccommodation_cases.values() if c["booking_id"] == booking["id"]]
    if cases:
        cases.sort(key=lambda c: c["created_at"])
        return cases[0]["queued_at"]
    return None
