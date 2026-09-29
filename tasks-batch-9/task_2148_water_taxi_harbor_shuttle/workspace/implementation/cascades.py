"""Landing-fee postings (PRD 3.8) and the two cascades (PRD 2.10, 3.7, 3.9)."""

import calc
from store import store


def _trip_slots_in_order(trip, status="RESERVED"):
    rows = [s for s in store.dock_slots.values()
            if s["trip_id"] == trip["id"] and s["status"] == status]
    rows.sort(key=lambda s: (s["_start_dt"], s["_seq"]))
    return rows


def _select_rebate_bp(slot, pre_posting_accrued):
    if slot.get("rebate_bp") == 10000:
        return 10000
    if pre_posting_accrued >= calc.REBATE_TIER2_FLOOR_CENTS:
        return calc.REBATE_TIER2_BP
    if pre_posting_accrued >= calc.REBATE_TIER1_FLOOR_CENTS:
        return calc.REBATE_TIER1_BP
    return 0


def post_provisional_fees(trip):
    """Variant PROVISIONAL — posted by depart.  The monthly cap is not evaluated."""
    total = 0
    touched = {}
    for slot in _trip_slots_in_order(trip):
        dock = store.docks[slot["dock_id"]]
        pax_basis = 0 if slot["purpose"] == "LAYOVER" else trip["booked_pax"]
        berth_minutes = int((slot["_end_dt"] - slot["_start_dt"]).total_seconds() // 60)
        if berth_minutes < 0:
            berth_minutes = 0
        gross = (berth_minutes * dock["berth_minute_rate_cents"]
                 + pax_basis * dock["landing_fee_per_pax_cents"])
        pre_posting = dock["accrued_fee_cents"]
        rebate_bp = _select_rebate_bp(slot, pre_posting)
        fee = gross - calc.apply_bp(gross, rebate_bp)

        slot["projected_fee_cents"] = fee
        dock["accrued_fee_cents"] = dock["accrued_fee_cents"] + fee
        slot["berth_minutes"] = berth_minutes
        slot["rebate_bp"] = rebate_bp
        slot["pax_basis"] = pax_basis
        store.touch(slot)
        total += fee
        touched[dock["id"]] = dock
    for dock in touched.values():
        store.touch(dock)
    return total


def post_final_fees(trip):
    """Variant FINAL — Cascade B.  Reversal, posting, cap flip, sibling pre-lock."""
    total = 0
    touched = {}
    for slot in _trip_slots_in_order(trip):
        dock = store.docks[slot["dock_id"]]

        # (1) reverse the provisional posting
        dock["accrued_fee_cents"] = dock["accrued_fee_cents"] - slot["projected_fee_cents"]
        slot["projected_fee_cents"] = 0

        pax_basis = 0 if slot["purpose"] == "LAYOVER" else trip["boarded_pax"]
        departure = trip["_actual_departure_dt"]
        berth_minutes = int((departure - slot["_start_dt"]).total_seconds() // 60)
        if berth_minutes < 0:
            berth_minutes = 0
        gross = (berth_minutes * dock["berth_minute_rate_cents"]
                 + pax_basis * dock["landing_fee_per_pax_cents"])

        # (2)(3) rebate selected from the post-reversal accrual alone
        pre_posting = dock["accrued_fee_cents"]
        rebate_bp = _select_rebate_bp(slot, pre_posting)

        # (4)(5) compute and post
        fee = gross - calc.apply_bp(gross, rebate_bp)
        dock["accrued_fee_cents"] = dock["accrued_fee_cents"] + fee

        # (6) monthly cap — FINAL only
        capped_now = False
        if dock["accrued_fee_cents"] >= dock["monthly_fee_cap_cents"]:
            overflow = dock["accrued_fee_cents"] - dock["monthly_fee_cap_cents"]
            fee = fee - overflow
            dock["accrued_fee_cents"] = dock["monthly_fee_cap_cents"]
            dock["fee_status"] = "CAPPED"
            capped_now = True

        slot["landing_fee_cents"] = fee
        slot["status"] = "CONSUMED"
        slot["berth_minutes"] = berth_minutes
        slot["rebate_bp"] = rebate_bp
        slot["pax_basis"] = pax_basis
        store.touch(slot)
        total += fee
        touched[dock["id"]] = dock

        if capped_now:
            for sibling in store.dock_slots.values():
                if (sibling["dock_id"] == dock["id"]
                        and sibling["status"] == "RESERVED"
                        and sibling.get("rebate_bp") != 10000):
                    sibling["rebate_bp"] = 10000
                    store.touch(sibling)

    for dock in touched.values():
        store.touch(dock)
    return total


def cascade_a(day):
    """Suspension cascade: cancel every non-terminal trip on the day."""
    trips = [t for t in store.trips.values()
             if t["service_day_id"] == day["id"]
             and t["operational_status"] in ("SCHEDULED", "BOARDING")]
    trips.sort(key=lambda t: (t["_departure_dt"], t["_seq"]))
    for trip in trips:
        _cancel_trip(trip)


def _cancel_trip(trip):
    # link 1 — the trip itself
    trip["operational_status"] = "CANCELLED"
    trip["settlement_status"] = "VOID"
    trip["cancellation_reason"] = "POSTURE_SUSPENDED"
    trip["seats_committed"] = 0
    store.touch(trip)

    # link 2a — berths
    touched_docks = {}
    slots = [s for s in store.dock_slots.values()
             if s["trip_id"] == trip["id"] and s["status"] == "RESERVED"]
    for slot in store.ordered(slots):
        projected = slot["projected_fee_cents"]
        if projected:
            dock = store.docks[slot["dock_id"]]
            dock["accrued_fee_cents"] = dock["accrued_fee_cents"] - projected
            touched_docks[dock["id"]] = dock
        slot["projected_fee_cents"] = 0
        slot["landing_fee_cents"] = 0
        slot["status"] = "VOIDED"
        store.touch(slot)
    for dock in touched_docks.values():
        store.touch(dock)

    # link 2b / link 3 — bookings and ride credits
    bookings = [b for b in store.bookings.values()
                if b["trip_id"] == trip["id"]
                and b["status"] in ("OFFERED", "CONFIRMED", "BOARDED")]
    for booking in store.ordered(bookings):
        booking["interrupted_from_status"] = booking["status"]
        booking["status"] = "INTERRUPTED"
        if booking["redemption_status"] == "REDEEMED":
            ride_pass = store.ride_passes.get(booking.get("ride_pass_id"))
            if ride_pass is not None:
                ride_pass["rides_remaining"] = ride_pass["rides_remaining"] + booking["party_size"]
                if ride_pass["status"] == "EXHAUSTED":
                    ride_pass["status"] = "ACTIVE"
                store.touch(ride_pass)
            booking["redemption_status"] = "RESTORED"
        store.touch(booking)

    calc.recompute_seats_committed(trip)
