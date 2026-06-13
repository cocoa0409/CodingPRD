"""Pure calculation rules (PRD §3 / SCAFFOLD §1.3).

All money is integer cents; all scores/points/days/months are integers.
"""
from decimal import Decimal, ROUND_HALF_UP

from timeutil import parse_iso, whole_months_between

# ---- Supervision-level ordering (PRD §2.7) -------------------------------
LEVEL_ORDER = {"ADMINISTRATIVE": 0, "MINIMUM": 1, "MEDIUM": 2, "MAXIMUM": 3}

# ---- LSI-R domains (PRD §3.2) -------------------------------------------
LSI_R_DOMAINS = [
    "criminal_history",
    "education_employment",
    "financial",
    "family_marital",
    "accommodation",
    "leisure_recreation",
    "companions",
    "alcohol_drug",
    "emotional_personal",
    "attitudes_orientation",
]

# ---- Sanction-matrix points (PRD §3.5) ----------------------------------
VIOLATION_POINTS = {"TECHNICAL": 2, "MISDEMEANOR": 4, "FELONY": 6, "ABSCOND": 12}
REVOCATION_REFERRAL_THRESHOLD = 12
EARLY_TERM_MIN_PERCENT = 50


def level_ge(a, b):
    """True when level a >= level b by the supervision-level ordering."""
    return LEVEL_ORDER[a] >= LEVEL_ORDER[b]


def level_max(a, b):
    """Return the higher of two levels by the ordering."""
    return a if LEVEL_ORDER[a] >= LEVEL_ORDER[b] else b


# =========================================================================
# LSI-R scoring (PRD §3.2)
# =========================================================================
def lsi_r_total(domain_scores):
    """Sum the ten LSI-R domain sub-scores."""
    return sum(int(domain_scores[d]) for d in LSI_R_DOMAINS)


def lsi_r_derived_level(total_score):
    """Actuarial-band lookup of derived_level from total_score (PRD §3.2)."""
    if total_score <= 13:
        return "ADMINISTRATIVE"
    elif total_score <= 23:
        return "MINIMUM"
    elif total_score <= 33:
        return "MEDIUM"
    else:
        return "MAXIMUM"


def effective_level(derived_level, override_level):
    """Effective level imposed on adoption: higher of derived and override."""
    if override_level is None:
        return derived_level
    return level_max(derived_level, override_level)


# =========================================================================
# Check-in punctuality (PRD §3.4)
# =========================================================================
def punctuality(scheduled_for_iso, window_minutes, attended_at_iso):
    """ON_TIME when attended_at <= scheduled_for + window_minutes (inclusive)."""
    scheduled = parse_iso(scheduled_for_iso)
    attended = parse_iso(attended_at_iso)
    window_close = scheduled.timestamp() + window_minutes * 60
    if attended.timestamp() <= window_close:
        return "ON_TIME"
    return "LATE"


# =========================================================================
# Sanction matrix (PRD §3.5)
# =========================================================================
def sanction_for(violation_class, post_sustain_cumulative):
    """Select (sanction_type, imposed_days) from the matrix.

    Inputs: the violation class and the supervisee's cumulative point total
    AFTER this sustain (including the points just assigned).
    """
    total = post_sustain_cumulative
    if violation_class == "ABSCOND" or total >= 12:
        return ("REVOCATION_REFERRAL", 0)
    if total >= 9:  # tier 3: 9..11
        return ("JAIL_SHOCK", (total - 9) * 2)
    if total >= 5:  # tier 2: 5..8
        if violation_class in ("MISDEMEANOR", "FELONY"):
            return ("CURFEW_IMPOSITION", 0)
        return ("INCREASED_REPORTING", 0)
    return ("VERBAL_WARNING", 0)  # tier 1: <= 4


# =========================================================================
# Compliance rate (PRD §3.10) — order pinned: ratio * 100 THEN round half-up
# =========================================================================
def compliance_rate(check_in_records):
    """Compliance rate over terminal check-ins as a percent, 1 dp, half-up."""
    terminal = [c for c in check_in_records if c["status"] in ("ATTENDED", "MISSED", "EXCUSED")]
    denom = len(terminal)
    if denom == 0:
        return 100.0
    numer = sum(
        1 for c in terminal if c["status"] == "ATTENDED" and c.get("punctuality") == "ON_TIME"
    )
    # Exact rational ratio, multiply by 100, then round half-up to 1 dp.
    product = (Decimal(numer) / Decimal(denom)) * Decimal(100)
    rounded = product.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(rounded)


# =========================================================================
# Fee accrual / obligation outstanding (PRD §3.6)
# =========================================================================
def accrued_to(obligation, as_of_dt):
    """Accrual earned by a recurring FEE obligation up to as_of_dt (cents)."""
    if obligation["obligation_type"] != "FEE" or not obligation.get("recurring"):
        return 0
    created = parse_iso(obligation["created_at"])
    months = whole_months_between(created, as_of_dt)
    return months * int(obligation.get("monthly_accrual_cents", 0))


def outstanding_now(obligation, now_dt):
    """Current outstanding amount of an obligation measured to now (>= 0).

    principal + accrual-to-now - paid, floored at 0.
    """
    out = obligation["principal_cents"] + accrued_to(obligation, now_dt) - obligation["paid_cents"]
    return max(out, 0)


def projected_outstanding(obligation, as_of_dt):
    """Forward-looking projected outstanding through as_of (>= 0).

    principal - paid + projected future accrual (whole months created_at->as_of).
    """
    out = obligation["principal_cents"] - obligation["paid_cents"]
    out += accrued_to(obligation, as_of_dt)
    return max(out, 0)


# =========================================================================
# Early-termination eligibility (PRD §3.9)
# =========================================================================
def early_termination_eligibility(supervisee, requested_on_dt, open_violation_count):
    """Compute the frozen eligibility object for a petition."""
    start = parse_iso(supervisee["supervision_start_date"])
    months_served = whole_months_between(start, requested_on_dt)
    term = supervisee["ordered_term_months"]
    percent_served = (months_served * 100) // term  # integer floor pct
    balances_clear = supervisee["restitution_balance_cents"] == 0
    no_open_violations = open_violation_count == 0
    eligible = (
        percent_served >= EARLY_TERM_MIN_PERCENT
        and balances_clear
        and no_open_violations
    )
    return months_served, {
        "percent_served": percent_served,
        "balances_clear": balances_clear,
        "no_open_violations": no_open_violations,
        "eligible": eligible,
    }
