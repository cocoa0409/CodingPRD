"""The nine calculations of the specification (PRD 2.5, 3.2, 3.3, 3.7)."""

from decimal import Decimal

from util import bp, d4, dec, rhu_cents

THOUSAND = Decimal(1000)


# --------------------------------------------------------------------------- #
# Growth projection (PRD 3.2)
# --------------------------------------------------------------------------- #


def growth_demand_units(component):
    residential = dec(component["projected_new_dwelling_units"]) * dec(
        component["demand_units_per_dwelling"])
    nonresidential = (dec(component["projected_new_nonres_sqft"]) / THOUSAND) * dec(
        component["demand_units_per_1000_nonres_sqft"])
    return d4(residential + nonresidential)


# --------------------------------------------------------------------------- #
# Cost allocation (PRD 3.2)
# --------------------------------------------------------------------------- #


def plan_based_cost_per_unit(component):
    gross_growth = rhu_cents(
        dec(component["planned_facility_cost_cents"]) * bp(component["planned_growth_share_bp"]))
    net_growth = gross_growth - component["planned_other_funding_cents"]
    growth = dec(component["growth_demand_units"])
    capacity = dec(component["planned_capacity_demand_units"])
    denominator = growth if growth < capacity else capacity
    if denominator <= 0:
        return None
    return rhu_cents(dec(net_growth) / denominator)


def standard_based_cost_per_unit(category, program):
    existing = dec(category["existing_los_per_demand_unit"])
    planned = dec(category["planned_los_per_demand_unit"])
    if program["los_policy"] == "PLANNED_STANDARD_ALLOWED":
        applicable = planned if planned > existing else existing
    else:
        applicable = existing
    return rhu_cents(dec(category["unit_cost_cents"]) * applicable)


def nexus_ratio(component):
    growth = dec(component["growth_demand_units"])
    if growth <= 0:
        return None
    return d4(dec(component["planned_capacity_demand_units"]) / growth)


def allocate(component, study, category, program):
    """Writes both methodology readings, the adopted cost and the nexus ratio."""
    plan_based = plan_based_cost_per_unit(component)
    standard_based = standard_based_cost_per_unit(category, program)
    selected = plan_based if study["methodology"] == "PLAN_BASED" else standard_based
    if selected is None:
        adopted = None
    else:
        adopted = selected - component["existing_tax_credit_per_unit_cents"]
        if adopted < 0:
            adopted = 0
    component["plan_based_cost_per_unit_cents"] = plan_based
    component["standard_based_cost_per_unit_cents"] = standard_based
    component["adopted_cost_per_unit_cents"] = adopted
    component["nexus_ratio"] = nexus_ratio(component)


# --------------------------------------------------------------------------- #
# Fee schedule line (PRD 3.3)
# --------------------------------------------------------------------------- #


def fee_per_unit_cents(component, conversion_factor):
    adopted = component.get("adopted_cost_per_unit_cents")
    if adopted is None:
        return None
    return rhu_cents(dec(adopted) * dec(conversion_factor))


# --------------------------------------------------------------------------- #
# Credit claim valuation (PRD 3.7)
# --------------------------------------------------------------------------- #


def credit_claim_value(valuation_method, improvement_cents, annual_tax_cents,
                       contribution_years, discount_rate_bp):
    improvement = dec(improvement_cents or 0)
    annual_tax = dec(annual_tax_cents or 0)
    years = int(contribution_years or 0)
    if valuation_method == "NOMINAL":
        return rhu_cents(improvement + annual_tax * years)
    rate = bp(discount_rate_bp)
    one_plus = Decimal(1) + rate
    annuity = Decimal(0)
    for period in range(1, years + 1):
        annuity += Decimal(1) / (one_plus ** period)
    present_value = annual_tax * annuity
    if years > 0:
        present_value += improvement / (one_plus ** years)
    else:
        present_value += improvement
    return rhu_cents(present_value)
