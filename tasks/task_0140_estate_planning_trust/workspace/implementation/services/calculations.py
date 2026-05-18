"""Pure-function calculation engine (SCAFFOLD §1.3).

Every monetary calculation operates in integer cents. The only places a
non-integer rate meets the integer ledger are the bond marginal-tier formula
(banker's rounding per tier, then sum, then add flat fee) and the fiduciary
risk score (half-up to 4 decimal places).
"""
from __future__ import annotations

from decimal import Decimal

from config import (
    BOND_FACTOR_WEIGHT,
    FILING_FACTOR_WEIGHT,
    FLAT_BOND_FEE_CENTS,
    SCORE_CEILING,
    SCORE_FLOOR,
    SETTLEMENT_WINDOW_DAYS,
    TIER1_LIMIT_CENTS,
    TIER1_RATE,
    TIER2_LIMIT_CENTS,
    TIER2_RATE,
    TIER3_RATE,
    TIME_FACTOR_WEIGHT,
)
from db import store
from utils import round_half_even, round_half_up


# ── Probate posture ────────────────────────────────────────────────────────

def compute_probate_posture(estate: dict) -> str:
    """Derived: SCAFFOLD §1.3 probate_posture.

    - admin_phase == CONTESTED      → FROZEN
    - any filing REVISION_REQUESTED → UNDER_COURT_REVIEW
    - else                           → OPEN
    """
    if estate["admin_phase"] == "CONTESTED":
        return "FROZEN"
    for f in store.filings.values():
        if f["estate_id"] == estate["id"] and f["status"] == "REVISION_REQUESTED":
            return "UNDER_COURT_REVIEW"
    return "OPEN"


# ── Gross estate value ─────────────────────────────────────────────────────

def compute_gross_estate_value(estate_id: str, variant: str) -> int:
    """SCAFFOLD §1.3 gross_estate_value.

    forward_looking — INVENTORIED at declared_value_cents,
                      APPRAISED & DISTRIBUTED at appraised_value_cents.
    chronological   — APPRAISED & DISTRIBUTED at appraised_value_cents only.
    """
    total = 0
    for a in store.assets.values():
        if a["estate_id"] != estate_id:
            continue
        status = a["status"]
        if variant == "forward_looking":
            if status == "INVENTORIED":
                total += a.get("declared_value_cents", 0) or 0
            elif status in ("APPRAISED", "DISTRIBUTED"):
                total += a.get("appraised_value_cents", 0) or 0
        elif variant == "chronological":
            if status in ("APPRAISED", "DISTRIBUTED"):
                total += a.get("appraised_value_cents", 0) or 0
        else:
            raise ValueError(f"Unknown gross_estate_value variant: {variant}")
    return total


# ── Required bond ──────────────────────────────────────────────────────────

def compute_required_bond(gross_cents: int) -> int:
    """SCAFFOLD §1.3 required_bond — marginal tiers + per-tier round-half-even
    then sum, then flat fee.
    """
    g = max(0, int(gross_cents))

    tier1_portion = min(g, TIER1_LIMIT_CENTS)
    tier2_portion = max(0, min(g, TIER2_LIMIT_CENTS) - TIER1_LIMIT_CENTS)
    tier3_portion = max(0, g - TIER2_LIMIT_CENTS)

    t1 = round_half_even(Decimal(tier1_portion) * Decimal(TIER1_RATE), 0)
    t2 = round_half_even(Decimal(tier2_portion) * Decimal(TIER2_RATE), 0)
    t3 = round_half_even(Decimal(tier3_portion) * Decimal(TIER3_RATE), 0)

    total = int(t1) + int(t2) + int(t3) + FLAT_BOND_FEE_CENTS
    return total


# ── Planned distribution waterfall ─────────────────────────────────────────

def compute_planned_distributions(estate_id: str) -> dict[str, int]:
    """SCAFFOLD §1.3 planned_distribution.

    For every APPRAISED Asset with at least one LOCKED designation:
      - sum locked share_basis_points
      - if < 10000, waterfall the shortfall in ascending priority_rank,
        ties broken by ascending designation.id (string)
      - each designation gets floor(appraised * allocated_bp / 10000) cents
      - any rounding remainder is distributed one cent at a time using the
        same order

    Returns: dict beneficiary_id → total planned cents.
    """
    by_beneficiary: dict[str, int] = {}

    # Group LOCKED designations by asset.
    locked_by_asset: dict[str, list[dict]] = {}
    for d in store.designations.values():
        if d["estate_id"] != estate_id:
            continue
        if d["status"] != "LOCKED":
            continue
        locked_by_asset.setdefault(d["asset_id"], []).append(d)

    for asset_id, designations in locked_by_asset.items():
        asset = store.assets.get(asset_id)
        if not asset or asset["status"] != "APPRAISED":
            continue
        appraised = asset.get("appraised_value_cents")
        if appraised is None or appraised <= 0:
            # Still credit zero — but skip if nothing to allocate.
            for d in designations:
                by_beneficiary.setdefault(d["beneficiary_id"], 0)
            continue

        # Order: ascending priority_rank, then ascending designation.id.
        ordered = sorted(designations,
                         key=lambda d: (d["priority_rank"], str(d["id"])))

        # Waterfall shortfall (allocated_share_bp = original + waterfall extra).
        total_bp = sum(d["share_basis_points"] for d in ordered)
        shortfall = max(0, 10000 - total_bp)
        allocated_bp = {d["id"]: d["share_basis_points"] for d in ordered}
        for d in ordered:
            if shortfall <= 0:
                break
            room = 10000 - allocated_bp[d["id"]]
            give = min(room, shortfall)
            allocated_bp[d["id"]] += give
            shortfall -= give

        # Per-designation floor cents.
        per_designation: dict[str, int] = {}
        sum_cents = 0
        for d in ordered:
            cents = (int(appraised) * allocated_bp[d["id"]]) // 10000
            per_designation[d["id"]] = cents
            sum_cents += cents

        # Distribute the rounding remainder (per-cent) using the same order.
        remainder = int(appraised) - sum_cents
        if remainder > 0:
            idx = 0
            while remainder > 0:
                target = ordered[idx % len(ordered)]
                per_designation[target["id"]] += 1
                remainder -= 1
                idx += 1

        # Aggregate per beneficiary.
        for d in ordered:
            bid = d["beneficiary_id"]
            by_beneficiary[bid] = by_beneficiary.get(bid, 0) + per_designation[d["id"]]

    return by_beneficiary


# ── Planned distribution total (for final accounting) ──────────────────────

def compute_planned_distribution_total(estate_id: str) -> int:
    total = 0
    for d in store.distributions.values():
        if d["estate_id"] != estate_id and d.get("estate_id") != estate_id:
            continue
        if d["status"] in ("PLANNED", "EXECUTED"):
            total += d.get("planned_amount_cents", 0) or 0
    return total


# ── Fiduciary risk score ───────────────────────────────────────────────────

def compute_fiduciary_risk_score(fiduciary: dict, estate: dict, variant: str) -> Decimal:
    """SCAFFOLD §1.3 fiduciary_risk_score.

    Returns a Decimal rounded half-up to 4 decimal places and clamped to
    [SCORE_FLOOR, SCORE_CEILING].

    variant: 'provisional' (forward_looking required_bond denominator) or
             'final' (chronological required_bond denominator).
    """
    now = store.logical_now()
    settle_due = estate.get("settlement_due_at")
    if settle_due is None:
        days_remaining = 0
    else:
        days_remaining = max(0, (settle_due - now).total_seconds() / 86400.0)
    time_factor = Decimal(str(days_remaining)) / Decimal(str(SETTLEMENT_WINDOW_DAYS))
    if time_factor > Decimal("1"):
        time_factor = Decimal("1")
    if time_factor < Decimal("0"):
        time_factor = Decimal("0")

    if variant == "provisional":
        gross = compute_gross_estate_value(estate["id"], "forward_looking")
    else:
        gross = compute_gross_estate_value(estate["id"], "chronological")
    required_bond = compute_required_bond(gross)
    bond_amount = fiduciary.get("bond_amount_cents") or 0
    if required_bond > 0:
        bond_factor = Decimal(bond_amount) / Decimal(required_bond)
    else:
        bond_factor = Decimal("0")

    # filing factor
    accepted = 0
    total = 0
    for f in store.filings.values():
        if f["estate_id"] != estate["id"]:
            continue
        if f["filed_by_fiduciary_id"] != fiduciary["id"]:
            continue
        total += 1
        if f["status"] == "ACCEPTED":
            accepted += 1
    denom = max(1, total)
    filing_factor = Decimal(accepted) / Decimal(denom)

    score = (Decimal(TIME_FACTOR_WEIGHT) * time_factor
             + Decimal(BOND_FACTOR_WEIGHT) * bond_factor
             + Decimal(FILING_FACTOR_WEIGHT) * filing_factor)

    score = round_half_up(score, 4)
    if score < Decimal(SCORE_FLOOR):
        score = Decimal(SCORE_FLOOR).quantize(Decimal("0.0001"))
    if score > Decimal(SCORE_CEILING):
        score = Decimal(SCORE_CEILING).quantize(Decimal("0.0001"))
    return score


# ── Recompute & cache gross on estate ──────────────────────────────────────

def recompute_estate_gross(estate: dict, variant: str = "forward_looking"):
    """Refresh estate.gross_estate_value_cents using the supplied variant.

    Default forward_looking, used by Asset transitions (INVENTORIED→APPRAISED,
    APPRAISED→DISTRIBUTED) and Estate IN_PROBATE→INVENTORIED side effects.
    """
    estate["gross_estate_value_cents"] = compute_gross_estate_value(
        estate["id"], variant
    )
