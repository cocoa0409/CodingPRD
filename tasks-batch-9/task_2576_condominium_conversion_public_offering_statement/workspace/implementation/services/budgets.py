"""The first-year budget chain and the per-unit assessment allocation (3.5).

The evaluation order is pinned and runs exactly once: the management fee tier
is keyed on `base_expense_cents` and on nothing else, and there is no
re-tiering pass even when the disclosed total crosses a tier ceiling.
"""

from fractions import Fraction

import store
from rounding import half_up_frac

TOTAL_BP = 10000
FEE_TIER_MID_FLOOR_CENTS = 12000000
FEE_TIER_TOP_FLOOR_CENTS = 30000000


def management_fee_bp(base_expense_cents):
    if base_expense_cents < FEE_TIER_MID_FLOOR_CENTS:
        return 800
    if base_expense_cents < FEE_TIER_TOP_FLOOR_CENTS:
        return 650
    return 500


def allocate_assessments(project, total_to_distribute):
    """Round per unit first, then sum, then hand the whole residual to exactly
    one unit.  Monthly amounts round again, independently, from the already
    rounded annual amount."""
    units = store.project_units(project["id"])
    included = [u for u in units if u["declaration_status"] == "INCLUDED"]

    for unit in units:
        if unit["declaration_status"] == "WITHDRAWN":
            if (unit["unit_annual_assessment_cents"] != 0
                    or unit["unit_monthly_assessment_cents"] != 0):
                unit["unit_annual_assessment_cents"] = 0
                unit["unit_monthly_assessment_cents"] = 0
                store.touch(unit)

    if not included:
        return 0

    amounts = {}
    for unit in included:
        raw = Fraction(total_to_distribute * unit["percentage_interest_bp"],
                       TOTAL_BP)
        amounts[unit["id"]] = half_up_frac(raw)

    remainder = total_to_distribute - sum(amounts.values())
    if remainder != 0:
        residual_unit = sorted(
            included,
            key=lambda u: (-u["percentage_interest_bp"], store.sort_key(u)),
        )[0]
        amounts[residual_unit["id"]] += remainder

    for unit in included:
        annual = amounts[unit["id"]]
        monthly = half_up_frac(Fraction(annual, 12))
        if (unit["unit_annual_assessment_cents"] != annual
                or unit["unit_monthly_assessment_cents"] != monthly):
            unit["unit_annual_assessment_cents"] = annual
            unit["unit_monthly_assessment_cents"] = monthly
            store.touch(unit)

    return sum(amounts[u["id"]] for u in included)


def derive(budget, project, study):
    """Steps one through nine of the pinned budget evaluation order."""
    budget["reserve_contribution_cents"] = (
        study["recommended_annual_contribution_cents"])
    budget["base_expense_cents"] = (budget["annual_operating_expense_cents"]
                                    + budget["reserve_contribution_cents"])
    budget["management_fee_bp"] = management_fee_bp(budget["base_expense_cents"])
    budget["management_fee_cents"] = half_up_frac(
        Fraction(budget["base_expense_cents"] * budget["management_fee_bp"],
                 TOTAL_BP))
    budget["total_annual_expense_cents"] = (budget["base_expense_cents"]
                                            + budget["management_fee_cents"])
    budget["assessment_income_cents"] = allocate_assessments(
        project, budget["total_annual_expense_cents"])
    deficit = (budget["total_annual_expense_cents"]
               - budget["assessment_income_cents"])
    budget["developer_deficit_funding_cents"] = max(0, deficit)
    budget["developer_subsidy_flag"] = (
        budget["developer_deficit_funding_cents"] > 0)
    return budget


def reallocate_for_project(project):
    """Re-run the allocation after a unit withdrawal or reinstatement, which
    change the INCLUDED set and therefore every unit's effective interest."""
    budgets = [b for b in store.project_budgets(project["id"])
               if b["status"] in ("DRAFT", "ADOPTED")]
    if not budgets:
        return None
    budget = budgets[-1]
    income = allocate_assessments(project, budget["total_annual_expense_cents"])
    if budget["assessment_income_cents"] != income:
        budget["assessment_income_cents"] = income
        deficit = budget["total_annual_expense_cents"] - income
        budget["developer_deficit_funding_cents"] = max(0, deficit)
        budget["developer_subsidy_flag"] = (
            budget["developer_deficit_funding_cents"] > 0)
        store.touch(budget)
    return budget
