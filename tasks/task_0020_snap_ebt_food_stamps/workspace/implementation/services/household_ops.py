"""Household-level operations: recompute totals, bump version/updated_at."""

from db import db
from services.calculations import compute_gross_size, net_monthly_income


def bump_household(household: dict):
    """Increment Household.version and refresh updated_at."""
    household["version"] = int(household.get("version", 1)) + 1
    household["updated_at"] = db.current_utc_iso()


def recompute_household_totals(household: dict):
    """Recompute gross/size/net (BENEFIT_CALC) and write to the household dict.

    Does NOT bump version or updated_at — caller decides.
    """
    gross, size = compute_gross_size(household["id"])
    household["gross_income_cents"] = gross
    household["size"] = size
    household["net_income_cents"] = net_monthly_income(household, variant="BENEFIT_CALC")
