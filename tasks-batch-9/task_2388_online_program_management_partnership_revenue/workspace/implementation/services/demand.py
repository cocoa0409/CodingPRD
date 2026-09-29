"""calculations.program_demand_score (PRD 3.2)."""

import constants as C
from services.money import D, as_float, rhu


def _capped(numerator, cap):
    value = D(numerator) / D(cap)
    return value if value < 1 else D(1)


def demand_score(program, variant):
    if variant == "CONFIRMED":
        yielded = rhu(D(program["prior_year_inquiry_volume"]) * D(C.CONFIRMED_INQUIRY_YIELD), 0)
        projection = min(D(program["projected_annual_enrollments"]), yielded)
    else:
        projection = D(program["projected_annual_enrollments"])

    enrollment_component = _capped(projection, C.PROJECTION_CAP) * D(C.W_ENROLLMENT)

    competition = D(1) - D(program["competitor_program_count"]) / D(C.COMPETITOR_CAP)
    if competition < 0:
        competition = D(0)
    competition_component = competition * D(C.W_COMPETITION)

    wage_component = _capped(program["regional_wage_premium_pct"], C.WAGE_PREMIUM_CAP) * D(C.W_WAGE)
    employer_component = _capped(program["employer_partner_count"], C.EMPLOYER_CAP) * D(C.W_EMPLOYER)

    raw = enrollment_component + competition_component + wage_component + employer_component
    factor = D(C.MODALITY_FACTOR[program["delivery_modality"]])
    return rhu(raw * factor, 2)


def screening(program):
    return as_float(demand_score(program, "SCREENING"))


def confirmed(program):
    return as_float(demand_score(program, "CONFIRMED"))
