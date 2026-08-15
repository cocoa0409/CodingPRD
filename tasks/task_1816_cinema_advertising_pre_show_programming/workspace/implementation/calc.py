"""Calculation rules (SCAFFOLD 1.3 / PRD 2.9, 3.x). All money math uses
Decimal; rounding is half-up to whole cents; impressions are floored after all
multiplications complete."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import db

OCCUPANCY = {
    "MAJOR_METRO": Decimal("0.40"),
    "REGIONAL": Decimal("0.32"),
    "SMALL_MARKET": Decimal("0.25"),
}
DAYPART_FACTOR = {"MATINEE": Decimal("0.80"), "EVENING": Decimal("1.20")}
RATING_DEMAND = {
    "G": Decimal("0.90"),
    "PG": Decimal("1.00"),
    "PG13": Decimal("1.10"),
    "R": Decimal("1.05"),
    "NC17": Decimal("0.70"),
}
OPENING_WEEK_DAYS = 7
OPENING_WEEK_MULTIPLIER = Decimal("1.25")

REEL_CAPACITY_SECONDS = 1200
NATIONAL_POOL_SECONDS = 720
LOCAL_POOL_SECONDS = 480
TURNAROUND_MINUTES = 30

MAKE_GOOD_THRESHOLD_PCT = Decimal("0.05")
MAKE_GOOD_MULTIPLIER = Decimal("1.10")

THOUSAND = Decimal("1000")
CENT = Decimal("1")


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half-up."""
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


def line_amount_cents(impressions, cpm_cents):
    """round_half_up(impressions * cpm_cents / 1000) — per-line rounding."""
    return round_half_up_cents(Decimal(impressions) * Decimal(cpm_cents) / THOUSAND)


def forecast_attendance(seat_count, market_tier, daypart, content_rating,
                        showtime_date, release_date):
    """floor(seat_count x OCCUPANCY x DAYPART_FACTOR x RATING_DEMAND x
    opening_multiplier); floor applied only after all multiplications."""
    base = Decimal(seat_count) * OCCUPANCY[market_tier]
    delta = (showtime_date - release_date).days
    multiplier = (OPENING_WEEK_MULTIPLIER
                  if 0 <= delta <= OPENING_WEEK_DAYS else Decimal("1"))
    product = base * DAYPART_FACTOR[daypart] * RATING_DEMAND[content_rating] * multiplier
    return int(product.to_integral_value(rounding=ROUND_FLOOR))


def daypart_of(starts_dt):
    return "MATINEE" if starts_dt.hour < 17 else "EVENING"


def play_factor_for(outcome, partial_credit_mode):
    if outcome == "VERIFIED":
        return 1.0
    if outcome == "PARTIAL":
        return 1.0 if partial_credit_mode == "LENIENT" else 0.5
    return 0.0  # FAILED


def attribute(actual_attendance, play_factor):
    """floor(actual_attendance * play_factor); None when attendance unknown."""
    if actual_attendance is None:
        return None
    return int((Decimal(actual_attendance) * Decimal(str(play_factor)))
               .to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Aggregates and cascades
# ---------------------------------------------------------------------------

def slots_of_reel(reel_id):
    return [s for s in db.slots.values() if s["reel_id"] == reel_id]


def slots_of_campaign(campaign_id):
    return [s for s in db.slots.values() if s["campaign_id"] == campaign_id]


def recompute_campaign_reserved(campaign):
    """reserved_estimated_cents = sum of estimated_cost_cents over slots in
    RESERVED or CONFIRMED."""
    total = sum(s["estimated_cost_cents"] for s in slots_of_campaign(campaign["id"])
                if s["slot_status"] in ("RESERVED", "CONFIRMED"))
    campaign["reserved_estimated_cents"] = total
    db.touch(campaign)


def recompute_campaign_delivered(campaign):
    """delivered_impressions = sum of attributed_impressions over PLAYED slots
    (null contributions count as 0)."""
    total = sum((s["attributed_impressions"] or 0)
                for s in slots_of_campaign(campaign["id"])
                if s["slot_status"] == "PLAYED")
    campaign["delivered_impressions"] = total
    db.touch(campaign)


def cascade_showtime_attendance(showtime):
    """PRD 3.5: after actual_attendance is set/revised, recompute attributions
    of PLAYED slots on this showtime, then delivered_impressions of every
    affected campaign."""
    actual = showtime["actual_attendance"]
    affected = set()
    for slot in db.slots.values():
        if slot["slot_status"] != "PLAYED":
            continue
        reel = db.reels.get(slot["reel_id"])
        if reel is None or reel["showtime_id"] != showtime["id"]:
            continue
        slot["attributed_impressions"] = attribute(actual, slot["play_factor"])
        db.touch(slot)
        affected.add(slot["campaign_id"])
    for cid in affected:
        recompute_campaign_delivered(db.campaigns[cid])


def showtime_date(showtime):
    return showtime["_starts_dt"].date()


def in_period_slots(campaign_id, period_start, period_end):
    """Slots of the campaign whose showtime calendar date falls inside the
    period, endpoints inclusive (any status)."""
    out = []
    for slot in slots_of_campaign(campaign_id):
        reel = db.reels[slot["reel_id"]]
        st = db.showtimes[reel["showtime_id"]]
        d = showtime_date(st)
        if period_start <= d <= period_end:
            out.append(slot)
    return out


def make_good_credit_cents(shortfall, cpm_cents, audited_amount_cents):
    raw = (Decimal(shortfall) * Decimal(cpm_cents)
           * MAKE_GOOD_MULTIPLIER / THOUSAND)
    return min(round_half_up_cents(raw), audited_amount_cents)


def threshold_met(shortfall, contracted):
    """under_delivery_pct > 0.05 compared in exact rational arithmetic;
    exactly 0.05 is NOT eligible."""
    return shortfall * 20 > contracted
