"""Alternative-departure selection policy (PRD 3.7)."""

from datetime import timedelta

from db import db
from services.allocation import recompute_seats
from services.eligibility import age_at_meeting, passes

MEETING_SETUP_MINUTES = 15


def sellable_candidates(booking, cancelled_departure):
    cancelled_excursion = db.excursions.get(cancelled_departure["excursion_id"])
    guest = db.guests.get(booking["guest_id"])
    now = db.now()
    earliest_meeting = now + timedelta(minutes=MEETING_SETUP_MINUTES)

    candidates = []
    for candidate in db.departures.values():
        if candidate["id"] == cancelled_departure["id"]:
            continue
        if candidate["port_call_id"] != cancelled_departure["port_call_id"]:
            continue
        if candidate["status"] != "SELLING":
            continue
        excursion = db.excursions.get(candidate["excursion_id"])
        if excursion is None or excursion["catalog_status"] != "PUBLISHED":
            continue
        recompute_seats(candidate)
        if candidate["seats_available_total"] < booking["party_size"]:
            continue
        if candidate["meeting_time_utc"] < earliest_meeting:
            continue
        if guest is None:
            continue
        age = age_at_meeting(guest, candidate["meeting_time_utc"])
        if not passes(guest, excursion, age, booking["language_choice"],
                      booking.get("medical_warning_acknowledged")):
            continue
        candidates.append(candidate)
    return candidates, cancelled_excursion


def select_alternative(booking, cancelled_departure):
    candidates, cancelled_excursion = sellable_candidates(booking, cancelled_departure)
    if not candidates:
        return None

    nominated_id = cancelled_excursion.get("alternative_excursion_id") if cancelled_excursion else None
    if nominated_id:
        nominated = [c for c in candidates if c["excursion_id"] == nominated_id]
        if nominated:
            nominated.sort(key=lambda d: (d["meeting_time_utc"], d["created_at"], d["_seq"]))
            return nominated[0]

    base_price = cancelled_excursion["base_price_cents"] if cancelled_excursion else 0

    def distance(candidate):
        excursion = db.excursions.get(candidate["excursion_id"])
        return abs(excursion["base_price_cents"] - base_price)

    candidates.sort(key=lambda d: (distance(d), d["meeting_time_utc"], d["created_at"], d["_seq"]))
    return candidates[0]
