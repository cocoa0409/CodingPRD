"""delivery_grade_assignment: tier ladder with inclusive boundaries.

Foreign matter above 6.0 rejects outright; otherwise test A, then B, then C;
scores compared exactly, weighted_barrels round2(net * multiplier).
"""
from decimal import Decimal

from validation import round2, to_decimal

GRADE_A_MIN_SCORE = Decimal("8.0")
GRADE_B_MIN_SCORE = Decimal("7.0")
GRADE_C_MIN_SCORE = Decimal("6.0")
GRADE_A_MAX_FM = Decimal("2.0")
GRADE_B_MAX_FM = Decimal("4.0")
GRADE_C_MAX_FM = Decimal("6.0")
FM_REJECT_ABOVE = Decimal("6.0")

PREMIUM = {
    "A": Decimal("1.10"),
    "B": Decimal("1.00"),
    "C": Decimal("0.90"),
    "REJECT": Decimal("0"),
}


def assign_grade(color_score, firmness_score, foreign_matter_pct, net_barrels):
    color = to_decimal(color_score)
    firmness = to_decimal(firmness_score)
    fm = to_decimal(foreign_matter_pct)
    net = to_decimal(net_barrels)

    if fm > FM_REJECT_ABOVE:
        grade = "REJECT"
    elif color >= GRADE_A_MIN_SCORE and firmness >= GRADE_A_MIN_SCORE and fm <= GRADE_A_MAX_FM:
        grade = "A"
    elif color >= GRADE_B_MIN_SCORE and firmness >= GRADE_B_MIN_SCORE and fm <= GRADE_B_MAX_FM:
        grade = "B"
    elif color >= GRADE_C_MIN_SCORE and firmness >= GRADE_C_MIN_SCORE and fm <= GRADE_C_MAX_FM:
        grade = "C"
    else:
        grade = "REJECT"

    multiplier = PREMIUM[grade]
    weighted = round2(net * multiplier)
    return grade, multiplier, weighted
