"""Calculation rules (SCAFFOLD Table 3 / PRD section 3).

All money is integer cents; all weights are Decimal at 2dp; rounding is
ROUND_HALF_UP applied at exactly the step each workflow pins.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import store

CENT = Decimal("1")
Q2 = Decimal("0.01")
ZERO = Decimal("0")


def q2(x):
    """Round a Decimal to 2 decimal places, half up."""
    return x.quantize(Q2, rounding=ROUND_HALF_UP)


def cents(x):
    """Round a Decimal to integer cents, half up."""
    return int(x.quantize(CENT, rounding=ROUND_HALF_UP))


def pct2(x):
    """Round a Decimal percentage to 2 decimal places, half up."""
    return x.quantize(Q2, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# yield_processing
# ---------------------------------------------------------------------------
CONDITION_FACTOR = {
    "GRADE_A": Decimal("1.00"),
    "GRADE_B": Decimal("0.97"),
    "GRADE_C": Decimal("0.92"),
}
PROCESSING_FACTOR = {
    "WHOLE": Decimal("1.00"),
    "FILLETED": Decimal("0.85"),
}


def processed_weight(landed_weight_kg, yield_pct, assessed_grade, processing_type):
    raw = (
        landed_weight_kg
        * yield_pct
        * CONDITION_FACTOR[assessed_grade]
        * PROCESSING_FACTOR[processing_type]
    )
    return q2(min(landed_weight_kg, raw))


# ---------------------------------------------------------------------------
# freight_charge (provisional and final variants share this pinned tariff)
# ---------------------------------------------------------------------------
DIM_KG_PER_M3 = Decimal("167")
BASE_CENTS = {"AIR": 5000, "TRUCK": 2500}
PER_KG_CENTS = {"AIR": 320, "TRUCK": 140}
DISCOUNT_TIER_CENTS = 10000
DISCOUNT_MULTIPLIER = Decimal("0.95")  # 1 - 0.05
FUEL_PCT = Decimal("0.12")
MIN_CHARGE_CENTS = 4000


def freight_charge_cents(mode, chargeable_weight_kg):
    subtotal = BASE_CENTS[mode] + cents(chargeable_weight_kg * PER_KG_CENTS[mode])
    if subtotal >= DISCOUNT_TIER_CENTS:
        discounted = cents(Decimal(subtotal) * DISCOUNT_MULTIPLIER)
    else:
        discounted = subtotal
    fuel = cents(Decimal(discounted) * FUEL_PCT)
    return max(MIN_CHARGE_CENTS, discounted + fuel)


def dimensional_weight_kg(volume_m3):
    return q2(volume_m3 * DIM_KG_PER_M3)


# ---------------------------------------------------------------------------
# Quote selectors
# ---------------------------------------------------------------------------
def standing_quote(species_id, grade):
    """Latest PUBLISHED quote for (species, grade) with quote_date <= current
    logical date; greatest quote_date, tie-break latest created (seq)."""
    today = store.clock.date()
    cands = [
        q for q in store.quotes.values()
        if q["species_id"] == species_id
        and q["grade"] == grade
        and q["status"] == "PUBLISHED"
        and q["_quote_date"] <= today
    ]
    if not cands:
        return None
    cands.sort(key=lambda q: (q["_quote_date"], q["_seq"]))
    return cands[-1]


def settlement_quote(species_id, grade, landing_date):
    """Historical settlement quote: (species, grade, quote_date == landing
    date), status in {PUBLISHED, SUPERSEDED, EXPIRED}; greatest quote_date,
    tie-break latest created (seq)."""
    cands = [
        q for q in store.quotes.values()
        if q["species_id"] == species_id
        and q["grade"] == grade
        and q["status"] in ("PUBLISHED", "SUPERSEDED", "EXPIRED")
        and q["_quote_date"] == landing_date
    ]
    if not cands:
        return None
    cands.sort(key=lambda q: (q["_quote_date"], q["_seq"]))
    return cands[-1]


def current_published(species_id, grade):
    """The one PUBLISHED quote for (species, grade), if any (volatility guard
    prior). At most one stands published per key at a time."""
    for q in store.quotes.values():
        if (
            q["species_id"] == species_id
            and q["grade"] == grade
            and q["status"] == "PUBLISHED"
        ):
            return q
    return None


def volatility_pct(new_price_cents, prior_price_cents):
    diff = abs(new_price_cents - prior_price_cents)
    return pct2(Decimal(diff) / Decimal(prior_price_cents) * Decimal("100"))


VOLATILITY_THRESHOLD = Decimal("10.00")


# ---------------------------------------------------------------------------
# substitute_selection (cascades: condemn, expiry)
# ---------------------------------------------------------------------------
def select_substitute(line):
    """Cheapest standing-quote species in the same substitution group with at
    least one ACTIVE+CLEAR lot; tie-break species created (seq). None if empty."""
    original = store.species[line["species_id"]]
    best = None
    for s in store.species.values():
        if s["id"] == line["species_id"]:
            continue
        if s["substitution_group"] != original["substitution_group"]:
            continue
        has_lot = any(
            lot["species_id"] == s["id"]
            and lot["lifecycle_status"] == "ACTIVE"
            and lot["hold_status"] == "CLEAR"
            for lot in store.lots.values()
        )
        if not has_lot:
            continue
        quote = standing_quote(s["id"], line["requested_grade"])
        if quote is None:
            continue
        key = (quote["price_per_kg_cents"], s["_seq"])
        if best is None or key < best[0]:
            best = (key, s)
    return best[1] if best else None
