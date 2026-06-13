"""Calculation rules — SCAFFOLD §1.3 / PRD §3. All money uses Decimal + ROUND_HALF_UP,
sum-then-round (round once on the final sum). Risk score is integer clamped [0,100].
"""
from decimal import Decimal, ROUND_HALF_UP

# --- constants ---
BASE_FEE = {"LOW": Decimal("100.00"), "MEDIUM": Decimal("250.00"), "HIGH": Decimal("600.00")}
PER_EMPLOYEE_FEE = Decimal("5.00")
ZONING_VARIANCE_SURCHARGE = Decimal("150.00")
PER_INSPECTION_FEE = Decimal("75.00")

# delinquency
GRACE_PERIOD_DAYS = 30
TIER_A_MAX_DAYS = 60
TIER_B_MAX_DAYS = 90
REVOCATION_THRESHOLD_DAYS = 90
RENEWAL_WINDOW_DAYS = 60
RENEWAL_FEE = {"LOW": Decimal("200.00"), "MEDIUM": Decimal("480.00"), "HIGH": Decimal("900.00")}

# transfer
FLAT_TRANSFER_FEE = Decimal("300.00")
RISK_TRANSFER_SURCHARGE = Decimal("200.00")

# risk score weights
VIOLATION_WEIGHT = 5
VIOLATION_CAP = 30
DELINQUENCY_WEIGHT = 20
PRIOR_REVOCATION_WEIGHT = 10


def _money(d):
    """Round a Decimal to 2 places using round-half-up and return a float for JSON."""
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def application_fee_estimate(risk_tier, declared_employee_count, variance):
    """base + per-employee*declared + (variance surcharge if variance flag), round once."""
    base = BASE_FEE[risk_tier]
    surcharge = PER_EMPLOYEE_FEE * Decimal(int(declared_employee_count))
    var = ZONING_VARIANCE_SURCHARGE if variance else Decimal("0.00")
    return _money(base + surcharge + var)


def issuance_fee_final(risk_tier, verified_employee_count, variance, passed_inspection_count):
    """base + per-employee*verified + variance + per-inspection*passed_count, round once."""
    base = BASE_FEE[risk_tier]
    surcharge = PER_EMPLOYEE_FEE * Decimal(int(verified_employee_count))
    var = ZONING_VARIANCE_SURCHARGE if variance else Decimal("0.00")
    inspection_fees = PER_INSPECTION_FEE * Decimal(int(passed_inspection_count))
    return _money(base + surcharge + var + inspection_fees)


def delinquency_penalty(risk_tier, days_overdue):
    """Single-tier penalty (tiers do not stack). Returns float rounded to 2 places."""
    if days_overdue <= GRACE_PERIOD_DAYS:
        pct = Decimal("0.00")
    elif days_overdue <= TIER_A_MAX_DAYS:
        pct = Decimal("0.10")
    elif days_overdue <= TIER_B_MAX_DAYS:
        pct = Decimal("0.25")
    else:
        pct = Decimal("0.50")
    penalty = RENEWAL_FEE[risk_tier] * pct
    return _money(penalty)


def transfer_fee(risk_tier):
    surcharge = RISK_TRANSFER_SURCHARGE if risk_tier == "HIGH" else Decimal("0.00")
    return _money(FLAT_TRANSFER_FEE + surcharge)


def compliance_risk_score(activity_base_risk, open_violation_count, standing, prior_revocation_flag):
    """Integer weighted score clamped to [0,100]. open_violation_count varies by variant
    (PROVISIONAL passes 0; AUDITED passes the summed failed_item_count)."""
    s = int(activity_base_risk)
    s = s + min(VIOLATION_WEIGHT * int(open_violation_count), VIOLATION_CAP)
    s = s + (DELINQUENCY_WEIGHT if standing == "DELINQUENT" else 0)
    s = s + (PRIOR_REVOCATION_WEIGHT if prior_revocation_flag else 0)
    return max(0, min(100, s))
