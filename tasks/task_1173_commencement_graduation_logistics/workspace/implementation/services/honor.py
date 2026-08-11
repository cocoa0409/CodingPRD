"""honor_gpa_designation calculation (scaffold §1.3)."""
from decimal import Decimal, ROUND_HALF_UP

HONOR_RANK = {"NONE": 0, "CUM_LAUDE": 1, "MAGNA_CUM_LAUDE": 2, "SUMMA_CUM_LAUDE": 3}

SUMMA_THRESHOLD = Decimal("3.900")
MAGNA_THRESHOLD = Decimal("3.700")
CUM_THRESHOLD = Decimal("3.500")

ELIGIBLE_FAMILY = {"ELIGIBLE", "ELIGIBLE_ON_APPEAL", "CONFIRMED"}

HONORS_TEXT = {
    "NONE": "",
    "CUM_LAUDE": "cum laude",
    "MAGNA_CUM_LAUDE": "magna cum laude",
    "SUMMA_CUM_LAUDE": "summa cum laude",
}


def _gpa(qp, cr):
    """gpa = cr == 0 ? 0.000 : round_half_up(qp / cr, 3)"""
    qp_d = Decimal(str(qp))
    cr_d = Decimal(str(cr))
    if cr_d == 0:
        return Decimal("0.000")
    return (qp_d / cr_d).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _tier(g):
    if g >= SUMMA_THRESHOLD:
        return "SUMMA_CUM_LAUDE"
    if g >= MAGNA_THRESHOLD:
        return "MAGNA_CUM_LAUDE"
    if g >= CUM_THRESHOLD:
        return "CUM_LAUDE"
    return "NONE"


def honor_tier_combined(grad):
    g = _gpa(
        grad["institutional_quality_points"] + grad["transfer_quality_points"],
        grad["institutional_gpa_credits"] + grad["transfer_gpa_credits"],
    )
    return _tier(g)


def honor_tier_institutional(grad):
    g = _gpa(grad["institutional_quality_points"], grad["institutional_gpa_credits"])
    return _tier(g)


def recompute_honor(grad, variant):
    """Recompute honor tier for an eligible-family graduate. Others keep NONE."""
    if grad["status"] not in ELIGIBLE_FAMILY:
        return
    if variant == "COMBINED":
        grad["honor_tier"] = honor_tier_combined(grad)
        grad["honor_basis"] = "COMBINED"
    else:  # INSTITUTIONAL
        grad["honor_tier"] = honor_tier_institutional(grad)
        grad["honor_basis"] = "INSTITUTIONAL"
