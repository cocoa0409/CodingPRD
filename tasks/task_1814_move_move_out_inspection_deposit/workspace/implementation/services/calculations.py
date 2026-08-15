"""Calculation rules (scaffold Table 3 / PRD §3.4, §3.6).

All money math is integer cents with round-half-up at the pinned points.
"""
from datetime import timedelta

from util import parse_date, round_half_up_int

DAYS_PER_YEAR = 365


def deposit_interest(tenancy, jurisdiction) -> int:
    """deposit_interest: accrual through move_out_on (PRD §3.4).

    ACTUAL_DAYS: round_half_up(deposit * rate_bp / 10000 * days / 365) once.
    WHOLE_YEARS: per-year round_half_up(deposit * rate_bp / 10000), summed per
    completed 365-day year (rounding order pinned: per year, then sum).
    """
    if not jurisdiction["interest_required"]:
        return 0
    move_in = parse_date(tenancy["move_in_on"])
    move_out = parse_date(tenancy["move_out_on"])
    days = (move_out - move_in).days
    if days <= 0:
        return 0
    deposit = tenancy["deposit_cents"]
    rate_bp = jurisdiction["annual_interest_rate_bp"]
    if jurisdiction["interest_basis"] == "ACTUAL_DAYS":
        return round_half_up_int(deposit * rate_bp * days, 10000 * DAYS_PER_YEAR)
    # WHOLE_YEARS
    years = days // DAYS_PER_YEAR
    per_year = round_half_up_int(deposit * rate_bp, 10000)
    return per_year * years


def damage_charge(item, unit, jurisdiction, move_out_on) -> int:
    """damage_charge: straight-line residual schedule (PRD §3.4).

    CARPET/PAINT: residual_fraction = max(0, life_days - age_days) / life_days;
      DEPRECIATED (default): round_half_up(replacement * residual_fraction);
      ACTUAL_COST (jurisdiction allows + actual_repair_cents provided):
        min(actual_repair_cents, replacement_cost_cents), no depreciation.
    OTHER: full replacement cost (no schedule).
    A computed charge of exactly zero creates no deduction line.
    """
    replacement = item["replacement_cost_cents"]
    category = item["category"]
    if category == "OTHER":
        return replacement
    if category == "CARPET":
        installed_on = unit["carpet_installed_on"]
        life_days = unit["carpet_life_years"] * DAYS_PER_YEAR
    else:  # PAINT
        installed_on = unit["paint_applied_on"]
        life_days = unit["paint_life_years"] * DAYS_PER_YEAR
    if (jurisdiction["allow_actual_cost_charge"]
            and item.get("actual_repair_cents") is not None):
        return min(item["actual_repair_cents"], replacement)
    age_days = (parse_date(move_out_on) - parse_date(installed_on)).days
    remaining = max(0, life_days - age_days)
    if life_days <= 0:
        return 0
    return round_half_up_int(replacement * remaining, life_days)


def key_fob_lock_charges(tenancy, prop, jurisdiction):
    """key_fob_lock_charge (PRD §3.4): turnover-hardware lines from the
    counts snapshotted at move-out completion.

    Returns a list of (source, quantity, amount_cents, description).
    """
    lines = []
    missing_keys = tenancy["keys_issued"] - tenancy["keys_returned"]
    missing_fobs = tenancy["fobs_issued"] - tenancy["fobs_returned"]
    if missing_keys > 0:
        lines.append((
            "KEY_NOT_RETURNED",
            missing_keys,
            missing_keys * prop["key_charge_cents"],
            "Unreturned keys",
        ))
    if missing_fobs > 0:
        lines.append((
            "FOB_NOT_RETURNED",
            missing_fobs,
            missing_fobs * prop["fob_charge_cents"],
            "Unreturned fobs",
        ))
    if missing_keys > 0 and jurisdiction["lock_change_allowed"]:
        lines.append((
            "LOCK_CHANGE",
            1,
            prop["lock_change_cents"],
            "Lock change",
        ))
    return lines


def small_claims_exposure(dispute, statement, jurisdiction) -> int:
    """small_claims_exposure (PRD §3.6): base is the disputed amount; when the
    statement was late the base is multiplied by the bad-faith multiplier;
    capped at the jurisdiction's small-claims cap."""
    base = dispute["disputed_amount_cents"]
    if statement["late"]:
        base = base * jurisdiction["bad_faith_multiplier"]
    return min(jurisdiction["small_claims_cap_cents"], base)


def court_resolution_settlement(dispute, statement, jurisdiction, awarded):
    """court_resolution_settlement (PRD §3.6): returns penalty_cents.

    released_delta = awarded (applied by the caller);
    tenant_total_recovery = min(exposure, awarded * (late ? multiplier : 1));
    penalty = recovery - awarded (auto PENALTY disbursement when > 0).
    """
    multiplier = jurisdiction["bad_faith_multiplier"] if statement["late"] else 1
    tenant_total_recovery = min(dispute["exposure_cents"], awarded * multiplier)
    return tenant_total_recovery - awarded


def deadline_and_lateness(move_out_on, issued_dt, jurisdiction):
    """statement_totals issuance fields: deadline_on = move_out_on +
    deposit_return_deadline_days; late when date(issued_at) > deadline_on."""
    deadline = parse_date(move_out_on) + timedelta(
        days=jurisdiction["deposit_return_deadline_days"]
    )
    late = issued_dt.date() > deadline
    return deadline.isoformat(), late
