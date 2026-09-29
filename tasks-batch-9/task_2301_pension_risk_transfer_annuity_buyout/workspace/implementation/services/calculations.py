"""All arithmetic from PRD section 2.5 and the calculation catalogue.

Every monetary figure is an integer count of cents; there is no floating point
anywhere in this module.  Division always goes through round_half_up unless the
PRD explicitly calls for truncation toward zero.
"""

# --------------------------------------------------------------------------
# constants (PRD 2.9)
# --------------------------------------------------------------------------

NOTICE_PERIOD_DAYS = 30
QUIET_PERIOD_DAYS = 90
REVOCATION_PERIOD_DAYS = 7
REVOCATION_MAX = 1
MAX_REVISION_ROUNDS = 2
ADDRESS_SEARCH_MAX_TIERS = 3
AUDIT_VARIANCE_TOLERANCE_CENTS = 500
DATA_CONFIDENCE_CLEAN_MIN = 80
SAFEST_AVAILABLE_MIN_RATING_POINTS = 78

ACCOUNTING_FACTOR_BP = {"RETIREE_IN_PAY": 118000, "DEFERRED_VESTED": 95500}
SETTLEMENT_FACTOR_BP = {"RETIREE_IN_PAY": 126250, "DEFERRED_VESTED": 104500}
LUMP_SUM_FACTOR_BP = {"RETIREE_IN_PAY": 121000, "DEFERRED_VESTED": 100000}

SETTLEMENT_EXPENSE_LOAD_BP = 350
SETTLEMENT_BASIS_LOAD_BP = 10700

BENEFIT_FORMULA_MULTIPLIER_BP = 150
BENEFIT_SERVICE_CAP_MONTHS = 420
BENEFIT_FORMULA_DIVISOR = 120000

ADMIN_FEE_CAP_CENTS = 500000

IN_KIND_HAIRCUT_BP = 125
IN_KIND_CUSTODY_FEE_PER_LOT_CENTS = 25000
CASH_WIRE_EXPENSE_BP = 8

RATING_POINTS = {
    "AAA": 100,
    "AA_PLUS": 92,
    "AA": 85,
    "AA_MINUS": 78,
    "A_PLUS": 70,
    "A": 60,
    "BBB": 40,
}

SELECTION_WEIGHTS = {
    "SAFETY_WEIGHTED": {"rating": 55, "capital": 25, "price": 20},
    "PRICE_WEIGHTED": {"rating": 25, "capital": 15, "price": 60},
}

STRATEGY_COHORT_MAP = {
    "LUMP_SUM_WINDOW": ("DEFERRED_VESTED",),
    "ANNUITY_BUYOUT": ("RETIREE_IN_PAY",),
    "HYBRID_WINDOW_AND_BUYOUT": ("RETIREE_IN_PAY", "DEFERRED_VESTED"),
    "LDI_GLIDEPATH": (),
}

COHORTS = ("RETIREE_IN_PAY", "DEFERRED_VESTED")


# --------------------------------------------------------------------------
# rounding
# --------------------------------------------------------------------------


def round_half_up(numerator, denominator):
    """Integer division rounding halves away from zero (PRD 2.5)."""
    if denominator == 0:
        raise ZeroDivisionError("round_half_up denominator is zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator < 0:
        return -((-numerator * 2 + denominator) // (2 * denominator))
    return (numerator * 2 + denominator) // (2 * denominator)


def apply_bp(amount, basis_points):
    """Apply a basis-point rate to an integer-cent amount."""
    return round_half_up(amount * basis_points, 10000)


# --------------------------------------------------------------------------
# participant liabilities
# --------------------------------------------------------------------------


def effective_monthly_benefit(participant):
    audited = participant.get("audited_monthly_benefit_cents")
    if audited is not None:
        return audited
    return participant.get("stated_monthly_benefit_cents") or 0


def participant_accounting_liability(participant):
    if participant.get("mortality_status") == "DECEASED_CONFIRMED":
        return 0
    monthly = effective_monthly_benefit(participant)
    factor = ACCOUNTING_FACTOR_BP[participant["cohort"]]
    return apply_bp(monthly * 12, factor)


def participant_settlement_liability(participant):
    if participant.get("mortality_status") == "DECEASED_CONFIRMED":
        return 0
    monthly = effective_monthly_benefit(participant)
    factor = SETTLEMENT_FACTOR_BP[participant["cohort"]]
    return apply_bp(monthly * 12, factor)


# --------------------------------------------------------------------------
# data confidence
# --------------------------------------------------------------------------


def data_confidence_score(participant):
    score = 100
    address_status = participant.get("address_status")
    if address_status == "UNCONFIRMED":
        score -= 40
    elif address_status == "UNLOCATABLE":
        score -= 25
    if participant.get("mortality_status") in ("UNVERIFIED", "DEATH_DISPUTED"):
        score -= 20
    if participant.get("benefit_audit_status") in (
        "NOT_AUDITED",
        "AUDIT_OPEN",
        "CORRECTION_REQUIRED",
        "REOPENED",
    ):
        score -= 15
    if score < 0:
        score = 0
    return score


def data_status_for(score):
    return "CLEAN" if score >= DATA_CONFIDENCE_CLEAN_MIN else "NEEDS_REVIEW"


# --------------------------------------------------------------------------
# benefit recomputation
# --------------------------------------------------------------------------


def benefit_recomputation(final_average_monthly_earnings_cents, credited_service_months,
                          stated_monthly_benefit_cents):
    capped_service = min(credited_service_months, BENEFIT_SERVICE_CAP_MONTHS)
    recomputed = round_half_up(
        final_average_monthly_earnings_cents * BENEFIT_FORMULA_MULTIPLIER_BP * capped_service,
        BENEFIT_FORMULA_DIVISOR,
    )
    variance = stated_monthly_benefit_cents - recomputed
    status = "PASSED" if abs(variance) <= AUDIT_VARIANCE_TOLERANCE_CENTS else "CORRECTION_REQUIRED"
    return recomputed, variance, status


# --------------------------------------------------------------------------
# lump-sum present value
# --------------------------------------------------------------------------


def admin_fee_bp_for(raw_pv_cents):
    """Fee ladder keyed on the *pre-fee* raw present value (non-monotonic)."""
    if raw_pv_cents <= 2400000:
        return 0
    if raw_pv_cents <= 12000000:
        return 75
    return 40


def lump_sum_present_value(participant):
    monthly = effective_monthly_benefit(participant)
    factor = LUMP_SUM_FACTOR_BP[participant["cohort"]]
    raw_pv = apply_bp(monthly * 12, factor)
    fee_bp = admin_fee_bp_for(raw_pv)
    uncapped_fee = apply_bp(raw_pv, fee_bp)
    fee = min(uncapped_fee, ADMIN_FEE_CAP_CENTS)
    return {
        "raw_pv_cents": raw_pv,
        "admin_fee_bp": fee_bp,
        "admin_fee_cents": fee,
        "net_lump_sum_cents": raw_pv - fee,
    }


# --------------------------------------------------------------------------
# strategy projection
# --------------------------------------------------------------------------


def strategy_projection(strategy_type, in_scope_participants):
    """Round per participant *before* summing; SETTLEMENT basis adds the load."""
    accounting_total = 0
    settlement_total = 0
    for participant in in_scope_participants:
        accounting_total += participant_accounting_liability(participant)
        base = participant_settlement_liability(participant)
        settlement_total += base + apply_bp(base, SETTLEMENT_EXPENSE_LOAD_BP)
    return {
        "projected_accounting_cost_cents": accounting_total,
        "projected_settlement_cost_cents": settlement_total,
        "projected_basis_gap_cents": settlement_total - accounting_total,
        "in_scope_participant_count": len(in_scope_participants),
    }


# --------------------------------------------------------------------------
# quote scoring
# --------------------------------------------------------------------------


def composite_score(rating_points, capital_ratio_bp, min_premium_cents, premium_cents, basis):
    weights = SELECTION_WEIGHTS[basis]
    capital_points = min(100, capital_ratio_bp // 100)
    price_points = min_premium_cents * 100 // premium_cents
    return (
        rating_points * weights["rating"]
        + capital_points * weights["capital"]
        + price_points * weights["price"]
    )


# --------------------------------------------------------------------------
# asset transfer valuation
# --------------------------------------------------------------------------


def transfer_expense(transfer_mode, gross_value_cents, lot_count):
    if transfer_mode == "IN_KIND":
        haircut = apply_bp(gross_value_cents, IN_KIND_HAIRCUT_BP)
        custody = (lot_count or 0) * IN_KIND_CUSTODY_FEE_PER_LOT_CENTS
        return haircut + custody
    return apply_bp(gross_value_cents, CASH_WIRE_EXPENSE_BP)


# --------------------------------------------------------------------------
# settlement recognition
# --------------------------------------------------------------------------


def settlement_recognition(locked_premium_cents, transfer_expense_cents, pbo_settled_cents,
                           service_cost_cents, interest_cost_cents,
                           unrecognized_actuarial_loss_cents, total_liability_cents):
    settlement_cost = locked_premium_cents + transfer_expense_cents
    threshold = service_cost_cents + interest_cost_cents
    gain_loss = settlement_cost - pbo_settled_cents
    if total_liability_cents == 0:
        pro_rata = 0
    else:
        pro_rata = round_half_up(
            unrecognized_actuarial_loss_cents * pbo_settled_cents, total_liability_cents
        )
    total_charge = gain_loss + pro_rata
    if settlement_cost > threshold:
        recognized, deferred = total_charge, 0
    else:
        recognized, deferred = 0, total_charge
    return {
        "settlement_cost_cents": settlement_cost,
        "gain_loss_cents": gain_loss,
        "pro_rata_loss_cents": pro_rata,
        "total_charge_cents": total_charge,
        "recognized_cents": recognized,
        "deferred_cents": deferred,
    }


# --------------------------------------------------------------------------
# funded status
# --------------------------------------------------------------------------


def funded_status(total_liability_cents, plan_assets_cents, participant_liability_total_cents):
    if total_liability_cents == 0:
        accounting_bp = 0
    else:
        accounting_bp = round_half_up(plan_assets_cents * 10000, total_liability_cents)
    settlement_basis = apply_bp(total_liability_cents, SETTLEMENT_BASIS_LOAD_BP)
    if settlement_basis == 0:
        settlement_bp = 0
    else:
        settlement_bp = round_half_up(plan_assets_cents * 10000, settlement_basis)
    gap = settlement_basis - plan_assets_cents
    if gap < 0:
        gap = 0
    return {
        "accounting_funded_status_bp": accounting_bp,
        "settlement_basis_liability_cents": settlement_basis,
        "settlement_funded_status_bp": settlement_bp,
        "participant_liability_total_cents": participant_liability_total_cents,
        "unfunded_settlement_gap_cents": gap,
    }
