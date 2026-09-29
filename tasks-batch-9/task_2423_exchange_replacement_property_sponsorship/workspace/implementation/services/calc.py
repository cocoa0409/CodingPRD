"""The twenty-one calculations of PRD section 3.

Every step is exact rational arithmetic; rounding happens only where the PRD
pins it, in the order the PRD pins it.
"""
from fractions import Fraction

import constants as C
from util import (
    F, ceil_div, days_inclusive, floor_div, frac4, fractional_part, ratio4,
    round_half_up, whole_days_between,
)


# ---------------------------------------------------------------------------
# property_depreciable_basis
# ---------------------------------------------------------------------------
def depreciable_basis(purchase_price_cents):
    return round_half_up(F(purchase_price_cents) * C.LAND_EXCLUSION_COMPLEMENT)


def annual_depreciation(depreciable_basis_cents):
    return round_half_up(F(depreciable_basis_cents) / C.DEPRECIATION_RECOVERY_YEARS)


# ---------------------------------------------------------------------------
# offering_capital_stack_grossup  (five pinned steps)
# ---------------------------------------------------------------------------
def capital_stack(purchase_price_cents, closing_costs_cents, loan_principal_cents,
                  reserve_funding_pct, load_pct, total_units, unit_price_cents):
    initial_reserve = round_half_up(F(purchase_price_cents) * F(reserve_funding_pct))
    net_acquisition = purchase_price_cents + closing_costs_cents - loan_principal_cents
    base_need = net_acquisition + initial_reserve
    load_pct_bps = round_half_up(F(load_pct) * C.BPS_SCALE)
    if load_pct_bps >= C.BPS_SCALE:
        load_pct_bps = C.BPS_SCALE - 1
    target_equity = ceil_div(base_need * C.BPS_SCALE, C.BPS_SCALE - load_pct_bps)
    sponsor_load = target_equity - base_need
    return {
        "purchase_price_cents": purchase_price_cents,
        "closing_costs_cents": closing_costs_cents,
        "loan_principal_cents": loan_principal_cents,
        "initial_reserve_cents": initial_reserve,
        "net_acquisition_cents": net_acquisition,
        "base_need_cents": base_need,
        "target_equity_cents": target_equity,
        "sponsor_load_cents": sponsor_load,
        "unit_capacity_cents": total_units * unit_price_cents,
    }


# ---------------------------------------------------------------------------
# investor_suitability_cap
# ---------------------------------------------------------------------------
def suitability_cap(entity_type, accreditation_method, annual_income_cents,
                    net_worth_cents, liquid_net_worth_cents, target_equity_cents):
    band = C.LIQUID_CAP_BY_ENTITY_TYPE[entity_type]
    liquid_cap = floor_div(F(liquid_net_worth_cents) * band)
    if accreditation_method == "SELF_CERT_INCOME":
        means_cap = floor_div(F(annual_income_cents) * C.INCOME_MULTIPLE)
    else:
        means_cap = floor_div(F(net_worth_cents) * C.NET_WORTH_PCT)
    deal_cap = floor_div(F(target_equity_cents or 0) * C.DEAL_CONCENTRATION_PCT)
    return min(liquid_cap, means_cap, deal_cap)


# ---------------------------------------------------------------------------
# exchange_file_deadlines
# ---------------------------------------------------------------------------
def exchange_deadlines(relinquished_closed_on):
    from util import deadline_after_days
    return (
        deadline_after_days(relinquished_closed_on, C.IDENTIFICATION_DAYS),
        deadline_after_days(relinquished_closed_on, C.EXCHANGE_DAYS),
    )


# ---------------------------------------------------------------------------
# identification_rule_capacity
# ---------------------------------------------------------------------------
def identification_rule_ok(rule, active_fmv_values, pending_fmv,
                           relinquished_sale_price_cents):
    values = list(active_fmv_values) + [pending_fmv]
    if rule == "THREE_PROPERTY":
        return len(values) <= C.MAX_IDENTIFIED_PROPERTIES
    total = sum(values)
    return total * 100 <= relinquished_sale_price_cents * C.TWO_HUNDRED_PCT_LIMIT


# ---------------------------------------------------------------------------
# subscription_boot
# ---------------------------------------------------------------------------
def subscription_boot(loan_principal_cents, units_requested, total_units,
                      investment_amount_cents, net_proceeds_cents, debt_retired_cents):
    debt_share = round_half_up(
        F(loan_principal_cents) * units_requested / total_units
    ) if total_units else 0
    replacement_value = investment_amount_cents + debt_share
    relinquished_value = net_proceeds_cents + debt_retired_cents
    return max(0, relinquished_value - replacement_value)


# ---------------------------------------------------------------------------
# loan_ltv_check / loan_dscr
# ---------------------------------------------------------------------------
def loan_ltv(principal_cents, appraised_value_cents):
    pct = ratio4(F(round_half_up(F(principal_cents) * C.BPS_SCALE / appraised_value_cents)) / 100)
    ok = principal_cents * C.BPS_SCALE <= appraised_value_cents * C.MAX_LTV_BPS
    return pct, ok


def annual_debt_service(principal_cents, rate_bps):
    return round_half_up(F(principal_cents) * rate_bps / C.BPS_SCALE)


def loan_dscr(principal_cents, rate_bps, annual_noi_cents):
    ads = annual_debt_service(principal_cents, rate_bps)
    if ads == 0:
        value = ratio4(0)
        ok = True
    else:
        value = ratio4(F(round_half_up(F(annual_noi_cents) * C.BPS_SCALE / ads)) / C.BPS_SCALE)
        ok = annual_noi_cents * C.BPS_SCALE >= ads * C.MIN_DSCR_BPS
    return value, ok


# ---------------------------------------------------------------------------
# distribution_reserve_replenishment / distribution_distributable
# ---------------------------------------------------------------------------
def period_days(period_start, period_end):
    return whole_days_between(period_start, period_end)


def reserve_replenishment(base_rent_annual_cents, reserve_target_pct, days):
    replenish_annual = round_half_up(F(base_rent_annual_cents) * F(reserve_target_pct))
    return round_half_up(F(replenish_annual) * days / C.DAYS_IN_YEAR)


def provisional_gross(base_rent_annual_cents, supplemental_rent_annual_cents,
                      loan_principal_cents, rate_bps, days):
    accrued_base = round_half_up(F(base_rent_annual_cents) * days / C.DAYS_IN_YEAR)
    accrued_supplemental = round_half_up(
        F(supplemental_rent_annual_cents) * days / C.DAYS_IN_YEAR)
    scheduled_debt_service = round_half_up(
        F(annual_debt_service(loan_principal_cents, rate_bps)) * days / C.DAYS_IN_YEAR)
    return accrued_base + accrued_supplemental - scheduled_debt_service


# ---------------------------------------------------------------------------
# distribution_allocation_rounding  (round-then-sweep)
# ---------------------------------------------------------------------------
def allocate(amount_cents, rows, denominator):
    """``rows`` is an ordered list of (subscription_id, units).

    Returns a list of dicts in the same order carrying the four pinned
    outputs, with the residual swept so the allocated total is exact.
    """
    out = []
    for subscription_id, units in rows:
        if denominator:
            raw = frac4(F(amount_cents) * units / denominator)
        else:
            raw = Fraction(0)
        out.append({
            "subscription_id": subscription_id,
            "units": units,
            "_raw": raw,
            "raw_share_cents": ratio4(raw),
            "allocated_cents": round_half_up(raw),
            "residual_adjustment_cents": 0,
        })
    residual = amount_cents - sum(r["allocated_cents"] for r in out)
    if residual and out:
        indexed = list(enumerate(out))
        if residual > 0:
            order = sorted(indexed, key=lambda p: (-fractional_part(p[1]["_raw"]), p[0]))
            step = 1
        else:
            order = sorted(indexed, key=lambda p: (fractional_part(p[1]["_raw"]), p[0]))
            step = -1
        for _, row in order[:abs(residual)]:
            row["allocated_cents"] += step
            row["residual_adjustment_cents"] = step
    for row in out:
        row.pop("_raw", None)
    return out


# ---------------------------------------------------------------------------
# tax_statement_trust_totals / tax_statement_allocation
# ---------------------------------------------------------------------------
def held_days(acquired_at, tax_year):
    from datetime import date
    if acquired_at is None:
        return 0
    days = days_inclusive(
        date(acquired_at.year, acquired_at.month, acquired_at.day),
        date(tax_year, 12, 31),
    )
    if days < 0:
        days = 0
    return min(days, C.DAYS_IN_YEAR)


def trust_depreciation(depreciable_basis_cents, acquired_at, tax_year):
    annual = annual_depreciation(depreciable_basis_cents)
    days = held_days(acquired_at, tax_year)
    return round_half_up(F(annual) * days / C.DAYS_IN_YEAR)


def unit_days(units_requested, closed_at, tax_year):
    from datetime import date
    if closed_at is None:
        return 0
    return units_requested * days_inclusive(
        date(closed_at.year, closed_at.month, closed_at.day),
        date(tax_year, 12, 31),
    )


def tax_allocation(rental_total, interest_total, depreciation_total, share):
    rental = round_half_up(F(rental_total) * share)
    interest = round_half_up(F(interest_total) * share)
    depreciation = round_half_up(F(depreciation_total) * share)
    return {
        "rental_income_cents": rental,
        "interest_expense_cents": interest,
        "depreciation_cents": depreciation,
        "net_taxable_income_cents": rental - interest - depreciation,
    }


# ---------------------------------------------------------------------------
# exit_consent_tally / exit_net_proceeds
# ---------------------------------------------------------------------------
def consent_tally(consented_units, units_issued, consent_threshold_pct):
    threshold_bps = round_half_up(F(consent_threshold_pct) * C.BPS_SCALE)
    if units_issued:
        pct = ratio4(F(round_half_up(F(consented_units) * C.BPS_SCALE / units_issued)) / C.BPS_SCALE)
    else:
        pct = ratio4(0)
    ok = consented_units * C.BPS_SCALE >= threshold_bps * units_issued
    return pct, ok


def exit_net_proceeds(exit_mode, gross_price_cents, selling_costs_cents,
                      loan_principal_cents):
    if exit_mode == "ASSET_SALE":
        return gross_price_cents - selling_costs_cents - loan_principal_cents
    return gross_price_cents - selling_costs_cents


def per_unit(net_proceeds_cents, units_issued):
    if not units_issued:
        return 0
    return floor_div(F(net_proceeds_cents) / units_issued)
