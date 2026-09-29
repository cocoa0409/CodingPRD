"""Reserve funding studies (PRD 3.5).

The population is the referenced report's VERIFIED components in ascending
`created_at` order.  Per-component amounts are rounded *before* they are
summed: the fully funded contribution half up, the component-method annual
contribution to the ceiling.
"""

from fractions import Fraction

import store
from rounding import ceiling_frac, half_up_frac

CASH_FLOW_HORIZON_YEARS = 30
CASH_FLOW_FLOOR_CENTS_PER_UNIT = 25000
ADEQUATE_THRESHOLD_BP = 7000
TOTAL_BP = 10000


def verified_components(report_id):
    return [c for c in store.report_components(report_id)
            if c["verification_status"] == "VERIFIED"]


def fully_funded_balance(components):
    total = 0
    for component in components:
        denominator = (component["effective_age_years"]
                       + component["remaining_useful_life_years"])
        if denominator == 0:
            continue
        share = Fraction(
            component["replacement_cost_cents"]
            * component["effective_age_years"],
            denominator,
        )
        total += half_up_frac(share)
    return total


def component_method_annual(components):
    total = 0
    for component in components:
        unfunded = Fraction(
            component["replacement_cost_cents"]
            * (TOTAL_BP - component["funded_pct_bp"]),
            TOTAL_BP,
        )
        years = max(1, component["remaining_useful_life_years"])
        total += ceiling_frac(unfunded / years)
    return total


def cash_flow_annual(components, project, opening_balance_cents):
    floor_cents = CASH_FLOW_FLOOR_CENTS_PER_UNIT * project["total_unit_count"]
    schedule = []
    for component in components:
        year = max(1, component["remaining_useful_life_years"])
        if year > CASH_FLOW_HORIZON_YEARS:
            continue
        schedule.append((year, component["replacement_cost_cents"]))

    requirement = 0
    for year in range(1, CASH_FLOW_HORIZON_YEARS + 1):
        cumulative = sum(cost for maturity, cost in schedule if maturity <= year)
        year_requirement = ceiling_frac(
            Fraction(floor_cents + cumulative - opening_balance_cents, year))
        if year_requirement > requirement:
            requirement = year_requirement
    return max(requirement, 0)


def percent_funded(fully_funded_balance_cents, opening_balance_cents):
    if fully_funded_balance_cents == 0:
        return 0
    return half_up_frac(Fraction(TOTAL_BP * opening_balance_cents,
                                 fully_funded_balance_cents))


def funding_status(percent_funded_bp):
    if percent_funded_bp >= ADEQUATE_THRESHOLD_BP:
        return "ADEQUATE"
    return "UNDERFUNDED"


def compute(study, project):
    """Write every derived figure of a study from its pinned population."""
    components = verified_components(study["engineering_report_id"])
    study["fully_funded_balance_cents"] = fully_funded_balance(components)
    if study["method"] == "COMPONENT_METHOD":
        study["recommended_annual_contribution_cents"] = (
            component_method_annual(components))
    else:
        study["recommended_annual_contribution_cents"] = cash_flow_annual(
            components, project, study["opening_reserve_balance_cents"])
    study["percent_funded_bp"] = percent_funded(
        study["fully_funded_balance_cents"],
        study["opening_reserve_balance_cents"])
    study["funding_status"] = funding_status(study["percent_funded_bp"])
    return study
