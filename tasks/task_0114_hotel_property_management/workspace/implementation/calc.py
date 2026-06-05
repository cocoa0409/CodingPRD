"""Calculations: nightly rate, room charges, no-show, folio money, block
counters, availability, corporate outstanding balance.

All money is integer cents (PRD §2.8). The only rounding is the per-night PCT
rate, rounded half up to whole cents BEFORE multiplication by nights.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

RATE_FLOOR_CENTS = 0


# ----------------------------------------------------------------------------
# Date helpers
# ----------------------------------------------------------------------------
def parse_date(s):
    """Parse a strict YYYY-MM-DD date. Returns a datetime.date or None if invalid."""
    if not isinstance(s, str) or len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    try:
        y, m, d = s[0:4], s[5:7], s[8:10]
        if not (y.isdigit() and m.isdigit() and d.isdigit()):
            return None
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def add_one_day(s):
    d = parse_date(s)
    return (d + timedelta(days=1)).isoformat()


def nights_between(arrival, departure):
    a = parse_date(arrival)
    dp = parse_date(departure)
    return (dp - a).days


def covers_night(arrival, departure, stay_date):
    """True iff arrival_date <= stay_date < departure_date (half-open interval)."""
    a = parse_date(arrival)
    dp = parse_date(departure)
    s = parse_date(stay_date)
    return a <= s < dp


# ----------------------------------------------------------------------------
# Nightly rate (PRD §3.4)
# ----------------------------------------------------------------------------
def nightly_rate(rate_plan, room_type):
    """Per-night rate in cents for a rate plan against a room type.

    PCT: round_half_up(base * (1 + adjustment_value/100)) per night.
    FLAT: base + adjustment_value, no rounding.
    Then floored at 0.
    """
    base = room_type["base_rate_cents"]
    if rate_plan["adjustment_mode"] == "PCT":
        factor = Decimal(1) + (Decimal(rate_plan["adjustment_value"]) / Decimal(100))
        raw = Decimal(base) * factor
        nightly = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:  # FLAT
        nightly = base + rate_plan["adjustment_value"]
    if nightly < RATE_FLOOR_CENTS:
        nightly = RATE_FLOOR_CENTS
    return nightly


# ----------------------------------------------------------------------------
# Forward room charge (PRD §3.6) — used at confirm and paid upgrade
# ----------------------------------------------------------------------------
def room_charge_forward(reservation, effective_room_type_id):
    rate_plan = db.rate_plans[reservation["rate_plan_id"]]
    room_type = db.room_types[effective_room_type_id]
    nightly = nightly_rate(rate_plan, room_type)
    total = nightly * reservation["nights"]
    if rate_plan["kind"] == "PACKAGE":
        total += rate_plan["package_fee_cents"]
    return total


# ----------------------------------------------------------------------------
# Folio money (PRD §3.6 / calculations.folio_balance)
# ----------------------------------------------------------------------------
def folio_money(folio_id):
    """Recompute folio money fields from POSTED incidentals.

    room_charges_cents = sum of POSTED NIGHT_AUDIT CHARGE lines.
    incidentals_cents  = sum of POSTED AGENT lines (PAYMENT stored negative).
    payments_cents     = sum of POSTED PAYMENT lines (negative).
    balance_cents      = room_charges_cents + incidentals_cents.
    VOIDED lines excluded from every sum.
    """
    room_charges = 0
    incidentals = 0
    payments = 0
    for inc in db.incidentals.values():
        if inc["folio_id"] != folio_id:
            continue
        if inc["status"] != "POSTED":
            continue
        amt = inc["amount_cents"]
        if inc["posted_by_kind"] == "NIGHT_AUDIT" and inc["kind"] == "CHARGE":
            room_charges += amt
        if inc["posted_by_kind"] == "AGENT":
            incidentals += amt
            if inc["kind"] == "PAYMENT":
                payments += amt
    return {
        "room_charges_cents": room_charges,
        "incidentals_cents": incidentals,
        "payments_cents": payments,
        "balance_cents": room_charges + incidentals,
    }


# ----------------------------------------------------------------------------
# Block counters (PRD §3.2 / calculations.block_pickup, block_wash)
# ----------------------------------------------------------------------------
def block_pickup(group_block_id):
    """picked_up_rooms = reservations on block whose status NOT IN {CANCELLED, NO_SHOW}."""
    count = 0
    for rv in db.reservations.values():
        if rv["group_block_id"] == group_block_id and rv["status"] not in (
            "CANCELLED",
            "NO_SHOW",
        ):
            count += 1
    return count


def block_washed(blocked_rooms, picked_up_rooms):
    return max(blocked_rooms - picked_up_rooms, 0)


# ----------------------------------------------------------------------------
# Availability (PRD §3.3 / calculations.availability_sellable)
# ----------------------------------------------------------------------------
def sellable_count(hotel, room_type):
    """floor(physical_inventory * (1 + overbooking_allowance_pct)) - OUT_OF_ORDER rooms."""
    allowance = Decimal(str(hotel["overbooking_allowance_pct"]))
    raw = Decimal(room_type["physical_inventory"]) * (Decimal(1) + allowance)
    base = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
    ooo = 0
    for r in db.rooms.values():
        if (
            r["room_type_id"] == room_type["id"]
            and r["housekeeping_status"] == "OUT_OF_ORDER"
        ):
            ooo += 1
    return base - ooo


def _reservation_type(rv):
    return rv["effective_room_type_id"] or rv["room_type_id"]


def sold_count(room_type_id, stay_date, exclude_reservation_id=None):
    """Reservations of this type covering stay_date, status NOT IN {CANCELLED, NO_SHOW}."""
    count = 0
    for rv in db.reservations.values():
        if exclude_reservation_id is not None and rv["id"] == exclude_reservation_id:
            continue
        if _reservation_type(rv) != room_type_id:
            continue
        if rv["status"] in ("CANCELLED", "NO_SHOW"):
            continue
        if covers_night(rv["arrival_date"], rv["departure_date"], stay_date):
            count += 1
    return count


# ----------------------------------------------------------------------------
# Corporate outstanding balance (PRD §3.7 / calculations.corporate_outstanding)
# ----------------------------------------------------------------------------
def corporate_outstanding(corporate_account_id):
    """Sum of balance_cents of CORPORATE folios whose reservation is CHECKED_OUT
    and bound to this account."""
    total = 0
    for f in db.folios.values():
        if f["bill_to"] != "CORPORATE":
            continue
        rv = db.reservations.get(f["reservation_id"])
        if rv is None:
            continue
        if rv["corporate_account_id"] != corporate_account_id:
            continue
        if rv["status"] != "CHECKED_OUT":
            continue
        total += folio_money(f["id"])["balance_cents"]
    return total
