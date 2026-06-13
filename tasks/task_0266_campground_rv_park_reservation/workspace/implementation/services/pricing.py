"""Pricing engine (PRD §3.6).

Implements, in the pinned order the PRD specifies:
  - stay_charge_cents     (tiered: min of nightly/weekly/monthly decompositions)
  - season_surcharge_cents (per-night rounded-then-summed)
  - addon_total_cents
  - loyalty discount_cents (frozen at confirm; keyed on guest lifetime tier)
  - tax_cents
  - total_due_cents
  - deposit_due_cents
"""
from datetime import timedelta

from db import store
from services.common import (
    WEEK_NIGHTS,
    MONTH_NIGHTS,
    parse_date,
    round_half_up,
)

# Loyalty tiers (PRD §3.6 / SCAFFOLD loyalty_discount)
TIER_GOLD_CENTS = 500000
TIER_SILVER_CENTS = 200000
GOLD_PCT = 10
SILVER_PCT = 5


def rate_plan_for_site(site):
    return store.rate_plans.get(site["rate_plan_id"])


def stay_charge(priced_nights, rate_plan):
    """Tiered stay charge: cheapest of nightly / weekly / monthly decompositions.

    Pure integer-cent arithmetic with whole-night floor division (PRD §3.6).
    """
    n = priced_nights
    nightly = rate_plan["nightly_rate_cents"]
    weekly = rate_plan["weekly_rate_cents"]
    monthly = rate_plan["monthly_rate_cents"]

    cand_nightly = n * nightly
    cand_weekly = (n // WEEK_NIGHTS) * weekly + (n % WEEK_NIGHTS) * nightly
    cand_monthly = (
        (n // MONTH_NIGHTS) * monthly
        + ((n % MONTH_NIGHTS) // WEEK_NIGHTS) * weekly
        + ((n % MONTH_NIGHTS) % WEEK_NIGHTS) * nightly
    )
    return min(cand_nightly, cand_weekly, cand_monthly)


def season_surcharge(check_in_date_str, priced_nights, park, rate_plan):
    """Per-night season surcharge, rounded half-up per night THEN summed.

    Order is load-bearing (PRD §3.6): round each night first, then sum.
    """
    start = parse_date(check_in_date_str)
    seasons = [s for s in store.seasons.values() if s["park_id"] == park["id"]]
    nightly = rate_plan["nightly_rate_cents"]

    total = 0
    for offset in range(priced_nights):
        d = start + timedelta(days=offset)
        covering = None
        for s in seasons:
            s_start = parse_date(s["start_date"])
            s_end = parse_date(s["end_date"])
            if s_start <= d <= s_end:
                covering = s
                break
        if covering is not None:
            # nightly_rate * (surcharge_pct / 100), rounded half-up for THIS night
            night_surcharge = round_half_up(
                nightly * (covering["surcharge_pct"] / 100.0)
            )
            total += night_surcharge
    return total


def loyalty_discount_pct(lifetime_spend_cents):
    """Discount percent keyed on the guest's lifetime spend tier (PRD §3.6)."""
    if lifetime_spend_cents >= TIER_GOLD_CENTS:
        return GOLD_PCT
    if lifetime_spend_cents >= TIER_SILVER_CENTS:
        return SILVER_PCT
    return 0


def active_addons(reservation_id):
    return [
        a
        for a in store.add_ons.values()
        if a["reservation_id"] == reservation_id and a["status"] == "ACTIVE"
    ]


def compute_totals(reservation, park, site, rate_plan, priced_nights, discount_cents):
    """Assemble the reservation money in the pinned nine-step order (PRD §3.6).

    discount_cents is passed in (it is frozen at confirm and persisted on the
    reservation; before confirm it is 0). Returns a dict of the money fields.
    """
    # 1. stay charge
    sc = stay_charge(priced_nights, rate_plan)
    # 2. season surcharge
    ss = season_surcharge(
        reservation["check_in_date"], priced_nights, park, rate_plan
    )
    # 3. addon total (ACTIVE only)
    addons = active_addons(reservation["id"])
    addon_total = sum(a["amount_cents"] for a in addons)
    taxable_addon_total = sum(
        a["amount_cents"] for a in addons if a.get("taxable", True)
    )

    # 4. pre-discount subtotal
    pre_discount_subtotal = sc + ss + addon_total
    # 5. discount_cents (provided; keyed on guest tier, not subtotal)
    # 6. discounted subtotal
    discounted_subtotal = max(0, pre_discount_subtotal - discount_cents)
    # 7. taxable base (discount reduces it, floored at 0)
    taxable_base = sc + ss + taxable_addon_total - discount_cents
    taxable_base = max(0, taxable_base)
    # 8. tax (round half up)
    tax = round_half_up(taxable_base * park["tax_rate"])
    # 9. total due
    total_due = discounted_subtotal + tax

    return {
        "stay_charge_cents": sc,
        "season_surcharge_cents": ss,
        "addon_total_cents": addon_total,
        "discount_cents": discount_cents,
        "tax_cents": tax,
        "total_due_cents": total_due,
        "pre_discount_subtotal": pre_discount_subtotal,
    }


def deposit_due(total_due_cents, park):
    """deposit_due_cents = round_half_up(total_due * deposit_pct) (PRD §3.6)."""
    return round_half_up(total_due_cents * park["deposit_pct"])


def guest_lifetime_spend(guest_id):
    """Sum of total_due_cents across the guest's CHECKED_OUT reservations.

    Computed live (not stored) — mirrors the serializer's derivation (PRD §3.5).
    """
    total = 0
    for r in store.reservations.values():
        if r["guest_id"] == guest_id and r["reservation_status"] == "CHECKED_OUT":
            total += r["total_due_cents"]
    return total


def compute_discount_at_confirm(pre_discount_subtotal, guest):
    """Loyalty discount frozen at confirm, keyed on guest lifetime tier (PRD §3.6)."""
    lifetime = guest_lifetime_spend(guest["id"])
    pct = loyalty_discount_pct(lifetime)
    return round_half_up(pre_discount_subtotal * pct / 100.0)
