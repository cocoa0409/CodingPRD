"""Application-submit snapshots and eligibility evaluation (PRD §3.2 / §3.3)."""

from decimal import Decimal

from core.errors import raise_error
from core.store import STORE
from services.calculations import (
    compute_applicant_magi,
    applicant_countable_assets,
    effective_household_size,
    fpl_threshold_amount,
    compute_total_magi,
    compute_fpl_percent,
)
from services.money import round2_float, to_decimal
from services.projections import (
    find_policy_by_state,
    list_applicants_of_household,
    list_income_of_applicant,
    list_assets_of_applicant,
)


def compute_snapshots(household: dict, rule_variant: str):
    """Return (snapshot_magi, snapshot_fpl_percent, snapshot_countable_assets, effective_size).

    Raises ERR_FPL_THRESHOLD_INVALID if effective_size == 0.
    """
    policy = find_policy_by_state(household["state_code"])
    if policy is None:
        raise_error("ERR_HOUSEHOLD_INCOMPLETE", "Household state_code does not reference a StatePolicy")
    applicants = list_applicants_of_household(household["id"])
    eff_size = effective_household_size(applicants)
    if eff_size <= 0:
        raise_error("ERR_FPL_THRESHOLD_INVALID", "Effective household size is zero")

    raw_sum = Decimal("0")
    asset_total = Decimal("0")
    state_exempt = list(policy.get("state_exempt_asset_types") or [])
    for a in applicants:
        if a["dependent_status"] == "EXCLUDED":
            continue
        a_magi = compute_applicant_magi(a, list_income_of_applicant(a["id"]))
        raw_sum += a_magi
        assets = list_assets_of_applicant(a["id"])
        a_assets = applicant_countable_assets(assets, rule_variant, state_exempt)
        asset_total += a_assets

    total_magi = compute_total_magi(raw_sum, rule_variant, policy)
    threshold = fpl_threshold_amount(eff_size, policy)
    if threshold <= 0:
        raise_error("ERR_FPL_THRESHOLD_INVALID", "FPL threshold is zero")
    fpl_pct = compute_fpl_percent(total_magi, threshold)
    return (
        round2_float(total_magi),
        round2_float(fpl_pct),
        round2_float(asset_total),
        eff_size,
    )


def check_application_eligibility(application: dict):
    """Raise ERR_NOT_ELIGIBLE if snapshot_fpl_percent > limit or asset test fails."""
    household = STORE.households.get(application["household_id"])
    if household is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    policy = find_policy_by_state(household["state_code"])
    if policy is None:
        raise_error("ERR_HOUSEHOLD_INCOMPLETE", "Household has no StatePolicy")
    snap_fpl = application.get("snapshot_fpl_percent")
    if snap_fpl is None:
        raise_error("ERR_FPL_THRESHOLD_INVALID", "Application has no snapshot_fpl_percent")
    limit_pct = to_decimal(policy["magi_income_limit_pct"])
    if to_decimal(snap_fpl) > limit_pct:
        raise_error("ERR_NOT_ELIGIBLE", "fpl_percent exceeds magi_income_limit_pct")
    if policy.get("asset_test_applies"):
        applicants = list_applicants_of_household(household["id"])
        eff_size = effective_household_size(applicants)
        per_member = to_decimal(policy.get("asset_limit_per_member", 0) or 0)
        ceiling = per_member * to_decimal(eff_size)
        snap_assets = to_decimal(application.get("snapshot_countable_assets") or 0)
        if snap_assets > ceiling:
            raise_error("ERR_NOT_ELIGIBLE", "Countable assets exceed the asset limit")
