"""Core domain logic: calculations, derived fields, state propagation, cascades.

Every behavior here traces to a verbatim PRD sentence (PRD §2-§3).
Money is integer cents; fractional-rate multiplications use Decimal ROUND_HALF_UP.
"""
from decimal import Decimal, ROUND_HALF_UP

import clock
import errors
from db import db, new_id, iso_ms
from errors import ApiError

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------
VENUE_DEFAULT_MIN_ITEMS = 2
MIN_ITEM_UNIT_PRICE_CENTS = 1000
CANCEL_FEE_CENTS = 1500
LATE_CANCEL_GRACE_MINUTES = 120
MAX_COUNTER_ROUNDS = 3
DEFAULT_HOUSE_FEE_PCT = 0.20
DEFAULT_DOORS_BUFFER_MINUTES = 30
DEFAULT_DEPOSIT_PCT = 0.25
DEFAULT_MAX_TABLES = 4


# ---------------------------------------------------------------------------
# Money helper
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to whole cents, half away from zero (PRD §2.4)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------
def stamp_create(record):
    now_ms = iso_ms()
    record["created_at"] = now_ms
    record["updated_at"] = now_ms
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on any mutation incl. cascades."""
    record["updated_at"] = iso_ms()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Existence helpers (ERR_NOT_FOUND, validated left-to-right)
# ---------------------------------------------------------------------------
def get_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise errors.not_found()
    return rec


# ===========================================================================
# Calculations (scaffold §1.3)
# ===========================================================================
def compute_ticket_charge(is_comp, price_cents, party_size):
    if is_comp:
        return 0
    return price_cents * party_size


def compute_minimum_due(reservation, tier, table=None, waived=False):
    """Per-seat minimum precedence (first non-null wins):
       1. tier.min_items_override
       2. table.min_items_per_seat (if table assigned & section kind == TABLE)
       3. VENUE_DEFAULT_MIN_ITEMS (=2)
    A comp whose originating guest-list entry waived the minimum owes 0.
    """
    if reservation.get("is_comp") and waived:
        per_seat_min = 0
    else:
        per_seat_min = None
        if tier.get("min_items_override") is not None:
            per_seat_min = tier["min_items_override"]
        elif table is not None and table.get("min_items_per_seat") is not None:
            per_seat_min = table["min_items_per_seat"]
        else:
            per_seat_min = VENUE_DEFAULT_MIN_ITEMS
    return per_seat_min * MIN_ITEM_UNIT_PRICE_CENTS * reservation["party_size"]


def compute_buyout_deposit(deposit_pct, buyout_fee_cents):
    return round_half_up(Decimal(str(deposit_pct)) * Decimal(buyout_fee_cents))


# ---------------------------------------------------------------------------
# refund base (PRD §3.7)
# ---------------------------------------------------------------------------
def _refund_base(res):
    settlement = res["settlement_status"]
    collected = res["ticket_charge_cents"] if settlement in ("TICKET_PAID", "MINIMUM_MET") else 0
    collected_minimum = min(res["items_consumed_cents"], res["minimum_due_cents"]) \
        if settlement == "MINIMUM_MET" else 0
    return collected + collected_minimum


def compute_refund_cancel(res, show):
    base = _refund_base(res)
    # Patron-initiated cancel keeps a cancellation fee unless it lands well
    # before doors: if now <= starts_at - LATE_CANCEL_GRACE_MINUTES, full refund.
    starts_at = clock.parse_iso8601(show["starts_at"])
    grace_cutoff = starts_at - _minutes(LATE_CANCEL_GRACE_MINUTES)
    if clock.now() <= grace_cutoff:
        return base
    return max(0, base - CANCEL_FEE_CENTS)


def compute_refund_show_cancel(res):
    # Full refund, fee waived.
    return _refund_base(res)


def compute_refund_exchange(res, new_charge):
    base = _refund_base(res)
    return max(0, base - new_charge)


def _minutes(n):
    from datetime import timedelta
    return timedelta(minutes=n)


# ===========================================================================
# Derived field maintenance (PRD §2.5)
# ===========================================================================
def recompute_ga_sold_count(show):
    total = 0
    for r in db.reservations.values():
        if r["show_id"] != show["id"]:
            continue
        section = db.sections.get(r["section_id"])
        if section is None or section["kind"] != "GA":
            continue
        if r["booking_status"] in ("BOOKED", "SEATED", "CHECKED_IN"):
            total += r["party_size"]
    show["ga_sold_count"] = total
    return total


def section_sold_count(show_id, section_id):
    total = 0
    for r in db.reservations.values():
        if r["show_id"] == show_id and r["section_id"] == section_id \
                and r["booking_status"] in ("BOOKED", "SEATED", "CHECKED_IN"):
            total += r["party_size"]
    return total


def recompute_assigned_table_count(server):
    count = 0
    for t in db.tables.values():
        if t.get("assigned_server_id") == server["id"] and t["status"] != "RETIRED":
            count += 1
    server["assigned_table_count"] = count
    return count


def recompute_is_private(show):
    is_private = any(
        pe["show_id"] == show["id"] and pe["status"] in ("HELD", "CONFIRMED")
        for pe in db.private_events.values()
    )
    show["is_private"] = is_private
    return is_private


def recompute_venue_posture(venue):
    """OPEN normally; RECONCILING while any of the venue's shows is SETTLING;
    CLOSED only when manually closed."""
    if venue.get("_closed"):
        venue["posture"] = "CLOSED"
        return
    any_settling = any(
        s["venue_id"] == venue["id"] and s["status"] == "SETTLING"
        for s in db.shows.values()
    )
    venue["posture"] = "RECONCILING" if any_settling else "OPEN"


# ---------------------------------------------------------------------------
# GA SOLD_OUT auto-transition (PRD §3.5, §2.5)
# ---------------------------------------------------------------------------
def _ga_sections(show_id):
    return [s for s in db.sections.values()
            if s["show_id"] == show_id and s["kind"] == "GA"]


def maybe_sold_out(show):
    """ON_SALE -> SOLD_OUT when no GA section has remaining capacity."""
    if show["status"] != "ON_SALE":
        return
    ga_sections = _ga_sections(show["id"])
    if not ga_sections:
        return
    any_remaining = False
    for sec in ga_sections:
        remaining = sec["ga_capacity"] - section_sold_count(show["id"], sec["id"])
        if remaining > 0:
            any_remaining = True
            break
    if not any_remaining:
        show["status"] = "SOLD_OUT"
        touch(show)


def maybe_back_on_sale(show):
    """SOLD_OUT -> ON_SALE when some GA section has remaining capacity."""
    if show["status"] != "SOLD_OUT":
        return
    ga_sections = _ga_sections(show["id"])
    for sec in ga_sections:
        remaining = sec["ga_capacity"] - section_sold_count(show["id"], sec["id"])
        if remaining > 0:
            show["status"] = "ON_SALE"
            touch(show)
            return
