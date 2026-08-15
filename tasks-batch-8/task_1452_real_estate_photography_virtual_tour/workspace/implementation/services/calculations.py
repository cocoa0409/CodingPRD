"""Calculation rules from SCAFFOLD §1.3 / PRD §3."""

import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import store
from timeutil import day_key


# --- shoot_duration constants ---
BASE_BY_PACKAGE = {"STANDARD": 60, "PREMIUM": 90, "LUXURY": 120}
INCLUDED_PHOTOS = {"STANDARD": 25, "PREMIUM": 40, "LUXURY": 60}
OVERAGE_STEP_PHOTOS = 5
OVERAGE_STEP_MINUTES = 10

# --- provisional_quote constants ---
BASE_RATE_CENTS = {"STANDARD": 15000, "PREMIUM": 25000, "LUXURY": 40000}
OVERAGE_RATE_CENTS_PER_PHOTO = 300
TOUR_RATE_CENTS = {"BRANDED": 12000, "UNBRANDED": 14000}
TWILIGHT_PREMIUM_BPS = 2500
VOLUME_DISCOUNT_FLOOR_CENTS = 50000
VOLUME_DISCOUNT_BPS = 1000

# --- addon_pricing constants ---
ADDON_RATE_CENTS = {
    "DRONE_STILLS": 20000,
    "DRONE_VIDEO": 35000,
    "RUSH_EDIT": 15000,
    "VIRTUAL_STAGING": 10000,
    "TWILIGHT_UPGRADE": 0,
}
ADDON_EXTRA_MINUTES = {
    "DRONE_STILLS": 30,
    "DRONE_VIDEO": 45,
    "RUSH_EDIT": 0,
    "VIRTUAL_STAGING": 0,
    "TWILIGHT_UPGRADE": 0,
}
DRONE_KINDS = {"DRONE_STILLS", "DRONE_VIDEO"}

# --- turnaround constants ---
WEATHER_SLA_EXTENSION_HOURS = 24

# --- final invoice constants ---
LATE_DELIVERY_PENALTY_BPS = 1500
WEATHER_CREDIT_CAP_BPS = 3000

# --- license fee constants ---
LICENSE_FEE_CENTS = {"MLS_COMPLIANT": 0, "STANDARD_MARKETING": 5000, "EXTENDED": 15000}
UNBRANDED_SURCHARGE_CENTS = 4000

# --- revision fee constants ---
FREE_REVISION_ROUNDS = 2
PAID_REVISION_BASE_CENTS = 7500

REVISION_HARD_CAP = 4
RESCHEDULE_HARD_CAP = 3


def _round_half_up_cents(value):
    """Round a Decimal/numeric to whole cents, HALF_UP."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def shoot_duration_minutes(equipment_package, photo_count, is_twilight, market):
    """shoot_duration rule: base + overage, or twilight override."""
    if is_twilight:
        return market["twilight_slot_minutes"]
    base = BASE_BY_PACKAGE[equipment_package]
    overage = max(0, photo_count - INCLUDED_PHOTOS[equipment_package])
    extra = math.ceil(overage / OVERAGE_STEP_PHOTOS) * OVERAGE_STEP_MINUTES
    return base + extra


def addon_price_cents(kind, market):
    """addon_pricing rule: rate * market multiplier, HALF_UP whole cents.
    TWILIGHT_UPGRADE is priced at 0 (captured inside quote)."""
    if kind == "TWILIGHT_UPGRADE":
        return 0
    raw = ADDON_RATE_CENTS[kind]
    return _round_half_up_cents(Decimal(raw) * Decimal(market["pricing_multiplier_bps"]) / Decimal(10000))


def addon_extra_minutes(kind):
    return ADDON_EXTRA_MINUTES[kind]


def compute_scheduled_end(booking):
    """scheduled_end_utc = scheduled_start + shoot_duration + sum(active addon extra_minutes).

    shoot_duration_minutes already reflects twilight override.
    """
    extra = 0
    for a in store.addons.values():
        if a["booking_id"] == booking["id"] and a["state"] == "ACTIVE":
            extra += a["extra_minutes"]
    total = booking["shoot_duration_minutes"] + extra
    return booking["scheduled_start_utc"] + timedelta(minutes=total)


def provisional_quote(booking, market):
    """Compute locked quote per provisional_quote rule (per-line HALF_UP, then sum).

    Returns (quote_cents, addon_lines_total_at_submit).
    """
    mult = Decimal(market["pricing_multiplier_bps"])
    base_cents = _round_half_up_cents(
        Decimal(BASE_RATE_CENTS[booking["equipment_package"]]) * mult / Decimal(10000)
    )
    overage = max(0, booking["photo_count"] - INCLUDED_PHOTOS[booking["equipment_package"]])
    overage_cents = _round_half_up_cents(
        Decimal(overage * OVERAGE_RATE_CENTS_PER_PHOTO) * mult / Decimal(10000)
    )
    tour_line_cents = 0
    if booking["wants_virtual_tour"] and booking["tour_variant"]:
        tour_line_cents = _round_half_up_cents(
            Decimal(TOUR_RATE_CENTS[booking["tour_variant"]]) * mult / Decimal(10000)
        )
    twilight_cents = 0
    if booking["is_twilight"]:
        twilight_cents = _round_half_up_cents(
            Decimal(base_cents) * Decimal(TWILIGHT_PREMIUM_BPS) / Decimal(10000)
        )
    addon_lines = 0
    for a in store.addons.values():
        if a["booking_id"] == booking["id"] and a["state"] == "ACTIVE":
            addon_lines += a["price_cents"]
    volume_discount = 0
    if addon_lines >= VOLUME_DISCOUNT_FLOOR_CENTS:
        volume_discount = _round_half_up_cents(
            Decimal(addon_lines) * Decimal(VOLUME_DISCOUNT_BPS) / Decimal(10000)
        )
    quote = base_cents + overage_cents + tour_line_cents + twilight_cents + addon_lines - volume_discount
    return quote, addon_lines


def license_fee_cents(tier, tour_variant):
    base = LICENSE_FEE_CENTS[tier]
    surcharge = UNBRANDED_SURCHARGE_CENTS if tour_variant == "UNBRANDED" else 0
    return base + surcharge


def paid_revision_fee_cents(market):
    return _round_half_up_cents(
        Decimal(PAID_REVISION_BASE_CENTS) * Decimal(market["pricing_multiplier_bps"]) / Decimal(10000)
    )


def weather_credit_apply(booking, market):
    """Apply a weather reschedule credit event.

    Returns the marginal credit actually applied on this event.
    Mutates booking.weather_credit_cents.
    """
    quote = booking["provisional_quote_cents"]
    raw = _round_half_up_cents(
        Decimal(quote) * Decimal(market["weather_reschedule_credit_bps"]) / Decimal(10000)
    )
    cap = _round_half_up_cents(Decimal(quote) * Decimal(WEATHER_CREDIT_CAP_BPS) / Decimal(10000))
    accumulated = booking["weather_credit_cents"] + raw
    new_total = min(accumulated, cap)
    applied = new_total - booking["weather_credit_cents"]
    booking["weather_credit_cents"] = new_total
    return applied


def final_invoice(booking, market, license_grant):
    """final_invoice rule. Returns final_invoice_cents."""
    quote = booking["provisional_quote_cents"]
    addons_at_submit = booking.get("addons_at_submit_cents", 0)
    addons_now = 0
    rush_price = 0
    for a in store.addons.values():
        if a["booking_id"] == booking["id"] and a["state"] == "ACTIVE":
            addons_now += a["price_cents"]
            if a["kind"] == "RUSH_EDIT":
                rush_price = a["price_cents"]

    # Late delivery detection
    late = False
    if booking["delivered_at_utc"] is not None and booking["delivery_due_utc"] is not None:
        late = booking["delivered_at_utc"] > booking["delivery_due_utc"]

    rush_discount = 0
    has_rush = any(
        a["booking_id"] == booking["id"] and a["state"] == "ACTIVE" and a["kind"] == "RUSH_EDIT"
        for a in store.addons.values()
    )
    if has_rush and late:
        rush_discount = rush_price

    revision_fees = 0
    for r in store.revisions.values():
        if r["booking_id"] == booking["id"] and r["state"] == "RESOLVED":
            revision_fees += r["fee_cents"]

    late_penalty = 0
    if late:
        late_penalty = _round_half_up_cents(
            Decimal(quote) * Decimal(LATE_DELIVERY_PENALTY_BPS) / Decimal(10000)
        )

    weather_credit = booking["weather_credit_cents"]
    lic_fee = license_grant["fee_cents"] if license_grant else 0

    total = (
        quote
        + (addons_now - addons_at_submit)
        - rush_discount
        + revision_fees
        - late_penalty
        - weather_credit
        + lic_fee
    )
    if total < 0:
        total = 0
    return total


def turnaround_deadline(booking, market, marked_at):
    """turnaround_deadline rule: base + rush halving + staging + weather extension."""
    base_hours = market["standard_turnaround_hours"]
    has_rush = any(
        a["booking_id"] == booking["id"] and a["state"] == "ACTIVE" and a["kind"] == "RUSH_EDIT"
        for a in store.addons.values()
    )
    has_staging = any(
        a["booking_id"] == booking["id"] and a["state"] == "ACTIVE" and a["kind"] == "VIRTUAL_STAGING"
        for a in store.addons.values()
    )
    if has_rush:
        base_hours = math.ceil(base_hours / 2)
    if has_staging:
        base_hours = base_hours + 12
    weather_events = sum(
        1
        for e in store.reschedule_events.values()
        if e["booking_id"] == booking["id"] and e["kind"] == "WEATHER"
    )
    extension = min(weather_events, 2) * WEATHER_SLA_EXTENSION_HOURS
    return marked_at + timedelta(hours=base_hours + extension)


# ---------- photographer_overlap_check ----------

def _booking_window(b):
    return b["scheduled_start_utc"], b["scheduled_end_utc"]


def photographer_conflict(photographer, candidate_booking, new_start, new_end, market):
    """Return True if candidate window [new_start, new_end) conflicts for photographer.

    - Excludes the candidate booking itself.
    - Only considers photographer bookings in {ASSIGNED, AUTHORIZATION_PENDING, CONFIRMED}.
    - Twilight-vs-twilight same UTC evening => always conflict (raw interval test).
    - Otherwise widened by buffer, open-interval intersection.
    """
    buffer = timedelta(minutes=market["travel_buffer_minutes"])
    cand_twilight = candidate_booking["is_twilight"]
    for other in store.bookings.values():
        if other["id"] == candidate_booking["id"]:
            continue
        if other.get("assigned_photographer_id") != photographer["id"]:
            continue
        if other["state"] not in ("ASSIGNED", "AUTHORIZATION_PENDING", "CONFIRMED"):
            continue
        o_start, o_end = _booking_window(other)
        # Twilight exclusivity: both twilight, same UTC day -> always conflict
        if cand_twilight and other["is_twilight"]:
            if day_key(new_start) == day_key(o_start):
                return True
        # Widened open-interval intersection
        w_start = new_start - buffer
        w_end = new_end + buffer
        if w_start < o_end and o_start < w_end:
            return True
    return False


def photographer_day_minutes(photographer, exclude_booking_id, day):
    """Sum of committed shoot minutes for photographer on given UTC day,
    excluding one booking (used when revalidating)."""
    total = 0
    for other in store.bookings.values():
        if other["id"] == exclude_booking_id:
            continue
        if other.get("assigned_photographer_id") != photographer["id"]:
            continue
        if other["state"] not in ("ASSIGNED", "AUTHORIZATION_PENDING", "CONFIRMED"):
            continue
        if day_key(other["scheduled_start_utc"]) == day:
            delta = other["scheduled_end_utc"] - other["scheduled_start_utc"]
            total += int(delta.total_seconds() // 60)
    return total


def capacity_ok(photographer, candidate_booking, new_start, new_end):
    """Check day-capacity: existing day minutes + new minutes <= max.

    Strictly greater triggers rejection; equal is allowed.
    """
    day = day_key(new_start)
    existing = photographer_day_minutes(photographer, candidate_booking["id"], day)
    new_minutes = int((new_end - new_start).total_seconds() // 60)
    return (existing + new_minutes) <= photographer["max_shoot_minutes_per_day"]


def recompute_committed_minutes(photographer):
    """Recompute photographer.committed_minutes_by_day from live bookings."""
    new_map = {}
    for other in store.bookings.values():
        if other.get("assigned_photographer_id") != photographer["id"]:
            continue
        if other["state"] not in ("ASSIGNED", "AUTHORIZATION_PENDING", "CONFIRMED"):
            continue
        d = day_key(other["scheduled_start_utc"])
        minutes = int((other["scheduled_end_utc"] - other["scheduled_start_utc"]).total_seconds() // 60)
        new_map[d] = new_map.get(d, 0) + minutes
    photographer["committed_minutes_by_day"] = new_map
