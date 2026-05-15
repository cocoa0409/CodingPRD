"""Domain calculations: life stage, portion, totals, recipe selector, address verify."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from app.clock import logical_clock
from app.errors import api_error
from app.utils import (
    parse_iso,
    parse_iso_date,
    round_half_up_2,
    round_half_up_int,
)


# ----------------------------------------------------------------------------
# Life stage
# ----------------------------------------------------------------------------
DOG_PUPPY_MAX_MONTHS = 12
DOG_ADULT_MAX_MONTHS = 84
CAT_PUPPY_MAX_MONTHS = 12
CAT_ADULT_MAX_MONTHS = 120


def compute_life_stage(species: str, birthdate_str: str) -> str:
    bd = parse_iso_date(birthdate_str)
    if bd is None:
        return "ADULT"
    now = logical_clock.now()
    # Use date-only deltas — count whole 30-day intervals between birthdate and current UTC date.
    days = (now.date() - bd.date()).days
    if days < 0:
        days = 0
    months = days // 30
    if species == "DOG":
        if months < DOG_PUPPY_MAX_MONTHS:
            return "PUPPY_KITTEN"
        if months < DOG_ADULT_MAX_MONTHS:
            return "ADULT"
        return "SENIOR"
    else:  # CAT
        if months < CAT_PUPPY_MAX_MONTHS:
            return "PUPPY_KITTEN"
        if months < CAT_ADULT_MAX_MONTHS:
            return "ADULT"
        return "SENIOR"


# ----------------------------------------------------------------------------
# Portion (grams/day)
# ----------------------------------------------------------------------------
ACTIVITY_FACTORS = {"LOW": Decimal("1.2"), "MODERATE": Decimal("1.6"), "HIGH": Decimal("2.0")}
LIFE_STAGE_FACTORS = {"PUPPY_KITTEN": Decimal("1.8"), "ADULT": Decimal("1.0"), "SENIOR": Decimal("0.8")}
RER_COEFFICIENT = Decimal("70")


def _decimal_power(base: Decimal, exponent: Decimal) -> Decimal:
    """Compute base ** exponent using Decimal precision via natural-log identity."""
    # Decimal supports ** for non-integer exponents in Python 3.
    return (base ** exponent)


def compute_portion_grams_per_day(
    weight_kg: float, activity_level: str, life_stage: str, kcal_per_gram: float
) -> int:
    weight_d = Decimal(str(weight_kg))
    rer = RER_COEFFICIENT * _decimal_power(weight_d, Decimal("0.75"))
    daily_kcal = rer * ACTIVITY_FACTORS[activity_level] * LIFE_STAGE_FACTORS[life_stage]
    grams_raw = daily_kcal / Decimal(str(kcal_per_gram))
    return round_half_up_int(grams_raw)


def compute_portion_with_delta(
    weight_kg: float,
    activity_level: str,
    life_stage: str,
    kcal_per_gram: float,
    portion_delta_pct: int,
) -> int:
    """Feedback-adjusted variant — apply delta percentage to provisional value, re-round."""
    provisional = compute_portion_grams_per_day(weight_kg, activity_level, life_stage, kcal_per_gram)
    factor = Decimal(1) + Decimal(portion_delta_pct) / Decimal(100)
    adjusted = Decimal(provisional) * factor
    return round_half_up_int(adjusted)


# ----------------------------------------------------------------------------
# Order totals
# ----------------------------------------------------------------------------
FREE_THRESHOLD_CENTS = 8000
MID_THRESHOLD_CENTS = 4000
MID_FEE_CENTS = 499
HIGH_FEE_CENTS = 999
TRIAL_DISCOUNT = Decimal("0.5")


def compute_line_total_cents(total_grams: int, unit_price_cents_per_100g: int) -> int:
    cents = (Decimal(total_grams) / Decimal(100)) * Decimal(unit_price_cents_per_100g)
    return round_half_up_int(cents)


def compute_shipping_fee(subtotal_cents: int) -> int:
    if subtotal_cents >= FREE_THRESHOLD_CENTS:
        return 0
    if subtotal_cents >= MID_THRESHOLD_CENTS:
        return MID_FEE_CENTS
    return HIGH_FEE_CENTS


def apply_trial_discount(subtotal_cents: int) -> int:
    return round_half_up_int(Decimal(subtotal_cents) * TRIAL_DISCOUNT)


# ----------------------------------------------------------------------------
# Address verification (PRD §3.1)
# ----------------------------------------------------------------------------
SUPPORTED_COUNTRIES = {"US", "CA", "UK", "AU", "DE", "FR", "JP", "CN"}
US_POSTAL_RE = re.compile(r"^\d{5}(-\d{4})?$")


def verify_address_inplace(address: Optional[Dict[str, Any]]) -> bool:
    """Run address_verification calc; mutate `verified` in place. Returns True if verified."""
    if not isinstance(address, dict):
        return False
    country = address.get("country")
    postal = address.get("postal_code")
    line1 = address.get("line1")
    city = address.get("city")
    ok = True
    if country not in SUPPORTED_COUNTRIES:
        ok = False
    elif not isinstance(postal, str) or len(postal) == 0:
        ok = False
    elif country == "US" and not US_POSTAL_RE.match(postal):
        ok = False
    elif not isinstance(line1, str) or len(line1.strip()) == 0:
        ok = False
    elif not isinstance(city, str) or len(city.strip()) == 0:
        ok = False
    address["verified"] = ok
    return ok


# ----------------------------------------------------------------------------
# Recipe selector
# ----------------------------------------------------------------------------
VET_PRESCRIBED_BONUS = 40
LIFE_STAGE_MATCH = 30
PREFERRED_INGREDIENT_WEIGHT = 10
AVERSION_PENALTY = 5
INTOLERANCE_PENALTY = 15


def recipe_passes_hard_gates(
    recipe: Dict[str, Any],
    pet: Dict[str, Any],
    *,
    is_trial_cycle1: bool = False,
    rotation_block_monotony: Optional[str] = None,
    enforce_rotation: bool = True,
) -> Optional[str]:
    """Return None if recipe is eligible, else an error_id describing the eliminator.

    The first reason found wins so callers can raise the right error when this recipe
    is the only candidate. For ranking, callers only check `is None`.
    """
    # Species
    if recipe.get("target_species") != pet.get("species"):
        return "ERR_RECIPE_NOT_ELIGIBLE"
    # Life stage
    target_ls = recipe.get("target_life_stage")
    if target_ls != "ALL" and target_ls != pet.get("life_stage"):
        return "ERR_RECIPE_NOT_ELIGIBLE"

    all_ingredients = set(recipe.get("protein_sources", []) or []) | set(
        recipe.get("grain_sources", []) or []
    ) | set(recipe.get("supplement_sources", []) or [])

    # Allergen exclusion (strict)
    allergies = set(pet.get("allergies", []) or [])
    if allergies & all_ingredients:
        return "ERR_ALLERGEN_PROHIBITED"

    # Vet prescribed gate
    health = set(pet.get("health_conditions", []) or [])
    vet_prescribed = bool(recipe.get("vet_prescribed", False))
    prescribed_for = set(recipe.get("prescribed_for", []) or [])
    if health:
        # Strict variant: only vet_prescribed recipes whose prescribed_for intersects health
        if not vet_prescribed or not (prescribed_for & health):
            return "ERR_VET_PRESCRIBED_REQUIRED"
    else:
        # Relaxed variant: vet_prescribed recipes are eliminated
        if vet_prescribed:
            return "ERR_VET_PRESCRIBED_REQUIRED"

    # Trial gate
    if is_trial_cycle1 and not bool(recipe.get("trial_eligible", True)):
        return "ERR_RECIPE_NOT_ELIGIBLE"

    # Rotation
    if enforce_rotation and rotation_block_monotony is not None:
        if recipe.get("monotony_class") == rotation_block_monotony:
            return "ERR_ROTATION_VIOLATION"

    return None


def compute_match_score(recipe: Dict[str, Any], pet: Dict[str, Any]) -> int:
    score = 0
    if recipe.get("vet_prescribed"):
        # Reached here only when prescribed-gate already passed in eligibility.
        score += VET_PRESCRIBED_BONUS
    if recipe.get("target_life_stage") == pet.get("life_stage"):
        score += LIFE_STAGE_MATCH

    prot_supp = set(recipe.get("protein_sources", []) or []) | set(
        recipe.get("supplement_sources", []) or []
    )
    all_ing = prot_supp | set(recipe.get("grain_sources", []) or [])

    score += PREFERRED_INGREDIENT_WEIGHT * len(
        set(pet.get("dietary_preferences", []) or []) & prot_supp
    )
    score -= AVERSION_PENALTY * len(set(pet.get("dietary_aversions", []) or []) & all_ing)
    score -= INTOLERANCE_PENALTY * len(set(pet.get("intolerances", []) or []) & all_ing)
    return score


def build_explanation(recipe: Dict[str, Any], pet: Dict[str, Any], rotation_ok: bool) -> List[str]:
    expl: List[str] = []
    if recipe.get("target_life_stage") == pet.get("life_stage"):
        expl.append("LIFE_STAGE_MATCH")
    expl.append("ALLERGEN_CLEAR")
    prot_supp = set(recipe.get("protein_sources", []) or []) | set(
        recipe.get("supplement_sources", []) or []
    )
    if set(pet.get("dietary_preferences", []) or []) & prot_supp:
        expl.append("PREFERRED_PROTEIN_HIT")
    if rotation_ok:
        expl.append("ROTATION_OK")
    return expl
