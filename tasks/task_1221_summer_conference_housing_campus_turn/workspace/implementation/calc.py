"""Calculation rules (scaffold 1.3 / PRD 3). Integer cents; round-half-up at
the pinned step of each calculation; no floats anywhere."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from timeutil import as_date, as_instant, add_months, nights_between

# bed_night_billing constants
BASE_RATE_CENTS = 4500
TIER_THRESHOLD_BED_NIGHTS = 100
TIER2_RATE_CENTS = 3900
MINOR_SURCHARGE_PCT = 15
WEEKEND_PREMIUM_CENTS = 400

# damage_charge constants
MONTHLY_DEPRECIATION_PCT = 2
DEPRECIATION_FLOOR = Decimal("0.40")
ADMIN_FEE_CENTS = 2500

# revenue_allocation constants
OVERHEAD_PCT = 12
RESERVE_PCT = 8

# turn_window_requirement constants
BASE_TURN_HOURS = 24
DELUXE_TURN_HOURS = 30

# key_late_fee constants
KEY_GRACE_DAYS = 2
KEY_LATE_FEE_PER_DAY_CENTS = 1500
KEY_LATE_FEE_CAP_CENTS = 7500
KEY_LOST_FEE_CENTS = 5000

# cancellation_fee constants
FREE_CANCEL_DAYS = 31
REDUCED_CANCEL_DAYS = 15
REDUCED_CANCEL_PCT = 20
LATE_CANCEL_PCT = 50

# linen_reconciliation_charge constants
LINEN_PACK_COST_CENTS = 3200
LINEN_DAMAGED_PACK_CENTS = 1600

# Screening validity window. The PRD and scaffold reference the constant
# SCREENING_VALIDITY_MONTHS in prose ("cleared_on + SCREENING_VALIDITY_MONTHS
# months") but neither document pins a numeric value; 6 months is assumed.
SCREENING_VALIDITY_MONTHS = 6

DAMAGE_DISPUTE_WINDOW_DAYS = 7


def _rhup_int(value):
    """Round half up to integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# bed_night_billing (provisional + final variants)
# ---------------------------------------------------------------------------

def _price_night_list(nights, has_minor):
    """nights: list of (sort_key, night_date). Prices marginal tiers by
    cumulative index (1-based), minor surcharge rounded half-up per night
    before the weekend premium, premium added after."""
    nights.sort(key=lambda e: e[0])
    total = 0
    for idx, (_key, d) in enumerate(nights, start=1):
        rate = BASE_RATE_CENTS if idx <= TIER_THRESHOLD_BED_NIGHTS else TIER2_RATE_CENTS
        if has_minor:
            rate = _rhup_int(Decimal(rate) * (Decimal(100) + Decimal(MINOR_SURCHARGE_PCT)) / Decimal(100))
        if d.weekday() in (4, 5):  # Friday or Saturday night
            rate += WEEKEND_PREMIUM_CENTS
        total += rate
    return total


def _participant_seq(participant_id):
    p = store.participants.get(participant_id)
    return p["_seq"] if p else 0


def provisional_bed_night_subtotal(group):
    """Planned nights over the ACTIVE revision's RESERVED/CHECKED_IN
    assignments; nights ordered by check-in date ASC, participant created_at
    ASC (insertion sequence stands in for created_at ordering)."""
    rev = active_revision(group["id"])
    entries = []
    if rev is not None:
        for a in store.assignments.values():
            if a["revision_id"] == rev["id"] and a["status"] in ("RESERVED", "CHECKED_IN"):
                ci = as_date(a["checkin_at"])
                co = as_date(a["checkout_at"])
                pseq = _participant_seq(a["participant_id"])
                for d in nights_between(ci, co):
                    entries.append(((ci, pseq, d), d))
    return _price_night_list(entries, group["has_minor_participants"])


def final_bed_night_subtotal(group):
    """Actual nights for CHECKED_OUT assignments; NO_SHOW bills one flat
    base-rate night outside the tier indexing; CANCELLED excluded."""
    entries = []
    no_show_count = 0
    for a in store.assignments.values():
        if a["group_id"] != group["id"]:
            continue
        if a["status"] == "CHECKED_OUT":
            ci = as_date(("datetime", a["actual_checkin_at"]))
            co = as_date(("datetime", a["actual_checkout_at"]))
            pseq = _participant_seq(a["participant_id"])
            for d in nights_between(ci, co):
                entries.append(((ci, pseq, d), d))
        elif a["status"] == "NO_SHOW":
            no_show_count += 1
    return _price_night_list(entries, group["has_minor_participants"]) + no_show_count * BASE_RATE_CENTS


# ---------------------------------------------------------------------------
# damage_charge
# ---------------------------------------------------------------------------

def damage_estimate_total(line_items):
    """Estimate variant: straight sum, no depreciation, no fee."""
    return sum(li["quantity"] * li["unit_replacement_cost_cents"] for li in line_items)


def damage_assessed_total(line_items):
    """Assessed variant: per-unit depreciation (floor 0.40) rounded half-up
    per unit, then * quantity, then summed, then one flat admin fee."""
    total = 0
    for li in line_items:
        factor = Decimal(1) - (Decimal(MONTHLY_DEPRECIATION_PCT) / Decimal(100)) * Decimal(li["fixture_age_months"])
        if factor < DEPRECIATION_FLOOR:
            factor = DEPRECIATION_FLOOR
        depreciated_unit = (Decimal(li["unit_replacement_cost_cents"]) * factor).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(depreciated_unit) * li["quantity"]
    if line_items:
        total += ADMIN_FEE_CENTS
    return total


# ---------------------------------------------------------------------------
# revenue_allocation waterfall (pinned evaluation order)
# ---------------------------------------------------------------------------

def allocation_waterfall(gross_cents):
    overhead = _rhup_int(Decimal(gross_cents) * Decimal(OVERHEAD_PCT) / Decimal(100))
    reserve = _rhup_int(Decimal(gross_cents - overhead) * Decimal(RESERVE_PCT) / Decimal(100))
    ops = gross_cents - overhead - reserve
    return overhead, reserve, ops


# ---------------------------------------------------------------------------
# key_late_fee
# ---------------------------------------------------------------------------

def key_late_fee(departure_date, returned_at):
    return_date = returned_at.date()
    late_days = max(0, (return_date - departure_date).days - KEY_GRACE_DAYS)
    return min(late_days * KEY_LATE_FEE_PER_DAY_CENTS, KEY_LATE_FEE_CAP_CENTS)


# ---------------------------------------------------------------------------
# cancellation_fee
# ---------------------------------------------------------------------------

def cancellation_fee_cents(group, provisional_total_cents):
    days_before = (as_date(group["arrival_date"]) - store.clock.date()).days
    if days_before >= FREE_CANCEL_DAYS:
        return 0
    pct = REDUCED_CANCEL_PCT if days_before >= REDUCED_CANCEL_DAYS else LATE_CANCEL_PCT
    return _rhup_int(Decimal(provisional_total_cents) * Decimal(pct) / Decimal(100))


# ---------------------------------------------------------------------------
# linen_reconciliation_charge
# ---------------------------------------------------------------------------

def linen_loss_charge(issue):
    lost = issue["packs_issued"] - issue["packs_returned"] - issue["packs_damaged"]
    return lost * LINEN_PACK_COST_CENTS + issue["packs_damaged"] * LINEN_DAMAGED_PACK_CENTS


# ---------------------------------------------------------------------------
# turn_window_requirement
# ---------------------------------------------------------------------------

def required_turn_hours(linen_tier):
    return DELUXE_TURN_HOURS if linen_tier == "DELUXE" else BASE_TURN_HOURS


# ---------------------------------------------------------------------------
# screening freshness
# ---------------------------------------------------------------------------

def screening_is_expired(screening):
    if screening["status"] != "CLEARED" or screening["cleared_on"] is None:
        return False
    return store.clock.date() > add_months(screening["cleared_on"], SCREENING_VALIDITY_MONTHS)


# ---------------------------------------------------------------------------
# shared lookups
# ---------------------------------------------------------------------------

def active_revision(group_id):
    for r in store.revisions.values():
        if r["group_id"] == group_id and r["status"] == "ACTIVE":
            return r
    return None


def binding_interval(assignment):
    """The interval an assignment occupies for overlap/turn/capacity checks:
    RESERVED/CHECKED_IN bind their planned interval, CHECKED_OUT binds its
    actual interval; CANCELLED and NO_SHOW bind nothing."""
    st = assignment["status"]
    if st in ("RESERVED", "CHECKED_IN"):
        return (as_instant(assignment["checkin_at"]), as_instant(assignment["checkout_at"]))
    if st == "CHECKED_OUT":
        return (assignment["actual_checkin_at"], assignment["actual_checkout_at"])
    return None
