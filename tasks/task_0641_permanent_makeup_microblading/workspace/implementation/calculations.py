"""Calculation rules (scaffold 1.3, PRD 2.5/3.4/3.8/3.2).

All money is integer cents. Rounding uses round-half-up applied at each
specified step. Risk scores and kit counts are plain integers (no rounding).
"""
from decimal import Decimal, ROUND_HALF_UP

# session_price constants (scaffold calculations.session_price)
BASE_RATE_CENTS = {"BROWS": 60000, "EYELINER": 50000, "LIP_BLUSH": 70000}
COLOR_SURCHARGE_2 = 5000
COLOR_SURCHARGE_3PLUS = 12000
CORRECTIVE_UPLIFT_PCT = Decimal("0.25")
ANNUAL_REFRESH_PCT = Decimal("0.50")

# deposit_amount
DEPOSIT_PCT = Decimal("0.20")

# package_price
TOUCHUP_PCT = Decimal("0.40")
BUNDLE_DISCOUNT_PCT = Decimal("0.15")

# client_risk_score
W_MEDICAL = 8
W_ADVERSE = 12
W_SENS = 5
HIGH_RISK_THRESHOLD = 30

# strikes / blocking
NO_SHOW_BLOCK_THRESHOLD = 3


def round_half_up(value):
    """Round a Decimal (or number) to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def session_price(procedure_type, pigment_count, is_corrective, appointment_kind):
    """scaffold calculations.session_price.

    Pinned evaluation order: base, then surcharge, then uplift, then sum.
    ANNUAL_REFRESH override: round_half_up(base * 0.50).
    REDO override: 0.
    """
    base = BASE_RATE_CENTS[procedure_type]

    if appointment_kind == "REDO":
        return 0
    if appointment_kind == "ANNUAL_REFRESH":
        return round_half_up(Decimal(base) * ANNUAL_REFRESH_PCT)

    # standard (INITIAL / TOUCH_UP)
    if pigment_count <= 1:
        color_surcharge = 0
    elif pigment_count == 2:
        color_surcharge = COLOR_SURCHARGE_2
    else:  # >= 3
        color_surcharge = COLOR_SURCHARGE_3PLUS

    corrective_uplift = round_half_up(Decimal(base) * CORRECTIVE_UPLIFT_PCT) if is_corrective else 0

    return base + color_surcharge + corrective_uplift


def deposit_amount(session_price_cents, appointment_kind=None):
    """scaffold calculations.deposit_amount: 20% round_half_up; REDO -> 0."""
    if appointment_kind == "REDO":
        return 0
    return round_half_up(Decimal(session_price_cents) * DEPOSIT_PCT)


def package_price(source_session_price_cents, included_sessions, pricing_mode):
    """scaffold calculations.package_price — opposite rounding orders.

    per_touchup_gross = sp * 0.40
    PAYG:   line = round_half_up(per_touchup_gross); price = line * n  (round-per-line-then-sum)
    BUNDLE: gross = per_touchup_gross * n; price = round_half_up(gross * (1 - 0.15))  (sum-then-round)
    """
    per_touchup_gross = Decimal(source_session_price_cents) * TOUCHUP_PCT
    n = included_sessions
    if pricing_mode == "PAYG":
        line = round_half_up(per_touchup_gross)
        return line * n
    else:  # BUNDLE
        gross = per_touchup_gross * n
        return round_half_up(gross * (Decimal(1) - BUNDLE_DISCOUNT_PCT))


def client_risk_score(medical_flag_count, prior_adverse_reactions,
                      skin_sensitivity_self, skin_sensitivity_observed):
    """scaffold calculations.client_risk_score (weighted, integer, no rounding).

    sensitivity = observed if observed is not None else self.
    """
    if skin_sensitivity_observed is not None:
        sensitivity = skin_sensitivity_observed
    else:
        sensitivity = skin_sensitivity_self
    score = (W_MEDICAL * medical_flag_count) + (W_ADVERSE * prior_adverse_reactions) + (W_SENS * sensitivity)
    return score


def risk_band(risk_score):
    return "HIGH_RISK" if risk_score >= HIGH_RISK_THRESHOLD else "STANDARD"
