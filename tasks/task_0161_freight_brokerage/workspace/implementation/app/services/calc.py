"""Calculation engine: linehaul, detention, factoring haircut, safety score.

All money is stored in integer cents. Floating-point arithmetic is permitted
only inside the factoring-haircut tier multiplication; the result is rounded
once, half-up, to a whole number of cents using ``decimal.Decimal``.
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from ..errors import ApiError, ERR_RATE_CONTRACT_AMBIGUOUS, ERR_RATE_CONTRACT_NOT_FOUND
from ..store import store
from ..timeutil import parse_iso


# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
SPOT_BASE_CENTS_PER_EQUIPMENT = {"DRY_VAN": 30000, "REEFER": 50000, "FLATBED": 40000}
SPOT_PER_UNIT_CENTS = {"DRY_VAN": 10, "REEFER": 18, "FLATBED": 14}

DETENTION_INCREMENT_MINUTES = 15

TIER_A_CAP_CENTS = 100_000
TIER_B_CAP_CENTS = 500_000
TIER_A_RATE = Decimal("0.030")
TIER_B_RATE = Decimal("0.020")
TIER_C_RATE = Decimal("0.010")

CLAIM_TYPE_PENALTY = {"DAMAGE": 100, "SHORTAGE": 60, "OVERCHARGE": 30, "LATE_DELIVERY": 40}
SMARTWAY_BREACH_PENALTY = 50
SAFETY_SUSPEND_THRESHOLD = 600
SAFETY_REQUALIFY_THRESHOLD = 700


def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal value to the nearest cent, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Quote linehaul
# ---------------------------------------------------------------------------
def resolve_rate_contract(
    *,
    brokerage_id: str,
    shipper_id: str,
    origin_zip: str,
    destination_zip: str,
    equipment_type: str,
    rate_contract_id: Optional[str],
    clock_now,
) -> Optional[dict]:
    """Return the single matching ACTIVE RateContract or None.

    Raises ``ERR_RATE_CONTRACT_NOT_FOUND`` if a non-null id was supplied but it
    does not resolve (does not exist, wrong brokerage, wrong shipper).

    Raises ``ERR_RATE_CONTRACT_AMBIGUOUS`` if more than one ACTIVE row matches
    the lane+equipment+shipper at ``clock_now``.

    Returns ``None`` (fall through to SPOT) if:
      * ``rate_contract_id`` was not supplied at all (PRD §3.4 — fall
        through unconditionally), or
      * a non-null id was supplied but its fields don't match the quote, or
      * the contract is not currently in its effective window.
    """
    # PRD §3.4: "If no rate contract matches, or if `rate_contract_id` was
    # not supplied at all, the engine falls through to the spot path with
    # `rate_source` set to `SPOT`."  So when no id was supplied we go SPOT
    # without any lane lookup.
    if rate_contract_id is None:
        return None

    # Pull all ACTIVE rate contracts for this shipper/lane/equipment at the clock.
    candidates: list[dict] = []
    for r in store.rate_contracts.values():
        if r.get("brokerage_id") != brokerage_id:
            continue
        if r.get("status") != "ACTIVE":
            continue
        if r.get("shipper_id") != shipper_id:
            continue
        if r.get("lane_origin_zip") != origin_zip:
            continue
        if r.get("lane_destination_zip") != destination_zip:
            continue
        if r.get("equipment_type") != equipment_type:
            continue
        try:
            ef = parse_iso(r["effective_from"])
            et = parse_iso(r["effective_to"])
        except Exception:  # noqa: BLE001
            continue
        if not (ef <= clock_now < et):
            continue
        candidates.append(r)

    # An id was supplied — it must exist in the brokerage.
    r = store.rate_contracts.get(rate_contract_id)
    if r is None or r.get("brokerage_id") != brokerage_id:
        raise ApiError(ERR_RATE_CONTRACT_NOT_FOUND, 404, "RateContract not found.")

    # If the supplied contract is in the candidate set, prefer it; if multiple
    # remain in the candidate set, that's still ambiguous.
    if len(candidates) > 1:
        raise ApiError(ERR_RATE_CONTRACT_AMBIGUOUS, 409, "Multiple matching active rate contracts.")
    if len(candidates) == 1 and candidates[0]["id"] == rate_contract_id:
        return candidates[0]
    # The id was supplied but does not match a candidate (wrong fields or window)
    # — fall through to SPOT.
    return None


def quote_linehaul(*, quote: dict, brokerage: dict, clock_now) -> Tuple[str, int]:
    """Run §1.3 quote_linehaul; return (rate_source, quoted_linehaul_cents)."""
    contract = resolve_rate_contract(
        brokerage_id=brokerage["id"],
        shipper_id=quote["shipper_id"],
        origin_zip=quote["origin_zip"],
        destination_zip=quote["destination_zip"],
        equipment_type=quote["equipment_type"],
        rate_contract_id=quote.get("rate_contract_id"),
        clock_now=clock_now,
    )
    if contract is not None:
        return "CONTRACT", int(contract["flat_rate_cents"])

    equipment = quote["equipment_type"]
    base = SPOT_BASE_CENTS_PER_EQUIPMENT[equipment]
    per_unit = SPOT_PER_UNIT_CENTS[equipment]
    try:
        origin = int(quote["origin_zip"])
        dest = int(quote["destination_zip"])
    except (TypeError, ValueError):
        # Per PRD ZIP codes are integers in the spot calc.  Invalid ZIPs
        # should have been rejected at QuoteRequest creation; treat as 0.
        origin = 0
        dest = 0
    distance_units = abs(dest - origin)
    return "SPOT", base + distance_units * per_unit


# ---------------------------------------------------------------------------
# Detention
# ---------------------------------------------------------------------------
def detention_cents(
    *,
    arrive,
    depart,
    free_minutes: int,
    rate_cents_per_15min: int,
) -> int:
    """Detention calc per PRD §3.7 / SCAFFOLD §1.3 detention_provisional/final.

    Pinned rounding order:
      1. chargeable_minutes = max(0, floor((depart-arrive).seconds/60) - free_minutes)
      2. chargeable_increments = ceil(chargeable_minutes / 15)
      3. cents = chargeable_increments * rate_cents_per_15min
    """
    if depart < arrive:
        return 0
    elapsed_seconds = int((depart - arrive).total_seconds())
    elapsed_minutes = elapsed_seconds // 60  # floor
    chargeable = elapsed_minutes - int(free_minutes)
    if chargeable <= 0:
        return 0
    increments = math.ceil(chargeable / DETENTION_INCREMENT_MINUTES)
    return int(increments) * int(rate_cents_per_15min)


# ---------------------------------------------------------------------------
# Factoring haircut
# ---------------------------------------------------------------------------
def factoring_haircut_cents(invoice_total: int) -> int:
    """Marginal tier haircut.  Sums un-rounded contributions, rounds once."""
    T = int(invoice_total)
    if T < 0:
        T = 0
    a_slice = min(T, TIER_A_CAP_CENTS)
    b_slice = max(0, min(T, TIER_B_CAP_CENTS) - TIER_A_CAP_CENTS)
    c_slice = max(0, T - TIER_B_CAP_CENTS)
    raw = (
        Decimal(a_slice) * TIER_A_RATE
        + Decimal(b_slice) * TIER_B_RATE
        + Decimal(c_slice) * TIER_C_RATE
    )
    return round_half_up_cents(raw)


def factoring_reserve_cents(invoice_total: int, reserve_pct: float) -> int:
    """reserve_cents = round_half_up(invoice_total * reserve_pct / 100)."""
    raw = Decimal(int(invoice_total)) * Decimal(str(reserve_pct)) / Decimal("100")
    return round_half_up_cents(raw)


# ---------------------------------------------------------------------------
# Safety score update
# ---------------------------------------------------------------------------
def safety_penalty(*, claim_type: str, smartway_required: bool, smartway_certified: bool) -> int:
    base = CLAIM_TYPE_PENALTY.get(claim_type, 0)
    if smartway_required and not smartway_certified:
        base += SMARTWAY_BREACH_PENALTY
    return int(base)
