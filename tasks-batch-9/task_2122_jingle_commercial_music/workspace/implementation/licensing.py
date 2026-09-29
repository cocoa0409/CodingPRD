"""Licence pricing: markets, fee variants, re-use and renewal (PRD 2.9, 3.6, 3.7)."""

from datetime import timedelta

import clock
import db
import money
from errors import ApiError

MARKET_TIER_MAP = {
    "US_NATIONAL": "TIER_1",
    "DIGITAL_GLOBAL": "TIER_1",
    "US_REGIONAL": "TIER_2",
    "CA_NATIONAL": "TIER_2",
    "EU_NATIONAL": "TIER_2",
    "US_LOCAL": "TIER_3",
    "INTERNAL_NON_AIR": "TIER_3",
}

MARKET_TIER_FEE_CENTS = {"TIER_1": 325000, "TIER_2": 150000, "TIER_3": 60000}

BUYOUT_MULTIPLIER = money.Fraction(5, 2)
TERM_ANNUAL_RATE_PCT = 40
TERM_MONTHS_ALLOWED = (12, 24, 36)
TERM_MONTH_DAYS = 30
RENEWAL_NOTICE_DAYS = 30
RENEWAL_UPLIFT_BASE_PCT = 85
RENEWAL_UPLIFT_STEP_PCT = 10
RENEWAL_UPLIFT_CAP_PCT = 120
REUSE_BASE_PCT = 60
ADMIN_BAND_LOW_CENTS = 100000
ADMIN_BAND_HIGH_CENTS = 200000
ADMIN_PCT_LOW = 10
ADMIN_PCT_MID = 7
ADMIN_PCT_HIGH = 5
MAX_COUNTER_ROUNDS = 2


def check_market_codes(codes):
    """Market vocabulary (PRD 2.5 step 9) -- before any pricing runs."""
    for code in codes:
        if code not in MARKET_TIER_MAP:
            raise ApiError("ERR_UNKNOWN_MARKET_CODE", "Unknown market code '%s'." % code)


def market_component(codes):
    """Plain sum of the per-market tier charges, with no further rounding."""
    return sum(MARKET_TIER_FEE_CENTS[MARKET_TIER_MAP[code]] for code in codes)


def structure_component(deal):
    creative_fee = deal["creative_fee_cents"]
    if deal["license_structure"] == "BUYOUT":
        return money.round_half_up(money.frac(creative_fee) * BUYOUT_MULTIPLIER)
    return money.round_half_up(
        money.pct(creative_fee, TERM_ANNUAL_RATE_PCT) * money.Fraction(deal["term_months"], 12)
    )


def approved_brief(project_id):
    rows = [b for b in db.briefs.values()
            if b["project_id"] == project_id and b["status"] == "APPROVED"]
    rows = db.by_created(rows)
    return rows[0] if rows else None


def quoted_fee(deal):
    """QUOTED_AT_DRAFT: priced over the APPROVED brief's target_markets."""
    brief = approved_brief(deal["project_id"])
    codes = brief["target_markets"] if brief else []
    return structure_component(deal) + market_component(codes)


def invoiced_fee(deal):
    """INVOICED_AT_ACTIVATION: priced over the deal's own market_codes right now."""
    return structure_component(deal) + market_component(deal["market_codes"])


def reuse_fee(market_code):
    """Four pinned steps; the admin band reads the PRE-admin subtotal (PRD 3.7)."""
    tier = MARKET_TIER_MAP[market_code]
    base = money.round_half_up(money.pct(MARKET_TIER_FEE_CENTS[tier], REUSE_BASE_PCT))
    if base <= ADMIN_BAND_LOW_CENTS:
        admin_pct = ADMIN_PCT_LOW
    elif base <= ADMIN_BAND_HIGH_CENTS:
        admin_pct = ADMIN_PCT_MID
    else:
        admin_pct = ADMIN_PCT_HIGH
    admin_fee = money.round_half_up(money.pct(base, admin_pct))
    return {
        "market_tier": tier,
        "reuse_base_cents": base,
        "admin_pct": admin_pct,
        "admin_fee_cents": admin_fee,
        "reuse_total_cents": base + admin_fee,
    }


def renewal_fee(deal):
    """Uplift reads renewal_count BEFORE it is incremented (PRD 3.7)."""
    uplift_pct = min(
        RENEWAL_UPLIFT_CAP_PCT,
        RENEWAL_UPLIFT_BASE_PCT + RENEWAL_UPLIFT_STEP_PCT * deal["renewal_count"],
    )
    return money.round_half_up(money.pct(deal["license_fee_invoiced_cents"], uplift_pct))


def term_end(start_dt, term_months):
    return start_dt + timedelta(days=TERM_MONTH_DAYS * term_months)


def renewal_sweep(new_clock):
    """Run on every clock set: ACTIVE -> RENEWAL_DUE, then RENEWAL_DUE -> LAPSED."""
    moved_to_renewal_due = 0
    lapsed = 0
    deals = db.by_created(list(db.license_deals.values()))
    for deal in deals:
        if deal["status"] != "ACTIVE" or deal["license_structure"] != "TERM":
            continue
        end_dt = deal.get("_effective_end_dt")
        if end_dt is None:
            continue
        if end_dt - timedelta(days=RENEWAL_NOTICE_DAYS) <= new_clock:
            deal["status"] = "RENEWAL_DUE"
            db.touch(deal)
            moved_to_renewal_due += 1
    for deal in deals:
        if deal["status"] != "RENEWAL_DUE":
            continue
        end_dt = deal.get("_effective_end_dt")
        if end_dt is None:
            continue
        if end_dt <= new_clock:
            deal["status"] = "LAPSED"
            db.touch(deal)
            lapsed += 1
    return moved_to_renewal_due, lapsed


def stamp_effective_window(deal, start_dt):
    deal["effective_start_utc"] = clock.iso(start_dt)
    deal["_effective_start_dt"] = start_dt
    if deal["license_structure"] == "TERM":
        end_dt = term_end(start_dt, deal["term_months"])
        deal["effective_end_utc"] = clock.iso(end_dt)
        deal["_effective_end_dt"] = end_dt
    else:
        deal["effective_end_utc"] = None
        deal["_effective_end_dt"] = None
