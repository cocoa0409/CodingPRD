"""Business calculations (SCAFFOLD §1.3 / PRD Section 3).

All money is Decimal, rounded HALF_UP to 2 decimal places at the points the
rules specify. Never float for money.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ---- global constants ----
FIRST_OFFENDER_MAX_PRIOR = 1
ARRAIGNMENT_WINDOW_DAYS = 30

# fine assessment
COURT_FEE = Decimal("50.00")
SURCHARGE_TIER_1_MAX = Decimal("100")
SURCHARGE_TIER_1_RATE = Decimal("0.20")
SURCHARGE_TIER_2_MAX = Decimal("500")
SURCHARGE_TIER_2_RATE = Decimal("0.30")
SURCHARGE_TIER_3_RATE = Decimal("0.35")
SURCHARGE_CAP = Decimal("150")
SEVERITY_MULTIPLIER = {"INFRACTION": Decimal("1.0"), "MISDEMEANOR": Decimal("1.5")}

# installment
INSTALLMENT_COUNT_MIN = 2
INSTALLMENT_COUNT_MAX = 12
INSTALLMENT_MIN_BALANCE = Decimal("100.00")
INSTALLMENT_INTERVAL_DAYS = 30

# compliance weights
WEIGHT_SERVICE = Decimal("0.5")
WEIGHT_CLASS = Decimal("0.3")
WEIGHT_FINANCIAL = Decimal("0.2")

# amnesty / warrant
LATE_PENALTY = Decimal("75.00")

CENT = Decimal("0.01")


def q2(x):
    """Quantize to 2 dp, round half up."""
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def to_decimal(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def surcharge_for(subtotal):
    """Tiered surcharge on the whole subtotal, rounded then capped."""
    if subtotal <= SURCHARGE_TIER_1_MAX:
        rate = SURCHARGE_TIER_1_RATE
    elif subtotal <= SURCHARGE_TIER_2_MAX:
        rate = SURCHARGE_TIER_2_RATE
    else:
        rate = SURCHARGE_TIER_3_RATE
    raw = q2(rate * subtotal)            # round first
    return min(raw, SURCHARGE_CAP)       # then cap


def fine_components(charges, variant, program_fee=Decimal("0")):
    """Return (fines, court_fee, surcharge, program_fee) as Decimals.

    provisional: fine per charge = base_fine_amount (no severity multiplier), no program_fee.
    final:       fine per charge = base_fine_amount * SEVERITY_MULTIPLIER[severity] + program_fee.
    """
    subtotal = Decimal("0")
    for c in charges:
        base = to_decimal(c["base_fine_amount"])
        if variant == "final":
            base = base * SEVERITY_MULTIPLIER.get(c["severity"], Decimal("1.0"))
        subtotal += base
    fines = q2(subtotal)
    surcharge = surcharge_for(subtotal)
    court_fee = COURT_FEE
    pf = q2(program_fee) if variant == "final" else Decimal("0.00")
    return fines, court_fee, surcharge, pf


def installment_schedule(balance, num_installments):
    """Return (installment_amount, final_installment_amount) as Decimals.

    Floor each installment to the cent; final installment absorbs remainder.
    """
    total_cents = int((to_decimal(balance) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    n = num_installments
    base_cents = total_cents // n            # floor
    remainder_cents = total_cents - base_cents * n
    installment_amount = (Decimal(base_cents) / 100).quantize(CENT)
    final_amount = (Decimal(base_cents + remainder_cents) / 100).quantize(CENT)
    return installment_amount, final_amount


def reinstatement_adjustment(assessed, penalty_waiver_pct, reinstatement_fee):
    """assessed - round(LATE_PENALTY * pct, 2) + reinstatement_fee -> (waived, new_assessed)."""
    waived = q2(LATE_PENALTY * to_decimal(penalty_waiver_pct))
    new_assessed = q2(to_decimal(assessed) - waived + to_decimal(reinstatement_fee))
    return waived, new_assessed


def compliance_pct(agreement, assignments, account, variant):
    """Weighted compliance percentage (0..100) as a Decimal rounded to 2 dp."""
    mandated = to_decimal(agreement["mandated_service_hours"])
    req_sessions = int(agreement["required_class_sessions"])

    if variant == "provisional":
        svc_statuses = {"IN_PROGRESS", "COMPLETED"}
        cls_statuses = {"IN_PROGRESS", "COMPLETED"}
    else:
        svc_statuses = {"COMPLETED"}
        cls_statuses = {"COMPLETED"}

    svc_num = sum((to_decimal(a["completed_hours"]) for a in assignments
                   if a["status"] in svc_statuses), Decimal("0"))
    cls_num = sum(1 for a in assignments
                  if a["assignment_type"] == "EDUCATION_CLASS" and a["status"] in cls_statuses)

    svc = min(Decimal("1.0"), svc_num / mandated) if mandated > 0 else Decimal("1.0")
    cls = min(Decimal("1.0"), Decimal(cls_num) / Decimal(req_sessions)) if req_sessions > 0 else Decimal("1.0")

    assessed = to_decimal(account["assessed_amount"]) if account else Decimal("0")
    collected = to_decimal(account["collected_amount"]) if account else Decimal("0")
    fin = min(Decimal("1.0"), collected / assessed) if assessed > 0 else Decimal("1.0")

    pct = Decimal("100") * (WEIGHT_SERVICE * svc + WEIGHT_CLASS * cls + WEIGHT_FINANCIAL * fin)
    return q2(pct)
