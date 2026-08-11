"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All money is integer cents;
round half up at each pinned rounding point. Never float for money."""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import store

# ---- constants -------------------------------------------------------------
WEEKEND_MULTIPLIER = Decimal("1.15")
INSTITUTIONAL_DISCOUNT_RATE = Decimal("0.15")
LIABILITY_SURCHARGE_RATE = Decimal("0.03")
DEPOSIT_RATE = Decimal("0.30")
COMPLIANCE_PENALTY_RATE = Decimal("0.20")

PONY_RIDE_FLAT_CENTS = 12000
PONY_RIDE_INCLUDED_MIN = 60
PONY_RIDE_OVERAGE_PER_MIN = 200
REPTILE_SHOW_FLAT_CENTS = 15000
REPTILE_SHOW_INCLUDED_MIN = 45
REPTILE_SHOW_OVERAGE_PER_MIN = 250

ZONE_TABLE = {
    "ZONE_A": (5000, 25),
    "ZONE_B": (9000, 50),
    "ZONE_C": (14000, 100),
}
OVERAGE_RATE_CENTS_PER_MI = 85
TRAILER_CAPACITY_ANIMALS = 6
TRAILER_FEE_CENTS = 3000
HARD_SURFACE_MULTIPLIER = Decimal("1.25")

GUESTS_PER_STATION = 20
REPTILE_EXTRA_STATION = 1
PETTING_ANIMALS_PER_HANDLER = 4
CHILDREN_PER_STAFF = 8

DAILY_CAPACITY_MINUTES = 480
CONFIRM_GATE = 60

TERMINAL_BOOKING_STATES = {
    "INVOICED", "CANCELLED_CUSTOMER", "CANCELLED_WEATHER", "CANCELLED_COMPLIANCE",
}


def rhu(value):
    """Round half up to integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_weekend(dt):
    """Saturday/Sunday by the event's calendar date (start_time, UTC)."""
    return dt.weekday() >= 5


def addon_fee_cents(addon):
    d = addon["duration_minutes"]
    if addon["addon_type"] == "PONY_RIDE":
        if d <= PONY_RIDE_INCLUDED_MIN:
            return PONY_RIDE_FLAT_CENTS
        return PONY_RIDE_FLAT_CENTS + PONY_RIDE_OVERAGE_PER_MIN * (d - PONY_RIDE_INCLUDED_MIN)
    # REPTILE_SHOW
    if d <= REPTILE_SHOW_INCLUDED_MIN:
        return REPTILE_SHOW_FLAT_CENTS
    return REPTILE_SHOW_FLAT_CENTS + REPTILE_SHOW_OVERAGE_PER_MIN * (d - REPTILE_SHOW_INCLUDED_MIN)


def travel_setup_fee(venue, animal_count):
    base, included = ZONE_TABLE[venue["travel_zone"]]
    overage_miles = max(0, venue["distance_miles"] - included)
    trailer_count = max(1, math.ceil(animal_count / TRAILER_CAPACITY_ANIMALS))
    raw = base + overage_miles * OVERAGE_RATE_CENTS_PER_MI + trailer_count * TRAILER_FEE_CENTS
    if venue["surface_type"] == "PAVEMENT":
        return rhu(Decimal(raw) * HARD_SURFACE_MULTIPLIER)
    return raw


def guest_surcharge(guests):
    if guests <= 20:
        return 0
    if guests <= 50:
        return 1500
    if guests <= 100:
        return 3500
    return 6000


def handwash_requirement(venue, guests, addons):
    required = math.ceil(guests / GUESTS_PER_STATION) if venue["requires_handwash_stations"] else 0
    if any(a["addon_type"] == "REPTILE_SHOW" for a in addons):
        required += REPTILE_EXTRA_STATION
    return required


def staff_requirement(booking_animals, addons, child_guest_count):
    petting_count = sum(1 for ba in booking_animals if ba["role"] == "PETTING_ZOO")
    handler_slots = max(1, math.ceil(petting_count / PETTING_ANIMALS_PER_HANDLER))
    if any(a["addon_type"] == "PONY_RIDE" for a in addons):
        handler_slots += 1
    if any(a["addon_type"] == "REPTILE_SHOW" for a in addons):
        handler_slots += 1
    return max(handler_slots, math.ceil(child_guest_count / CHILDREN_PER_STAFF))


def compliance_score(venue, animals, stations_in_scope, guests_in_scope, addons_in_scope):
    required_stations = handwash_requirement(venue, guests_in_scope, addons_in_scope)
    load = {"LARGE": 15, "MEDIUM": 10, "SMALL": 5}
    score = 100
    for an in animals:
        score -= load[an["weight_class"]]
    if venue["venue_type"] == "INDOOR":
        score -= 10
    if not venue["water_access"]:
        score -= 8
    score -= 5 * max(0, required_stations - stations_in_scope)
    score -= max(0, guests_in_scope - 30) // 10
    calm = sum(1 for an in animals if an["temperament_tier"] == 3)
    score += min(10, 2 * calm)
    return max(0, min(100, score))


def booking_addons(booking_id):
    return [a for a in store.addon_requests.values() if a["booking_id"] == booking_id]


def booking_animals(booking_id):
    return [ba for ba in store.booking_animals.values() if ba["booking_id"] == booking_id]


def in_scope(booking, variant):
    """Input sets for the provisional (quote) and final (invoice) variants."""
    bas = booking_animals(booking["id"])
    addons = booking_addons(booking["id"])
    if variant == "provisional":
        bas = [ba for ba in bas if ba["status"] in ("PROPOSED", "CONFIRMED")]
        addons = [a for a in addons if a["status"] in ("REQUESTED", "APPROVED")]
        guests = booking["guest_count"]
        stations = booking["planned_handwash_stations"]
    else:  # final
        bas = [ba for ba in bas if ba["status"] == "CONFIRMED"]
        addons = [a for a in addons if a["status"] == "APPROVED"]
        guests = booking["actual_attendance_count"]
        stations = booking["actual_handwash_stations"]
    animals = [store.animals[ba["animal_id"]] for ba in bas]
    return bas, addons, animals, guests, stations


def booking_price(booking, variant):
    """The pinned eight-step pricing evaluation. Returns a dict of components."""
    venue = store.venues[booking["venue_id"]]
    bas, addons, animals, guests, _stations = in_scope(booking, variant)

    # (1) animal lines: round per line, then sum.
    weekend = is_weekend(booking["start_time"])
    animal_subtotal = 0
    for an in animals:
        line = an["base_event_fee_cents"]
        if weekend:
            line = rhu(Decimal(line) * WEEKEND_MULTIPLIER)
        animal_subtotal += line

    # (2) add-on lines.
    addon_subtotal = sum(addon_fee_cents(a) for a in addons)

    # (3) subtotal.
    subtotal = animal_subtotal + addon_subtotal

    # (4) institutional discount (computed FIRST from the raw subtotal).
    if booking["booking_type"] in ("SCHOOL_PROGRAM", "LIBRARY_PROGRAM"):
        discount = rhu(INSTITUTIONAL_DISCOUNT_RATE * subtotal)
    else:
        discount = 0

    # (5) liability surcharge (computed SECOND from the discounted subtotal).
    surcharge = rhu(LIABILITY_SURCHARGE_RATE * (subtotal - discount))

    # (6) travel & setup fee.
    travel = travel_setup_fee(venue, len(animals))

    # (7) guest tier surcharge (boundaries inclusive at the lower edge).
    guest_sur = guest_surcharge(guests)

    # (8) total.
    total = subtotal - discount + surcharge + travel + guest_sur

    return {
        "animal_subtotal_cents": animal_subtotal,
        "addon_subtotal_cents": addon_subtotal,
        "discount_cents": discount,
        "surcharge_cents": surcharge,
        "travel_fee_cents": travel,
        "guest_surcharge_cents": guest_sur,
        "total_cents": total,
    }


def deposit_amount(quoted_total_cents):
    return rhu(DEPOSIT_RATE * quoted_total_cents)
