"""Business logic: computed fields, MAGI/asset determinations, the ledger.

All money is integer cents. Rounding uses round-half-up. We use Decimal for
the half-up rounding steps to avoid float error (PRD §2.7).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db
from common import touch

# --- Constants (scaffold §1.3) ----------------------------------------------
FPL_DISREGARD_PCT = Decimal("0.05")
MONTHS_PER_YEAR = 12
ADULT_AGE_FLOOR = 19
EXEMPT_BURIAL_CAP_CENTS = 150000  # $1,500

# MAGI countability by income_type (PRD §3.2).
NON_COUNTABLE_INCOME = {"CHILD_SUPPORT", "TANF", "GIFT"}

ADULT_RELATIONSHIPS = {"SELF", "SPOUSE", "OTHER", "DEPENDENT"}


def round_half_up(value) -> int:
    """Round a numeric/Decimal value to the nearest integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- Derived helpers on entities --------------------------------------------

def is_income_countable(income_type: str) -> bool:
    return income_type not in NON_COUNTABLE_INCOME


def counted_members(household_id: str) -> list:
    return [
        m for m in db.members.values()
        if m["household_id"] == household_id and m["member_status"] == "COUNTED"
    ]


def recompute_household_size(household_id: str) -> None:
    hh = db.households.get(household_id)
    if hh is None:
        return
    hh["household_size"] = len(counted_members(household_id))
    touch(hh)


def member_income_sources(member_id: str) -> list:
    return [s for s in db.income_sources.values() if s["member_id"] == member_id]


def household_assets(household_id: str) -> list:
    return [a for a in db.assets.values() if a["household_id"] == household_id]


# --- Asset exemption / countable value (PRD §3.2 + §3.6) --------------------

def compute_asset_countable(asset: dict, household_id: str) -> tuple[bool, int]:
    """Return (is_exempt, countable_value_cents) for one asset, contextual to
    the household's other assets (one highest-value VEHICLE is exempt)."""
    atype = asset["asset_type"]
    value = asset["value_cents"]
    if atype == "HOME":
        return True, 0
    if atype == "VEHICLE":
        # The single highest-value vehicle is exempt; ties broken by created_at
        # then sequence (earliest wins) so the choice is deterministic.
        vehicles = [a for a in household_assets(household_id) if a["asset_type"] == "VEHICLE"]
        if vehicles:
            top = max(vehicles, key=lambda a: (a["value_cents"], -a.get("_seq", 0)))
            if top["id"] == asset["id"]:
                return True, 0
        return False, value
    if atype == "BURIAL_FUND":
        excess = max(value - EXEMPT_BURIAL_CAP_CENTS, 0)
        return (excess == 0), excess
    return False, value


def refresh_asset_derived(asset: dict) -> None:
    """Recompute is_exempt + countable_value_cents on an asset row in place."""
    is_exempt, countable = compute_asset_countable(asset, asset["household_id"])
    asset["is_exempt"] = is_exempt
    asset["countable_value_cents"] = countable


def refresh_household_assets_derived(household_id: str) -> None:
    """Adding a new asset can change which VEHICLE is the highest-value one, so
    recompute derived fields across all of the household's assets."""
    for a in household_assets(household_id):
        refresh_asset_derived(a)


# --- FPL base ---------------------------------------------------------------

def fpl_base_for_size(fpl_schedule: dict, household_size: int) -> int:
    size = max(household_size, 1)
    return fpl_schedule["base_annual_cents"] + (size - 1) * fpl_schedule["per_member_increment_cents"]


# --- MAGI income calculation (scaffold magi_annual_income, PRD §3.4) ---------

def compute_magi_annual_cents(household_id: str, magi_variant: str, fpl_schedule: dict, household_size: int) -> int:
    members = counted_members(household_id)
    gross_annual_cents = 0
    for m in members:
        sources = [s for s in member_income_sources(m["id"]) if s["is_magi_countable"]]
        if magi_variant == "POINT_IN_TIME":
            monthly_sum = sum(s["monthly_amount_cents"] for s in sources)
            member_annual = round_half_up(monthly_sum * MONTHS_PER_YEAR)
        else:  # PROJECTED_ANNUAL
            projected_sum = sum(s["projected_annual_cents"] for s in sources)
            member_annual = round_half_up(projected_sum)
        gross_annual_cents += member_annual  # sum AFTER per-member rounding

    base = fpl_base_for_size(fpl_schedule, household_size)
    disregard = round_half_up(FPL_DISREGARD_PCT * Decimal(base))
    magi = gross_annual_cents - disregard
    return max(magi, 0)


def has_adult_household(household_id: str) -> bool:
    for m in counted_members(household_id):
        if m["relationship"] in ADULT_RELATIONSHIPS and m["age"] >= ADULT_AGE_FLOOR:
            return True
    return False


# --- Asset calculation (scaffold countable_assets_and_eligibility, PRD §3.6) -

def compute_countable_assets_cents(household_id: str) -> int:
    total = 0
    for a in household_assets(household_id):
        _exempt, countable = compute_asset_countable(a, household_id)
        total += countable
    return total


def household_has_disabled_counted_member(household_id: str) -> bool:
    return any(m.get("is_disabled") for m in counted_members(household_id))


# --- Ledger (scaffold ledger_reconciliation, PRD §2.6) ----------------------

def credit_ledger(household: dict, member_months: int) -> None:
    household["covered_member_months"] = household.get("covered_member_months", 0) + member_months
    household["active_enrollment_count"] = household.get("active_enrollment_count", 0) + 1
    touch(household)


def debit_ledger(household: dict, member_months: int) -> None:
    household["covered_member_months"] = household.get("covered_member_months", 0) - member_months
    household["active_enrollment_count"] = household.get("active_enrollment_count", 0) - 1
    touch(household)
