"""Calculation rules (SCAFFOLD §1.3, PRD §2.7, §3.3, §3.5, §3.7, §3.9).

All monetary values are integer cents; all rounding is half-up via Decimal.
Blended index values are rounded half-up to 4 decimal places.
"""

from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _D(x) -> Decimal:
    """Coerce to Decimal without float artefacts."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round_half_up_cents(x) -> int:
    """Round a Decimal / number to integer cents, half-up."""
    return int(_D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(x) -> Decimal:
    """Round to 4 decimal places, half-up (PRD §2.7)."""
    return _D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _dec4_to_jsonable(d: Decimal):
    """Render a 4-dp Decimal as a JSON number. If integral, return int; else float
    with exactly the canonical decimal expansion (parsed through repr to avoid
    binary float noise like 1.1000000000000001)."""
    if d == d.to_integral_value():
        return int(d)
    return float(format(d.normalize(), "f"))


# ---------------------------------------------------------------------------
# blended_index_value (SCAFFOLD §1.3, PRD §3.3)
# ---------------------------------------------------------------------------

def effective_observations(index_id: str, window_end_date: str):
    """Set S: effective observations for (index, window_end_date)."""
    return [
        o for o in db.observations.values()
        if o["index_definition_id"] == index_id
        and o["window_end_date"] == window_end_date
        and o["is_effective"]
    ]


def compute_blend(index: dict, window_end_date: str):
    """Compute (blended_index_value Decimal 4dp, verification_method) or (None, None)
    when the effective set is empty.

    Source-priority override (PRD §3.3): STATION_PRIMARY with >=1 PHYSICAL_STATION
    row excludes GRID_MODEL rows; symmetrically for MODEL_PRIMARY.
    """
    obs = effective_observations(index["id"], window_end_date)
    if not obs:
        return None, None

    mode = index["source_priority_mode"]
    kinds = [db.stations[o["station_id"]]["station_kind"] for o in obs]
    if mode == "STATION_PRIMARY" and "PHYSICAL_STATION" in kinds:
        obs = [o for o in obs if db.stations[o["station_id"]]["station_kind"] == "PHYSICAL_STATION"]
    elif mode == "MODEL_PRIMARY" and "GRID_MODEL" in kinds:
        obs = [o for o in obs if db.stations[o["station_id"]]["station_kind"] == "GRID_MODEL"]

    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    for o in obs:
        w = _D(db.stations[o["station_id"]]["reliability_weight"])
        weighted_sum += _D(o["measured_value"]) * w
        weight_total += w
    blended = round_half_up_4dp(weighted_sum / weight_total)

    # verification_method: STATION_VERIFIED when the surviving blend used at
    # least one physical-station row; otherwise MODEL_FALLBACK.
    used_kinds = {db.stations[o["station_id"]]["station_kind"] for o in obs}
    method = "STATION_VERIFIED" if "PHYSICAL_STATION" in used_kinds else "MODEL_FALLBACK"
    return blended, method


def compute_max_tier(index: dict, blended) -> int:
    """Highest tier breached (inclusive boundary). 0 when none.

    BELOW: tier t breaches iff blended <= threshold_value
    ABOVE: tier t breaches iff blended >= threshold_value
    """
    if blended is None:
        return 0
    b = _D(blended)
    max_tier = 0
    for t in index["trigger_thresholds"]:
        thr = _D(t["threshold_value"])
        if index["strike_direction"] == "BELOW":
            if b <= thr:
                if int(t["tier"]) > max_tier:
                    max_tier = int(t["tier"])
        else:  # ABOVE
            if b >= thr:
                if int(t["tier"]) > max_tier:
                    max_tier = int(t["tier"])
    return max_tier


def payout_fraction_for_tier(index: dict, tier: int):
    """Return payout_fraction Decimal for a tier number, or None."""
    for t in index["trigger_thresholds"]:
        if int(t["tier"]) == int(tier):
            return _D(t["payout_fraction"])
    return None


# ---------------------------------------------------------------------------
# provisional_payout (forward-looking, uncapped) — PRD §3.6/§3.7
# ---------------------------------------------------------------------------

def provisional_payout_cents(policy: dict, index: dict, tier_applied: int) -> int:
    frac = payout_fraction_for_tier(index, tier_applied)
    return round_half_up_cents(_D(policy["sum_insured_cents"]) * frac)


def payout_for_tier(policy: dict, index: dict, tier: int) -> int:
    """Benchmark payout for a tier (dispute remedy benchmark, PRD §3.8)."""
    return round_half_up_cents(_D(policy["sum_insured_cents"]) * payout_fraction_for_tier(index, tier))


# ---------------------------------------------------------------------------
# final_payout (chronological, capped) — PRD §3.7
# ---------------------------------------------------------------------------

def coverage_year(date_str: str) -> int:
    """Calendar year of a YYYY-MM-DD window_end_date."""
    return int(date_str[:4])


def final_payout_cents(policy: dict, index: dict, claim: dict) -> int:
    """Chronological capped variant (PRD §3.7):
    prior = sum of final_payout_cents of this policy's claims in APPROVED/PAID/
            RECOVERY_CEDED with the same coverage-year as this claim's event window.
    uncapped = round_half_up(sum_insured * payout_fraction[tier_applied])
    final = min(uncapped, max(0, sum_insured - prior))
    """
    event = db.trigger_events[claim["trigger_event_id"]]
    year = coverage_year(event["window_end_date"])
    prior = 0
    for c in db.claims.values():
        if c["policy_id"] != policy["id"] or c["id"] == claim["id"]:
            continue
        if c["status"] not in ("APPROVED", "PAID", "RECOVERY_CEDED"):
            continue
        ev = db.trigger_events[c["trigger_event_id"]]
        if coverage_year(ev["window_end_date"]) == year:
            prior += int(c.get("final_payout_cents") or 0)
    frac = payout_fraction_for_tier(index, claim["tier_applied"])
    uncapped = round_half_up_cents(_D(policy["sum_insured_cents"]) * frac)
    headroom = max(0, int(policy["sum_insured_cents"]) - prior)
    return min(uncapped, headroom)


# ---------------------------------------------------------------------------
# premium_pricing — PRD §3.5
# ---------------------------------------------------------------------------

_LOADING = {
    "ADMITTED_INSURANCE": Decimal("0.25"),
    "SURPLUS_LINES": Decimal("0.35"),
    "DERIVATIVE_CONTRACT": Decimal("0.15"),
}
_TAX = {
    "ADMITTED_INSURANCE": Decimal("0.02"),
    "SURPLUS_LINES": Decimal("0.05"),
    "DERIVATIVE_CONTRACT": Decimal("0.00"),
}


def premium_pricing(sum_insured_cents: int, index: dict, regulatory_classification: str):
    """Return (premium_cents, premium_tax_cents).

    pure = sum_insured * historical_breach_frequency * expected_loss_ratio
    premium_cents = round_half_up(pure * (1 + loading))
    premium_tax_cents = round_half_up(premium_cents * tax)   # tax on loaded premium
    """
    pure = (
        _D(sum_insured_cents)
        * _D(index["historical_breach_frequency"])
        * _D(index["expected_loss_ratio"])
    )
    premium_cents = round_half_up_cents(pure * (Decimal("1") + _LOADING[regulatory_classification]))
    premium_tax_cents = round_half_up_cents(_D(premium_cents) * _TAX[regulatory_classification])
    return premium_cents, premium_tax_cents


# ---------------------------------------------------------------------------
# net_retained_exposure — PRD §3.9
# ---------------------------------------------------------------------------

def recompute_net_retained_exposure(program: dict) -> None:
    """retained = sum over BOUND policies (created_at ASC) of
    sum_insured - round_half_up(sum_insured * total_active_ceded_pct / 100).
    total_active_ceded_pct = min(100, sum of ceded_percentage over ACTIVE treaties).
    """
    active_treaties = [t for t in db.treaties.values()
                       if t["program_id"] == program["id"] and t["status"] == "ACTIVE"]
    total_ceded_pct = min(Decimal("100"), sum((_D(t["ceded_percentage"]) for t in active_treaties), Decimal("0")))
    bound = sorted(
        (p for p in db.policies.values()
         if p["program_id"] == program["id"] and p["lifecycle_status"] == "BOUND"),
        key=lambda p: p["created_at"],
    )
    retained = 0
    for p in bound:
        ceded_share = round_half_up_cents(_D(p["sum_insured_cents"]) * total_ceded_pct / Decimal("100"))
        retained += int(p["sum_insured_cents"]) - ceded_share
    program["net_retained_exposure_cents"] = retained


def recompute_fraud_alert_count(program: dict) -> None:
    """fraud_alert_count = number of claims currently in FRAUD_HOLD within the program."""
    count = 0
    for c in db.claims.values():
        if c["status"] != "FRAUD_HOLD":
            continue
        pol = db.policies.get(c["policy_id"])
        if pol and pol["program_id"] == program["id"]:
            count += 1
    program["fraud_alert_count"] = count


# ---------------------------------------------------------------------------
# cession_allocation waterfall — PRD §3.7/§3.9
# ---------------------------------------------------------------------------

def cession_waterfall(program: dict, claim: dict) -> int:
    """Run the reinsurance cession waterfall for an approved claim being released.

    Returns total ceded cents. Mutates treaties (recovered_to_date_cents, status).
    Per-treaty rounding half-up BEFORE summing (PRD §2.7). Treaties processed in
    created_at ASC order.
    """
    treaties = sorted(
        (t for t in db.treaties.values()
         if t["program_id"] == program["id"] and t["status"] == "ACTIVE"),
        key=lambda t: t["created_at"],
    )
    total_ceded = 0
    final_payout = int(claim["final_payout_cents"])
    for t in treaties:
        excess = max(0, final_payout - int(t["attachment_point_cents"]))
        gross_cede = round_half_up_cents(_D(excess) * _D(t["ceded_percentage"]) / Decimal("100"))
        room = int(t["treaty_limit_cents"]) - int(t["recovered_to_date_cents"])
        cede = min(gross_cede, max(0, room))
        if cede > 0 or True:
            t["recovered_to_date_cents"] = int(t["recovered_to_date_cents"]) + cede
            t["updated_at"] = db.now_iso()
            t["version"] = int(t["version"]) + 1
            if t["recovered_to_date_cents"] == int(t["treaty_limit_cents"]):
                t["status"] = "EXHAUSTED"
        total_ceded += cede
    return total_ceded
