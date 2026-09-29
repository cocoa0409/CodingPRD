"""Calculation unit_salvage_value (PRD 3.9)."""

import constants as C
from clock import clock
from services.numbers import D, cents


def salvage_value(unit, valuation_basis):
    age_years = clock.year() - unit["in_service_year"]
    straight_line_factor = max(
        C.SALVAGE_FLOOR_PCT, D(1) - D(age_years) / D(C.USEFUL_LIFE_YEARS)
    )
    acquisition = D(unit["acquisition_cost_cents"])
    straight_line_cents = cents(acquisition * straight_line_factor)
    floor_cents = cents(acquisition * C.SALVAGE_FLOOR_PCT)

    if valuation_basis == "STRAIGHT_LINE":
        return straight_line_cents

    multiplier = C.CONDITION_MULTIPLIER[unit["condition_grade"]]
    return max(floor_cents, cents(D(straight_line_cents) * multiplier))


def sale_floor(salvage_value_cents):
    return cents(C.MIN_SALE_RECOVERY_PCT * D(salvage_value_cents))
