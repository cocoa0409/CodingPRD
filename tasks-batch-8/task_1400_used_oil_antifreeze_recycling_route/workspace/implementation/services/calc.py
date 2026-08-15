"""Calculation rules (SCAFFOLD §1.3 / PRD §3.5, §3.8, §3.9).

All monetary amounts are integer cents; all volumes are whole gallons.
Non-integral intermediates are rounded HALF UP at the step the rule pins.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError, ERR_PRICE_NOT_PUBLISHED

# --- settlement_amount constants ---
ZONE_MINIMUM_GALLONS = {"URBAN": 50, "SUBURBAN": 100, "RURAL": 150}
DENSITY_FEE_CENTS_PER_GAL = {"URBAN": 20, "SUBURBAN": 15, "RURAL": 10}
SURCHARGE_TIER_1_MAX = 2
SURCHARGE_TIER_2_MAX = 4
SURCHARGE_TIER_1_CENTS = 500
SURCHARGE_TIER_2_CENTS = 1500
SURCHARGE_TIER_3_PER_VIOLATION_CENTS = 250

# --- market_price_lookup constants ---
DEFAULT_MIXED_OIL_SHARE_PCT = 50

# --- blend_batch_yield constants ---
BASE_YIELD_PCT = {
    "RE_REFINED_BASE_OIL": 72,
    "RECYCLED_ANTIFREEZE": 85,
    "FUEL_BLENDING_STOCK": 60,
}
HALOGEN_PENALTY_PER_VIOLATION_PCT = 2
HALOGEN_PENALTY_CAP_PCT = 20
MIX_PENALTY_PCT = 5

# --- spill_liability constants ---
SPILL_BASE_RATE_CENTS_PER_GAL = 850
RQ_THRESHOLD_GALLONS = 25
RQ_FLAT_FEE_CENTS = 50000
SPILL_CAUSE_MULTIPLIER = {
    "EQUIPMENT_FAILURE": Decimal("1.5"),
    "CUSTOMER_OVERFILL": Decimal("1.0"),
    "DRIVER_ERROR": Decimal("2.0"),
    "THIRD_PARTY": Decimal("0.5"),
    "UNKNOWN": Decimal("1.0"),
}


def round_half_up(value):
    """Round a Decimal (or int) half-up to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round half-up to one decimal place; returned as a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# market_price_lookup
# ---------------------------------------------------------------------------


def _latest_price(zone, kind, scheduled_date):
    """Most recent MarketPrice for (zone, kind) with effective_date <= date.

    effective_date is an inclusive lower bound: a row dated exactly the
    scheduled date is used; future-dated rows are never used. ISO dates
    compare lexicographically.
    """
    best = None
    for mp in db.all_entities("market_prices"):
        if mp["market_zone"] != zone or mp["tank_kind"] != kind:
            continue
        if mp["effective_date"] > scheduled_date:
            continue
        if best is None or mp["effective_date"] > best["effective_date"]:
            best = mp
    return best


def market_price_for(zone, tank_kind, scheduled_date, oil_share_pct=None):
    """Signed cents/gal for the stream on the given date in the zone.

    MIXED is the weighted blend of the zone's used-oil and antifreeze prices,
    rounded half-up to whole cents; the oil share defaults to 50 percent.
    Raises ERR_PRICE_NOT_PUBLISHED when no applicable row exists.
    """
    if tank_kind == "MIXED":
        oil = _latest_price(zone, "USED_OIL", scheduled_date)
        anti = _latest_price(zone, "ANTIFREEZE", scheduled_date)
        if oil is None or anti is None:
            raise ApiError(
                ERR_PRICE_NOT_PUBLISHED,
                "No market price with effective_date <= scheduled_date for (zone, kind)",
                422,
            )
        share = oil_share_pct if oil_share_pct is not None else DEFAULT_MIXED_OIL_SHARE_PCT
        blended = (
            Decimal(oil["price_cents_per_gal"]) * Decimal(str(share))
            + Decimal(anti["price_cents_per_gal"]) * Decimal(str(100 - share))
        ) / Decimal(100)
        return round_half_up(blended)

    row = _latest_price(zone, tank_kind, scheduled_date)
    if row is None:
        raise ApiError(
            ERR_PRICE_NOT_PUBLISHED,
            "No market price with effective_date <= scheduled_date for (zone, kind)",
            422,
        )
    return row["price_cents_per_gal"]


def market_price_or_none(zone, tank_kind, scheduled_date, oil_share_pct=None):
    try:
        return market_price_for(zone, tank_kind, scheduled_date, oil_share_pct)
    except ApiError as e:
        if e.error_id == ERR_PRICE_NOT_PUBLISHED:
            return None
        raise


# ---------------------------------------------------------------------------
# settlement_amount
# ---------------------------------------------------------------------------


def halogen_surcharge_cents(halogen_violation_count):
    h = halogen_violation_count
    if h == 0:
        return 0
    if h <= SURCHARGE_TIER_1_MAX:
        return SURCHARGE_TIER_1_CENTS
    if h <= SURCHARGE_TIER_2_MAX:
        return SURCHARGE_TIER_2_CENTS
    return SURCHARGE_TIER_2_CENTS + SURCHARGE_TIER_3_PER_VIOLATION_CENTS * (h - SURCHARGE_TIER_2_MAX)


def density_fee_cents(volume_gallons, density_zone, route_eligibility_override):
    """Zero when the volume meets the zone minimum (>= is inclusive) or the
    site carries the override; otherwise shortfall x per-gallon fee."""
    zone_min = ZONE_MINIMUM_GALLONS[density_zone]
    if volume_gallons >= zone_min or route_eligibility_override:
        return 0
    return (zone_min - volume_gallons) * DENSITY_FEE_CENTS_PER_GAL[density_zone]


def settlement_calc(price_cents_per_gal, volume_gallons, frozen_halogen_count,
                    density_zone, route_eligibility_override):
    """Pinned order: gross, surcharge, density fee, then sign, then direction."""
    p = price_cents_per_gal
    v = volume_gallons
    gross = abs(p) * v
    surcharge = halogen_surcharge_cents(frozen_halogen_count)
    fee = density_fee_cents(v, density_zone, route_eligibility_override)
    if p > 0:
        net = gross - surcharge - fee
    elif p < 0:
        net = -(gross + surcharge + fee)
    else:
        net = 0
    if net > 0:
        direction = "PAY_CUSTOMER"
    elif net < 0:
        direction = "CHARGE_CUSTOMER"
    else:
        direction = "ZERO_NET"
    return {
        "commodity_price_cents_per_gal": p,
        "gross_amount_cents": gross,
        "surcharge_cents": surcharge,
        "density_fee_cents": fee,
        "net_amount_cents": net,
        "settlement_direction": direction,
    }


# ---------------------------------------------------------------------------
# blend_batch_yield
# ---------------------------------------------------------------------------


def blend_yield(target_product, tickets, optimistic=False):
    """Return (input_gallons_total, yield_pct, output_gallons).

    optimistic=True is the planned_estimate variant: zero halogen history and
    no mix penalty; informational only.
    """
    v_in = sum(t["metered_volume_gallons"] for t in tickets)
    base_pct = BASE_YIELD_PCT[target_product]
    if optimistic:
        penalty_pct = 0
        mix_penalty = 0
    else:
        if v_in > 0:
            avg_h = round_half_up(
                Decimal(sum(t["frozen_halogen_count"] * t["metered_volume_gallons"] for t in tickets))
                / Decimal(v_in)
            )
        else:
            avg_h = 0
        penalty_pct = min(
            HALOGEN_PENALTY_CAP_PCT,
            max(0, HALOGEN_PENALTY_PER_VIOLATION_PCT * (avg_h - 4)),
        )
        kinds = {t["tank_kind"] for t in tickets}
        mix_penalty = MIX_PENALTY_PCT if len(kinds) > 1 else 0
    yield_pct = max(0, base_pct - penalty_pct - mix_penalty)
    output = round_half_up(Decimal(v_in) * Decimal(yield_pct) / Decimal(100))
    return v_in, yield_pct, output


# ---------------------------------------------------------------------------
# spill_liability
# ---------------------------------------------------------------------------


def spill_liability(gallons_spilled, cause_code, tank_ownership, reportable_quantity_exceeded):
    """Return (liability_cents, responsible_party, customer_share_cents)."""
    base = SPILL_BASE_RATE_CENTS_PER_GAL * gallons_spilled
    raw = round_half_up(Decimal(base) * SPILL_CAUSE_MULTIPLIER[cause_code])

    if cause_code == "CUSTOMER_OVERFILL":
        party = "CUSTOMER"
    elif cause_code == "DRIVER_ERROR":
        party = "COMPANY"
    elif cause_code == "EQUIPMENT_FAILURE":
        party = "COMPANY" if tank_ownership == "COMPANY_OWNED" else "CUSTOMER"
    elif cause_code == "THIRD_PARTY":
        party = "COMPANY"
    else:  # UNKNOWN
        party = "SHARED"

    liability = raw
    if party == "SHARED":
        customer_share = round_half_up(Decimal(raw) / Decimal(2))
    elif party == "CUSTOMER":
        customer_share = liability
    else:
        customer_share = 0

    if reportable_quantity_exceeded:
        liability += RQ_FLAT_FEE_CENTS

    return liability, party, customer_share


# ---------------------------------------------------------------------------
# route_posture
# ---------------------------------------------------------------------------


def route_posture(route):
    """CLOSED_OUT when COMPLETE/CANCELLED (or forced by facility rejection),
    else AT_CAPACITY when loaded >= capacity (equality counts), else OPEN."""
    if route["status"] in ("COMPLETE", "CANCELLED"):
        return "CLOSED_OUT"
    if route.get("_posture_override"):
        return "CLOSED_OUT"
    if route["loaded_gallons"] >= route["vehicle_capacity_gallons"]:
        return "AT_CAPACITY"
    return "OPEN"
