"""Calculation services per PRD §3 and SCAFFOLD calculations table.

All money is integer cents. Round-half-up via Decimal for provisional; ceiling for final.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import store


# ---- outage_credit_amount (PRD §3.7) ----
BASE_RATE_CENTS_PER_MIN = 500
TIER1_MAX_MIN = 30
TIER2_MAX_MIN = 120
TIER1_MULT = Decimal("1.0")
TIER2_MULT = Decimal("1.5")
TIER3_MULT = Decimal("2.0")
SATJAM_MULT = Decimal("1.5")
PLANNED_MAINT_MULT = Decimal("0.0")
DEFAULT_MULT = Decimal("1.0")


def compute_outage_credit_cents(cause: str, duration_minutes: int) -> int:
    """Per PRD §3.7 outage-credit waterfall."""
    if cause == "PLANNED_MAINTENANCE":
        multiplier = PLANNED_MAINT_MULT
    elif cause == "SATELLITE_JAM":
        multiplier = SATJAM_MULT
    else:
        multiplier = DEFAULT_MULT
    minutes = max(0, int(duration_minutes))
    tier1 = min(minutes, 30)
    tier2 = max(0, min(minutes - 30, 90))
    tier3 = max(0, minutes - 120)
    raw = (
        Decimal(tier1) * TIER1_MULT
        + Decimal(tier2) * TIER2_MULT
        + Decimal(tier3) * TIER3_MULT
    ) * Decimal(BASE_RATE_CENTS_PER_MIN) * multiplier
    # Round half-up to integer cents
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- clearance_rate_calc (PRD §3.5) ----
def compute_clearance_rate(cleared_hours, obligation_hours) -> float:
    """Round_half_up(cleared / obligation, 4)."""
    cleared = Decimal(str(cleared_hours))
    obligated = Decimal(str(obligation_hours))
    if obligated == 0:
        # Avoid divide-by-zero; treat as 0
        return 0.0
    rate = (cleared / obligated).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(rate)


# ---- reverse_comp_provisional_vs_final (PRD §3.6) ----
TIER_THRESHOLD_MAJOR_CENTS = 100_000_000
TIER_THRESHOLD_LARGE_CENTS = 50_000_000
TIER_THRESHOLD_MID_CENTS = 20_000_000
DISCOUNT_MAJOR = Decimal("0.04")
DISCOUNT_LARGE = Decimal("0.025")
DISCOUNT_MID = Decimal("0.01")
DISCOUNT_NONE = Decimal("0.0")


def _tier_discount(leverage_tier: str, trailing_cents: int) -> Decimal:
    if leverage_tier == "MAJOR" and trailing_cents >= TIER_THRESHOLD_MAJOR_CENTS:
        return DISCOUNT_MAJOR
    if leverage_tier == "LARGE" and trailing_cents >= TIER_THRESHOLD_LARGE_CENTS:
        return DISCOUNT_LARGE
    if leverage_tier == "MID" and trailing_cents >= TIER_THRESHOLD_MID_CENTS:
        return DISCOUNT_MID
    return DISCOUNT_NONE


def compute_provisional_share(net_cents: int, reverse_comp_pct, leverage_tier: str, current_trailing_cents: int) -> int:
    """PROVISIONAL: round_half_up(net * pct), then round_half_up(base * (1 - discount))."""
    pct = Decimal(str(reverse_comp_pct))
    net = Decimal(int(net_cents))
    base_share = (net * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    discount = _tier_discount(leverage_tier, current_trailing_cents)
    provisional = (base_share * (Decimal(1) - discount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(provisional)


def compute_final_share(net_cents: int, reverse_comp_pct, leverage_tier: str, prior_trailing_cents: int) -> int:
    """FINAL: ceil(net * pct * (1 - discount_prior))."""
    pct = Decimal(str(reverse_comp_pct))
    net = Decimal(int(net_cents))
    discount = _tier_discount(leverage_tier, prior_trailing_cents)
    raw = net * pct * (Decimal(1) - discount)
    # Ceiling to integer cents
    final_share = int(math.ceil(raw))
    return final_share


# ---- StationGroup.aggregate_retrans_cents recompute ----
def recompute_group_aggregate(station_group_id: str, current_period_index: int):
    """Rolling 4-period sum of net retrans revenue across all stations in this group.

    Per PRD §3.1: "Rolling 4-period sum of net retrans revenue across all Stations in
    this group; recomputed on every PeriodSettlement commit" — interpreted as the sum
    of net_retrans_cents over settlements in the trailing 4 periods (current-3..current),
    including COMMITTED and RECONCILED settlements (net is only set on commit).
    """
    sg = store.station_groups.get(station_group_id)
    if sg is None:
        return
    lower = current_period_index - 3
    total = 0
    for s in store.retrans_settlements.values():
        if s.get("status") not in ("COMMITTED", "RECONCILED"):
            continue
        if s.get("period_index") is None:
            continue
        if s["period_index"] < lower or s["period_index"] > current_period_index:
            continue
        station = store.stations.get(s.get("station_id"))
        if station is None:
            continue
        if station.get("station_group_id") != station_group_id:
            continue
        net = s.get("net_retrans_cents")
        if net is None:
            continue
        total += int(net)
    sg["aggregate_retrans_cents"] = total
