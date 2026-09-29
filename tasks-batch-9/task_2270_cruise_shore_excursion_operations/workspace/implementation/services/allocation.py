"""Channel allocation, the pre-cruise release and seat accounting (PRD 3.5)."""

from db import db
from util import minutes_between

PRECRUISE_RELEASE_MINUTES = 2880

LIVE_SEAT_HOLDING = ("BOOKED", "TICKETED", "CHECKED_IN", "COMPLETED", "NO_SHOW")


def bookings_of(departure_id):
    rows = [b for b in db.bookings.values() if b["departure_id"] == departure_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def sold_counts(departure):
    precruise = 0
    onboard = 0
    for booking in bookings_of(departure["id"]):
        if booking["fulfillment_status"] in ("CANCELLED_BY_GUEST", "CANCELLED_BY_LINE"):
            continue
        if booking["channel"] == "PRE_CRUISE":
            precruise += booking["party_size"]
        else:
            onboard += booking["party_size"]
    return precruise, onboard


def precruise_released(departure):
    """True once the clock is within 2880 minutes of the meeting time."""
    return minutes_between(db.now(), departure["meeting_time_utc"]) <= PRECRUISE_RELEASE_MINUTES


def effective_allocations(departure):
    precruise_sold, _onboard_sold = sold_counts(departure)
    if precruise_released(departure):
        return precruise_sold, departure["total_capacity"] - precruise_sold
    return departure["precruise_allocation"], departure["onboard_allocation"]


def recompute_seats(departure):
    precruise_sold, onboard_sold = sold_counts(departure)
    departure["precruise_sold_seats"] = precruise_sold
    departure["onboard_sold_seats"] = onboard_sold
    departure["seats_available_total"] = departure["total_capacity"] - precruise_sold - onboard_sold
    eff_pre, eff_on = effective_allocations(departure)
    departure["effective_precruise_available"] = max(0, eff_pre - precruise_sold)
    departure["effective_onboard_available"] = max(0, eff_on - onboard_sold)
    return departure


def channel_available(departure, channel):
    recompute_seats(departure)
    if channel == "PRE_CRUISE":
        return departure["effective_precruise_available"]
    return departure["effective_onboard_available"]


def return_seats(departure, booking):
    """Give a cancelled booking's seats back, moving the bucket after the release."""
    if booking["channel"] == "PRE_CRUISE" and precruise_released(departure):
        departure["precruise_allocation"] = departure["precruise_allocation"] - booking["party_size"]
        departure["onboard_allocation"] = departure["onboard_allocation"] + booking["party_size"]
    recompute_seats(departure)
    return departure
