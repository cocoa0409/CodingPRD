"""Calculation rules (PRD 2.5, 2.8, 2.9, 2.10 and section 3).

Money is integer cents throughout.  Every fractional intermediate is carried as
an exact Fraction and rounded half up only at the positions the PRD names.
"""
import math
from datetime import timedelta
from fractions import Fraction

from store import now, rows_of, touch
from timeutil import (fmt_instant, iso_week_key, local_day, local_minutes,
                      parse_instant, whole_minutes)

# ---------------------------------------------------------------- constants ---
FACILITY_FEE_CENTS_PER_TICKET = 150
MAX_TICKETS_PER_ORDER = 10

OFFER_VALIDITY_HOURS = 72
MAX_NEGOTIATION_ROUNDS = 4

MIN_PRORATION_FLOOR = Fraction(60, 100)
SLIDING_SCALE_EXHIBITOR_SPLIT_COMPLEMENT = Fraction(90, 100)
MIN_RUN_PENALTY_RATE = Fraction(50, 100)

ROLLING_WINDOW_DAYS = 365
MEMBERSHIP_TERM_DAYS = 365
FISCAL_YEAR_START = parse_instant("2026-07-01T00:00:00.000Z")
TIER_BASIC_CENTS = 6000
TIER_SUPPORTER_CENTS = 15000
TIER_DONOR_CIRCLE_CENTS = 50000

TIER_RANK = {"PROSPECT": 0, "BASIC": 1, "SUPPORTER": 2, "DONOR_CIRCLE": 3}
DISCOUNT_PCT = {"PROSPECT": 0.00, "BASIC": 0.10, "SUPPORTER": 0.15, "DONOR_CIRCLE": 0.25}
DISCOUNT_FRACTION = {
    "PROSPECT": Fraction(0),
    "BASIC": Fraction(10, 100),
    "SUPPORTER": Fraction(15, 100),
    "DONOR_CIRCLE": Fraction(25, 100),
}
ADVANCE_ACCESS_HOURS = {"PROSPECT": 0, "BASIC": 24, "SUPPORTER": 48, "DONOR_CIRCLE": 168}
COMP_TICKETS_GRANTED = {"PROSPECT": 0, "BASIC": 0, "SUPPORTER": 2, "DONOR_CIRCLE": 6}

SLOT_GRANULARITY_MINUTES = 15
GAP_CAP_MINUTES = 120
SPACING_CAP = 12
PRIME_START_LOCAL = 18 * 60
PRIME_END_LOCAL = 21 * 60
SHOULDER_START_LOCAL = 15 * 60

OCCUPYING_ASSET_STATUSES = ("REQUESTED", "IN_TRANSIT", "RECEIVED", "INGESTING")
ASSET_CHAIN = ("REQUESTED", "IN_TRANSIT", "RECEIVED", "INGESTING", "INGESTED", "RETURNED")


def round_half_up(value):
    """Round an exact Fraction (or int) half up to the nearest integer."""
    frac = Fraction(value)
    num, den = frac.numerator, frac.denominator
    if frac >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def share_fraction(value):
    """Exact Fraction for a decimal share such as 0.60 (never float error)."""
    if isinstance(value, Fraction):
        return value
    return Fraction(str(value))


# ------------------------------------------------------------- venue-local ---

def venue_offset(venue):
    return venue.get("utc_offset_minutes") or 0


def venue_local_day(venue, instant):
    return local_day(instant, venue_offset(venue))


def venue_local_minutes(venue, instant):
    return local_minutes(instant, venue_offset(venue))


def venue_week(venue, instant):
    return iso_week_key(instant, venue_offset(venue))


# ------------------------------------------------------- screen_slot_block ---

def content_minutes(venue, title, extra_minutes):
    return venue["trailer_reel_minutes"] + title["runtime_minutes"] + (extra_minutes or 0)


def compute_block(venue, title, start_at, extra_minutes=0):
    end_at = start_at + timedelta(minutes=content_minutes(venue, title, extra_minutes))
    blocked_until = end_at + timedelta(minutes=venue["turnaround_minutes"])
    return end_at, blocked_until


def find_collision(venue_id, start_at, blocked_until, exclude_id=None):
    """Half-open occupancy [start_at, blocked_until); touching blocks are legal."""
    for other in rows_of("showtimes"):
        if other["venue_id"] != venue_id:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        if start_at < other["blocked_until"] and other["start_at"] < blocked_until:
            return other
    return None


# -------------------------------------------------- weekly_programming_balance ---

def week_rows(venue, instant, exclude_id=None):
    week = venue_week(venue, instant)
    out = []
    for st in rows_of("showtimes"):
        if st["venue_id"] != venue["id"] or st["status"] == "CANCELLED":
            continue
        if exclude_id is not None and st["id"] == exclude_id:
            continue
        if venue_week(venue, st["start_at"]) == week:
            out.append(st)
    return out


def weekly_balance_admits(venue, start_at, strand, exclude_id=None):
    existing = week_rows(venue, start_at, exclude_id)
    total_after = len(existing) + 1
    first_run_after = sum(1 for st in existing if st["strand"] == "FIRST_RUN")
    if strand == "FIRST_RUN":
        first_run_after += 1
    share = share_fraction(venue["max_first_run_share"])
    ceiling = math.ceil(Fraction(total_after) * share)
    return first_run_after <= ceiling


def repertory_count_of_week(venue, start_at, exclude_id=None):
    return sum(1 for st in week_rows(venue, start_at, exclude_id)
               if st["strand"] == "REPERTORY_SERIES")


# ------------------------------------------------ kdm coverage and overlap ---

def key_covers(key, showtime):
    return (key["dcp_asset_id"] == showtime["dcp_asset_id"]
            and key["venue_id"] == showtime["venue_id"]
            and key["status"] == "ISSUED"
            and key["valid_from"] <= showtime["start_at"]
            and key["valid_until"] >= showtime["end_at"])


def find_key_overlap(dcp_asset_id, venue_id, valid_from, valid_until, exclude_id=None):
    """Closed validity intervals: touching IS an overlap."""
    for key in rows_of("keys"):
        if key["dcp_asset_id"] != dcp_asset_id or key["venue_id"] != venue_id:
            continue
        if key["status"] != "ISSUED":
            continue
        if exclude_id is not None and key["id"] == exclude_id:
            continue
        if valid_from <= key["valid_until"] and key["valid_from"] <= valid_until:
            return key
    return None


# ----------------------------------------------------- ingest_lane_capacity ---

def ingest_lane_admits(venue, window_start, window_end):
    existing = [a for a in rows_of("assets")
                if a["venue_id"] == venue["id"] and a["status"] in OCCUPYING_ASSET_STATUSES]
    instants = {window_start, window_end}
    for asset in existing:
        instants.add(asset["ingest_window_start_at"])
        instants.add(asset["ingest_window_end_at"])
    evaluated = [t for t in instants if window_start <= t <= window_end]
    peak = 0
    for moment in evaluated:
        concurrency = 1 + sum(
            1 for asset in existing
            if asset["ingest_window_start_at"] <= moment <= asset["ingest_window_end_at"])
        peak = max(peak, concurrency)
    return peak <= venue["dcp_ingest_lane_count"]


# ---------------------------------------------- membership standing (PRD 3.7) ---

def tier_for_cents(cents):
    if cents >= TIER_DONOR_CIRCLE_CENTS:
        return "DONOR_CIRCLE"
    if cents >= TIER_SUPPORTER_CENTS:
        return "SUPPORTER"
    if cents >= TIER_BASIC_CENTS:
        return "BASIC"
    return "PROSPECT"


def member_comp_used(member_id):
    return sum(o["comp_quantity"] for o in rows_of("orders")
               if o["member_id"] == member_id and o["status"] in ("RESERVED", "PAID"))


def rolling_cents(member, clock):
    window_start = clock - timedelta(days=ROLLING_WINDOW_DAYS)
    return sum(d["amount_cents"] for d in member["donations"]
               if window_start <= d["received_at"] <= clock)


def fiscal_cents(member, clock):
    return sum(d["amount_cents"] for d in member["donations"]
               if FISCAL_YEAR_START <= d["received_at"] <= clock)


def refresh_member(member):
    """Re-derive every standing field against the logical clock.

    A read re-derives but never counts as a mutation, so this never bumps
    version; callers that genuinely mutate the row bump it themselves.
    """
    clock = now()
    rolling = rolling_cents(member, clock)
    fiscal = fiscal_cents(member, clock)
    rolling_tier = tier_for_cents(rolling)
    fiscal_tier = tier_for_cents(fiscal)
    effective = rolling_tier if TIER_RANK[rolling_tier] >= TIER_RANK[fiscal_tier] else fiscal_tier
    member["rolling_donation_cents"] = rolling
    member["fiscal_ytd_donation_cents"] = fiscal
    member["rolling_tier"] = rolling_tier
    member["fiscal_tier"] = fiscal_tier
    member["effective_tier"] = effective
    member["discount_pct"] = DISCOUNT_PCT[effective]
    member["advance_access_hours"] = ADVANCE_ACCESS_HOURS[effective]
    granted = COMP_TICKETS_GRANTED[effective]
    member["comp_tickets_granted"] = granted
    member["comp_tickets_remaining"] = granted - member_comp_used(member["id"])
    if member["donations"]:
        latest = max(d["received_at"] for d in member["donations"])
        member["expires_at"] = latest + timedelta(days=MEMBERSHIP_TERM_DAYS)
    else:
        member["expires_at"] = None
    return member


# ------------------------------------------------ ticket order pricing (3.8) ---

def price_order(showtime, member, quantity, comp_quantity, apply_credit):
    gross_unit = showtime["base_price_cents"] + showtime["surcharge_cents"]
    paid_quantity = quantity - comp_quantity
    if member is None:
        discount = Fraction(0)
    else:
        discount = DISCOUNT_FRACTION[member["effective_tier"]]
    unit_price = round_half_up(Fraction(gross_unit) * (Fraction(1) - discount))
    line_subtotal = unit_price * paid_quantity
    facility_fee = FACILITY_FEE_CENTS_PER_TICKET * quantity
    before_credit = line_subtotal + facility_fee
    if apply_credit and member is not None:
        applied_credit = min(member["credit_balance_cents"], before_credit)
    else:
        applied_credit = 0
    total = before_credit - applied_credit
    return {
        "unit_price_cents": unit_price,
        "line_subtotal_cents": line_subtotal,
        "facility_fee_cents": facility_fee,
        "applied_credit_cents": applied_credit,
        "total_cents": total,
    }


# --------------------------------------------------- showtime rollup (2.10) ---

def showtime_orders(showtime_id):
    return [o for o in rows_of("orders") if o["showtime_id"] == showtime_id]


def recompute_showtime(showtime, venue=None):
    """Recompute the four rollup fields from surviving orders (PRD 2.10).

    Returns True when any stored field actually moved.
    """
    from validate import find
    if venue is None:
        venue = find("venues", showtime["venue_id"])
    orders = showtime_orders(showtime["id"])
    seats_sold = sum(o["quantity"] for o in orders if o["status"] in ("RESERVED", "PAID"))
    gross = sum(o["total_cents"] for o in orders if o["status"] == "PAID")
    admissions = sum(o["quantity"] for o in orders if o["status"] == "PAID")
    sellable = venue["seat_capacity"] - venue["house_hold_seats"]
    seats_available = max(0, sellable - seats_sold)
    changed = False
    for field, value in (("seats_sold", seats_sold), ("seats_available", seats_available),
                         ("gross_cents", gross), ("admissions_count", admissions)):
        if showtime.get(field) != value:
            showtime[field] = value
            changed = True
    # The sale dimension oscillates on its own (PRD 3.8); no caller asks for it.
    if showtime["status"] == "SCHEDULED":
        if showtime["sale_status"] == "ON_SALE" and seats_available == 0:
            showtime["sale_status"] = "SOLD_OUT"
            changed = True
        elif showtime["sale_status"] == "SOLD_OUT" and seats_available >= 1:
            showtime["sale_status"] = "ON_SALE"
            changed = True
    return changed


def recompute_clearance(clearance):
    used = sum(1 for st in rows_of("showtimes")
               if st["clearance_id"] == clearance["id"]
               and st["status"] in ("SCHEDULED", "COMPLETED"))
    remaining = max(0, clearance["max_screenings"] - used)
    if clearance["screenings_used"] == used and clearance["screenings_remaining"] == remaining:
        return False
    clearance["screenings_used"] = used
    clearance["screenings_remaining"] = remaining
    return True


def recompute_booking_count(booking):
    count = sum(1 for st in rows_of("showtimes")
                if st["booking_id"] == booking["id"]
                and st["status"] in ("SCHEDULED", "COMPLETED"))
    if booking["scheduled_showtime_count"] == count:
        return False
    booking["scheduled_showtime_count"] = count
    return True


# ----------------------------------------- min-run compliance (PRD 3.9 close) ---

def proration_factor(days, min_run_days):
    """0 with nothing played, else min(1, max(0.60, days / min_run_days))."""
    if days == 0:
        return Fraction(0)
    ratio = Fraction(days, min_run_days)
    return min(Fraction(1), max(MIN_PRORATION_FLOOR, ratio))


def distinct_playing_days(venue, showtimes):
    return len({venue_local_day(venue, st["start_at"]) for st in showtimes})


def booking_min_run_compliance(booking, venue):
    """The eight normative steps of PRD 3.9, in the stated order."""
    completed = [st for st in rows_of("showtimes")
                 if st["booking_id"] == booking["id"] and st["status"] == "COMPLETED"]
    actual_playing_days = distinct_playing_days(venue, completed)
    min_run_days = booking["min_run_days"]
    shortfall = max(0, min_run_days - actual_playing_days)
    factor = proration_factor(actual_playing_days, min_run_days)
    house_nut_applied = round_half_up(Fraction(booking["house_nut_cents"]) * factor)
    if actual_playing_days == 0:
        daily_nut = round_half_up(Fraction(booking["house_nut_cents"], min_run_days))
    else:
        daily_nut = round_half_up(Fraction(house_nut_applied, actual_playing_days))
    penalty = round_half_up(Fraction(shortfall) * Fraction(daily_nut) * MIN_RUN_PENALTY_RATE)
    return {
        "actual_playing_days": actual_playing_days,
        "shortfall_days": shortfall,
        "proration_factor": factor,
        "house_nut_applied_cents": house_nut_applied,
        "daily_nut_cents": daily_nut,
        "min_run_penalty_cents": penalty,
        "min_run_compliant": shortfall == 0,
    }


# ----------------------------------------------- settlement figures (PRD 3.9) ---

def settlement_figures(booking, venue, variant):
    if variant == "FINAL":
        st_states = ("COMPLETED",)
        order_states = ("PAID",)
    else:
        st_states = ("SCHEDULED", "COMPLETED")
        order_states = ("RESERVED", "PAID")
    included_showtimes = [st for st in rows_of("showtimes")
                          if st["booking_id"] == booking["id"] and st["status"] in st_states]
    showtime_ids = {st["id"] for st in included_showtimes}
    included_orders = [o for o in rows_of("orders")
                       if o["showtime_id"] in showtime_ids and o["status"] in order_states]
    box_office = sum(o["total_cents"] for o in included_orders)
    facility_total = sum(o["facility_fee_cents"] for o in included_orders)
    adjusted_gross = box_office - facility_total
    playing_days = distinct_playing_days(venue, included_showtimes)
    factor = proration_factor(playing_days, booking["min_run_days"])
    house_nut_applied = round_half_up(Fraction(booking["house_nut_cents"]) * factor)
    terms = booking["terms_variant"]
    if terms == "SLIDING_SCALE_90_10":
        base = max(0, adjusted_gross - house_nut_applied)
        raw_rent = round_half_up(SLIDING_SCALE_EXHIBITOR_SPLIT_COMPLEMENT * Fraction(base))
    elif terms == "PERCENTAGE_FLOOR":
        raw_rent = round_half_up(share_fraction(booking["distributor_share_pct"])
                                 * Fraction(adjusted_gross))
    else:
        raw_rent = booking["guarantee_cents"]
    film_rent = max(raw_rent, booking["guarantee_cents"])
    cinema_retained = adjusted_gross + facility_total - film_rent
    return {
        "box_office_cents": box_office,
        "facility_fee_total_cents": facility_total,
        "adjusted_gross_cents": adjusted_gross,
        "playing_days": playing_days,
        "proration_factor": float(factor),
        "house_nut_applied_cents": house_nut_applied,
        "film_rent_cents": film_rent,
        "cinema_retained_cents": cinema_retained,
    }


# ------------------------------------------------ slot_ranking_score (PRD 3.5) ---

def _gap_component(minutes):
    return min(SPACING_CAP, (minutes // SLOT_GRANULARITY_MINUTES) * 2)


def slot_score(venue, candidate_start, candidate_blocked_until, strand):
    local_time = venue_local_minutes(venue, candidate_start)
    if PRIME_START_LOCAL <= local_time <= PRIME_END_LOCAL:
        prime = 60
    elif SHOULDER_START_LOCAL <= local_time < PRIME_START_LOCAL:
        prime = 35
    else:
        prime = 10
    day = venue_local_day(venue, candidate_start)
    same_day = [st for st in rows_of("showtimes")
                if st["venue_id"] == venue["id"] and st["status"] != "CANCELLED"
                and venue_local_day(venue, st["start_at"]) == day]
    earlier = [st["blocked_until"] for st in same_day if st["blocked_until"] <= candidate_start]
    if earlier:
        gap_before = min(GAP_CAP_MINUTES, whole_minutes(candidate_start - max(earlier)))
    else:
        gap_before = GAP_CAP_MINUTES
    later = [st["start_at"] for st in same_day if st["start_at"] >= candidate_blocked_until]
    if later:
        gap_after = min(GAP_CAP_MINUTES,
                        whole_minutes(min(later) - candidate_blocked_until))
    else:
        gap_after = GAP_CAP_MINUTES
    spacing = _gap_component(gap_before) + _gap_component(gap_after)
    fragmentation = 0
    threshold = venue["min_useful_gap_minutes"]
    if 0 < gap_before < threshold:
        fragmentation += 15
    if 0 < gap_after < threshold:
        fragmentation += 15
    bonus = 0
    if strand == "REPERTORY_SERIES":
        if repertory_count_of_week(venue, candidate_start) < venue["weekly_repertory_target"]:
            bonus = 10
    return prime + spacing - fragmentation + bonus
