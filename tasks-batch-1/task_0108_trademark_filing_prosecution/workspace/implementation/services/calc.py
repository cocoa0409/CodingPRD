"""Calculation rules (SCAFFOLD §1.3, PRD §2.7/§2.8/§3). All fees are whole cents.

All monetary inputs are whole-cent integer constants, so fee arithmetic is exact
and never requires rounding.
"""

from services.dateutil import add_days, add_years, days_late  # noqa: F401 (re-export)


# ---- Application filing fee (calc application_filing_fee) -------------------
TEAS_PLUS_PER_CLASS_CENTS = 25000
TEAS_STANDARD_PER_CLASS_CENTS = 35000
INTENT_SURCHARGE_PER_CLASS_CENTS = 10000


def application_filing_fee(filing_tier: str, filing_basis: str, class_count: int) -> int:
    per_class = (
        TEAS_PLUS_PER_CLASS_CENTS
        if filing_tier == "TEAS_PLUS"
        else TEAS_STANDARD_PER_CLASS_CENTS
    )
    # INTENT surcharge is added to the per-class amount BEFORE multiplying.
    if filing_basis == "INTENT":
        per_class += INTENT_SURCHARGE_PER_CLASS_CENTS
    return per_class * class_count


# ---- Maintenance fee (calc maintenance_fee) --------------------------------
SECTION_8_PER_CLASS_CENTS = 22500
SECTION_9_PER_CLASS_CENTS = 30000
GRACE_SURCHARGE_PER_CLASS_CENTS = 10000


def maintenance_fee(filing_type: str, class_count: int, in_grace_period: bool) -> int:
    base = SECTION_8_PER_CLASS_CENTS * class_count
    if filing_type == "SECTION_8_AND_9":
        base += SECTION_9_PER_CLASS_CENTS * class_count
    surcharge = GRACE_SURCHARGE_PER_CLASS_CENTS * class_count if in_grace_period else 0
    return base + surcharge


# ---- Madrid fee (calc madrid_fee) ------------------------------------------
MADRID_BASE_CENTS = 65300
MADRID_PER_COUNTRY_CENTS = 10000


def madrid_fee(designated_countries: list) -> int:
    return MADRID_BASE_CENTS + MADRID_PER_COUNTRY_CENTS * len(designated_countries)


# ---- Docket deadline windows (calc docket_deadline_windows) ----------------
RESPONSE_PERIOD_DAYS = 90
NONFINAL_GRACE_DAYS = 30
FINAL_GRACE_DAYS = 0
OPPOSITION_WINDOW_DAYS = 30
ANSWER_PERIOD_DAYS = 40
SOU_INITIAL_DAYS = 180
SOU_MAX_DAYS = 1260
DEPENDENCY_YEARS = 5


# ---- Maintenance windows (calc maintenance_window) -------------------------
FIRST_WINDOW_YEARS = 6
RENEWAL_PERIOD_YEARS = 10
WINDOW_LEAD_YEARS = 1
GRACE_WINDOW_DAYS = 180


def maintenance_due_at(registered_at, cycle: int):
    """next_maintenance_due_at anchored to registered_at, given the post-acceptance
    maintenance_cycle. cycle 0 -> +6y (first §8); each subsequent cycle -> +(6 + 10*cycle)y."""
    if cycle == 0:
        return add_years(registered_at, FIRST_WINDOW_YEARS)
    return add_years(registered_at, FIRST_WINDOW_YEARS + RENEWAL_PERIOD_YEARS * cycle)


def maintenance_window_open_at(due_at):
    """Window opens one year before it closes."""
    return add_years(due_at, -WINDOW_LEAD_YEARS)


# ---- Prosecution risk score (calc prosecution_risk_score) ------------------
W_OPEN_OA = 15
W_LATE_RESP = 10
W_DEFAULT = 40
W_GRACE_REG = 20
SCORE_CEILING = 100
