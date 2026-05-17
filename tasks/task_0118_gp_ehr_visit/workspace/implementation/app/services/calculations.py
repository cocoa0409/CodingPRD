"""Calculation rules: CPT billing, BMI, prescription expiry, provider panel count."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..store import store

# Tier brackets (per scaffold §1.3 cpt_billing_allowed).
TIER1_CEILING_CENTS = 50000
TIER2_CEILING_CENTS = 200000
TIER1_FACTOR = Decimal("1.00")
TIER2_FACTOR = Decimal("0.95")
TIER3_FACTOR = Decimal("0.90")

# Prescription expiry windows (scaffold §1.3 prescription_expiry).
NON_CONTROLLED_DAYS = 365
SCHEDULE_III_V_DAYS = 180
SCHEDULE_II_DAYS = 30


def _round_half_up(value: Decimal) -> int:
    """Round a Decimal to the nearest integer half-up. Returns int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def modifier_multiplier(modifier: str | None) -> Decimal:
    """Per scaffold §1.3 step 2: '25'=1.25, '59'=1.00, 'TC'=0.65, '26'=0.35, else 1.00."""
    if modifier == "25":
        return Decimal("1.25")
    if modifier == "59":
        return Decimal("1.00")
    if modifier == "TC":
        return Decimal("0.65")
    if modifier == "26":
        return Decimal("0.35")
    return Decimal("1.00")


def cpt_billing_charge(catalog_row: dict, units: int) -> int:
    """Provisional list_charge_cents at line creation. No modifier, no telehealth."""
    return int(catalog_row["list_price_cents"]) * int(units)


def select_tier_factor(encounter_total_cents: int) -> Decimal:
    if encounter_total_cents <= TIER1_CEILING_CENTS:
        return TIER1_FACTOR
    if encounter_total_cents <= TIER2_CEILING_CENTS:
        return TIER2_FACTOR
    return TIER3_FACTOR


def cpt_billing_allowed_for_encounter(encounter_id: str) -> None:
    """Recompute allowed_amount_cents for every CptLineItem on the encounter.

    Implements scaffold §1.3 cpt_billing_allowed (tiered_pricing):
      1) per-line base = allowed_price_cents * units
      2) per-line after modifier mult, rounded HALF_UP -> per_line_cents
      3) encounter_total = sum(per_line_cents); pick tier_factor
      4) adjusted_total = round_half_up(encounter_total * tier_factor)
         apportion_i = round_half_up(per_line_cents_i * tier_factor)
         residual = adjusted_total - sum(apportion_i)
         assign residual to line with largest per_line_cents; tie-break smallest id (lex).
      Final: line.allowed_amount_cents = apportion_i + (residual if winner else 0)
    """
    s = store()
    # Gather lines for this encounter (in any stable order — we will sort as needed).
    lines = [li for li in s.cpt_line_items.values() if li["encounter_id"] == encounter_id]
    if not lines:
        return

    # Step 1-2: per-line cents (post-modifier, rounded HALF_UP per line).
    per_line: list[tuple[dict, int]] = []
    for li in lines:
        catalog = s.cpt_fee_catalog.get(li["cpt_code"])
        if catalog is None:
            # Shouldn't happen — line was created against an existing code.
            base_cents = 0
        else:
            base_cents = int(catalog["allowed_price_cents"]) * int(li["units"])
        mult = modifier_multiplier(li.get("modifier"))
        per_line_pre = Decimal(base_cents) * mult
        per_line_cents = _round_half_up(per_line_pre)
        per_line.append((li, per_line_cents))

    # Step 3: encounter total and tier.
    encounter_total = sum(plc for _li, plc in per_line)
    tier_factor = select_tier_factor(encounter_total)

    # Step 4: apportion and reconcile residual.
    adjusted_total = _round_half_up(Decimal(encounter_total) * tier_factor)
    apportioned: list[tuple[dict, int, int]] = []  # (line, per_line_cents, apportion_cents)
    apportion_sum = 0
    for li, plc in per_line:
        apportion = _round_half_up(Decimal(plc) * tier_factor)
        apportioned.append((li, plc, apportion))
        apportion_sum += apportion
    residual = adjusted_total - apportion_sum

    # Winner: greatest per_line_cents; tie -> smallest id lex.
    # We must pick from apportioned where the max per_line_cents wins.
    winner_idx = 0
    for i in range(1, len(apportioned)):
        cand_li, cand_plc, _ = apportioned[i]
        win_li, win_plc, _ = apportioned[winner_idx]
        if cand_plc > win_plc or (cand_plc == win_plc and cand_li["id"] < win_li["id"]):
            winner_idx = i

    # Apply.
    for i, (li, _plc, apportion) in enumerate(apportioned):
        if i == winner_idx:
            li["allowed_amount_cents"] = apportion + residual
        else:
            li["allowed_amount_cents"] = apportion


def compute_bmi(weight_kg: float, height_cm: float) -> float:
    """weight_kg / (height_cm/100)^2, rounded HALF_UP to 1 decimal."""
    if height_cm is None or height_cm == 0:
        return None  # type: ignore[return-value]
    height_m = Decimal(str(height_cm)) / Decimal("100")
    bmi = Decimal(str(weight_kg)) / (height_m * height_m)
    return float(bmi.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def prescription_expiry(signed_at, is_controlled: bool, dea_schedule: str | None):
    """signed_at + N days where N depends on controlled status / schedule."""
    if not is_controlled:
        days = NON_CONTROLLED_DAYS
    elif dea_schedule == "II":
        days = SCHEDULE_II_DAYS
    else:
        # III, IV, V
        days = SCHEDULE_III_V_DAYS
    return signed_at + timedelta(days=days)


def recompute_provider_panel(provider_id: str) -> int:
    """Provider.panel_size = count(Patient where pcp_provider_id == provider_id AND status == ACTIVE)."""
    s = store()
    count = 0
    for p in s.patients.values():
        if p.get("pcp_provider_id") == provider_id and p.get("status") == "ACTIVE":
            count += 1
    prov = s.providers.get(provider_id)
    if prov is not None:
        prov["panel_size"] = count
    return count
