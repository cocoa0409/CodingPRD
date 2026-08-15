"""Fee arithmetic (PRD §3.8, SCAFFOLD §1.3).

All monetary values are integer cents; fractional results round half-up at the
pinned steps: once at the scheme-multiplier step and once at the risk-surcharge
step of the annual fee; per line before summation on product-addition invoices;
once on the volume-discount amount. Sum-then-round is forbidden.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import store

TIER1_CENTS = 120000
TIER2_CENTS = 90000
TIER3_CENTS = 70000
COPACKER_SURCHARGE_CENTS = 25000
DUAL_SCHEME_MULTIPLIER = Decimal("1.8")
MEDIUM_RISK_SURCHARGE_PCT = 5
HIGH_RISK_SURCHARGE_PCT = 15
DAYS_IN_CYCLE = 365
REINSTATEMENT_FEE_CENTS = 50000

DISCOUNT_TIER2_CENTS = 200000
DISCOUNT_TIER1_CENTS = 100000
DISCOUNT_TIER2_PCT = 10
DISCOUNT_TIER1_PCT = 5


def rhu(value):
    """Round half-up a Decimal to integer cents."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def annual_certification_fee(client, scheme):
    """Marginal facility tiers + co-packer surcharge, scheme multiplier, then
    risk surcharge keyed on the client's risk tier at the calculation instant.
    Facilities: client's, status != DECOMMISSIONED, ordered created_at ASC."""
    facilities = [f for f in store.facilities.values()
                  if f["client_id"] == client["id"] and f["status"] != "DECOMMISSIONED"]
    facilities.sort(key=lambda f: (f["created_at"], f["_seq"]))
    count = len(facilities)
    tier_sum = 0
    if count >= 1:
        tier_sum += TIER1_CENTS
    tier_sum += max(0, min(count, 5) - 1) * TIER2_CENTS
    tier_sum += max(0, count - 5) * TIER3_CENTS
    copackers = sum(1 for f in facilities if f["facility_role"] == "CO_PACKER")
    base = tier_sum + COPACKER_SURCHARGE_CENTS * copackers
    mult = DUAL_SCHEME_MULTIPLIER if scheme == "DUAL" else Decimal("1")
    subtotal = rhu(Decimal(base) * mult)
    pct = {"LOW": 0, "MEDIUM": MEDIUM_RISK_SURCHARGE_PCT,
           "HIGH": HIGH_RISK_SURCHARGE_PCT}[client["risk_tier"]]
    return subtotal + rhu(Decimal(subtotal) * pct / 100)


def prorata_line_cents(per_product_fee_cents, addition_date, cycle_end_date):
    """Forward-looking proration: half-open [addition_date, cycle_end) days,
    floored at zero; one product = one line, rounded half-up per line."""
    days_remaining = max(0, (cycle_end_date - addition_date).days)
    raw = Decimal(per_product_fee_cents) * days_remaining / DAYS_IN_CYCLE
    return rhu(raw)


def volume_discount_cents(subtotal_cents):
    """Tier keyed exactly once on the PRE-discount subtotal; the post-discount
    total never re-enters tier selection."""
    if subtotal_cents >= DISCOUNT_TIER2_CENTS:
        pct = DISCOUNT_TIER2_PCT
    elif subtotal_cents >= DISCOUNT_TIER1_CENTS:
        pct = DISCOUNT_TIER1_PCT
    else:
        pct = 0
    return rhu(Decimal(subtotal_cents) * pct / 100)


def cycle_end_for(agreement, addition_date):
    """ANNIVERSARY: the agreement's term_end_date; CALENDAR_YEAR: Dec 31 of the
    addition year."""
    if agreement["billing_cycle"] == "ANNIVERSARY":
        return agreement["term_end_date"]
    return date(addition_date.year, 12, 31)
