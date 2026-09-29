"""The thirteen calculations of PRD section 3 / SCAFFOLD calculations."""
from decimal import Decimal

from datetimes import add_business_days, day_count_30_360, parse_dt
from money import D, ZERO, dmax, dmin, q2, q4, q6

# ---------------------------------------------------------------- constants
MONETARY_DELINQUENCY_DAYS_THRESHOLD = 60
APPRAISAL_CREDIT_PCT = Decimal("0.90")
DAY_COUNT_BASIS = Decimal("360")
ABSOLUTE_MARGIN_FLOOR_USD = Decimal("50000")
RELATIVE_MARGIN_PCT = Decimal("0.005")
DEPOSIT_FLOOR_USD = {
    "MODIFICATION": Decimal("25000"),
    "ASSUMPTION": Decimal("15000"),
    "LEASE_APPROVAL": Decimal("5000"),
}
CONTROL_TERMINATION_PCT = Decimal("0.25")
MONTHS_PER_YEAR = Decimal("12")
MONTHLY_FEE_FLOOR_USD = Decimal("500.00")
FEE_CAP_USD = Decimal("1000000.00")
ALTERNATIVE_TYPE_ORDINAL = {
    "MODIFICATION": 1,
    "DEED_IN_LIEU": 2,
    "NOTE_SALE": 3,
    "FORECLOSURE": 4,
}


# ------------------------------------------------ 1. transfer_event_qualification
def transfer_event_qualification(event_code, days_delinquent_at_event,
                                 imminent_default_certified, occurred_on_dt,
                                 loan_maturity_dt):
    if event_code == "MONETARY_DEFAULT_60D":
        return int(days_delinquent_at_event or 0) >= MONETARY_DELINQUENCY_DAYS_THRESHOLD
    if event_code == "IMMINENT_DEFAULT":
        return bool(imminent_default_certified)
    if event_code == "MATURITY_DEFAULT":
        if occurred_on_dt is None or loan_maturity_dt is None:
            return False
        return occurred_on_dt >= loan_maturity_dt
    if event_code in ("BANKRUPTCY", "RECEIVERSHIP"):
        return True
    return False


# ------------------------------------------------ 2. advance_interest_accrual
def advance_interest(amount_usd, reimbursed_principal_usd, advanced_on_dt,
                     clock_dt, advance_interest_rate_pct):
    day_count = day_count_30_360(advanced_on_dt, clock_dt)
    if day_count <= 0:
        return ZERO, day_count
    unreimbursed = D(amount_usd) - D(reimbursed_principal_usd)
    accrued = q2(unreimbursed * (D(advance_interest_rate_pct) / Decimal(100))
                 * Decimal(day_count) / DAY_COUNT_BASIS)
    return accrued, day_count


# ------------------------------------------------ 3. appraisal_reduction_amount
def appraisal_reduction_amount(current_principal_balance_usd, accrued_unpaid_interest_usd,
                               advance_principal, advance_interest_total,
                               appraisal_type, value_usd,
                               estimated_liquidation_expenses_usd):
    deficiency_base = q2(D(current_principal_balance_usd)
                         + D(accrued_unpaid_interest_usd)
                         + D(advance_principal)
                         + D(advance_interest_total))
    if appraisal_type == "FULL_NARRATIVE":
        basis = "NET_LIQUIDATION_BASIS"
        credit = q2(APPRAISAL_CREDIT_PCT
                    * (D(value_usd) - D(estimated_liquidation_expenses_usd)))
    else:
        basis = "GROSS_APPRAISED_BASIS"
        credit = q2(APPRAISAL_CREDIT_PCT * D(value_usd))
    ara = dmax(ZERO, q2(deficiency_base - credit))
    cpb = D(current_principal_balance_usd)
    if cpb == 0:
        pct = q4(0)
    else:
        pct = q4(ara / cpb * Decimal(100))
    return {
        "calculation_basis": basis,
        "deficiency_base_usd": q2(deficiency_base),
        "appraisal_credit_usd": q2(credit),
        "ara_amount_usd": q2(ara),
        "ara_percentage": pct,
    }


# ------------------------------------------- 4. ara_adjusted_advance_obligation
def ara_adjusted_advance_obligation(monthly_debt_service_usd,
                                    current_principal_balance_usd, ara_amount_usd):
    ara = D(ara_amount_usd)
    mds = D(monthly_debt_service_usd)
    cpb = D(current_principal_balance_usd)
    if ara == 0:
        return q2(mds)
    if cpb == 0:
        return q2(0)
    return q2(mds * (cpb - ara) / cpb)


# ------------------------------------------------ 5. servicing_standard_analysis
def servicing_standard_analysis(npv_with, npv_without, current_principal_balance_usd):
    margin = q2(D(npv_with) - D(npv_without))
    required = dmax(ABSOLUTE_MARGIN_FLOOR_USD,
                    q2(RELATIVE_MARGIN_PCT * D(current_principal_balance_usd)))
    conclusion = "SERVICING_STANDARD_MET" if margin >= required else "SERVICING_STANDARD_NOT_MET"
    return q2(margin), q2(required), conclusion


# ------------------------------------------------ 6. request_deposit_floor
def request_deposit_floor(request_type):
    return DEPOSIT_FLOOR_USD[request_type]


# --------------------------------------------- 7. consultation_response_deadline
def consultation_response_deadline(issued_at_dt, business_days):
    return add_business_days(issued_at_dt, int(business_days))


# ------------------------------------------------ 8. workout_alternative_npv
def workout_alternative_npv(projected_cash_flows, upfront_cost_usd,
                            discount_rate_pct, npv_basis):
    rate = D(discount_rate_pct) / Decimal(100)
    shift = 0 if npv_basis == "CONTRACTUAL" else 1
    base = Decimal(1) + rate
    total = ZERO
    for entry in sorted(projected_cash_flows, key=lambda e: int(e["period_index"])):
        exponent = int(entry["period_index"]) + shift
        total = total + q2(D(entry["amount_usd"]) / (base ** exponent))
    discounted_pv = q2(total)
    npv = q2(discounted_pv - D(upfront_cost_usd))
    return discounted_pv, npv


# --------------------------------------------- 9. workout_alternative_ranking
def rank_alternatives(pool):
    """Sort by npv DESC, type ordinal ASC, created_at ASC (id never used)."""
    ordered = sorted(
        pool,
        key=lambda a: (
            -D(a["npv_usd"]),
            ALTERNATIVE_TYPE_ORDINAL.get(a["alternative_type"], 99),
            a["created_at"],
            a["_seq"],
        ),
    )
    for index, alt in enumerate(ordered, start=1):
        alt["rank"] = index
    return ordered


# --------------------------------------- 10. controlling_class_control_test
def controlling_class_control_test(original_balance, total_ara, realized_loss):
    notional = dmax(ZERO, q2(D(original_balance) - D(total_ara) - D(realized_loss)))
    threshold = q2(CONTROL_TERMINATION_PCT * D(original_balance))
    status = "CONTROLLING" if notional >= threshold else "CONSULTING_ONLY"
    return q2(notional), q2(threshold), status


# --------------------------------------- 11. special_servicing_fee_accrual
def special_servicing_fee_accrual(current_principal_balance_usd, ara_amount_usd,
                                  annual_pct, fee_basis_convention):
    monthly_rate = D(annual_pct) / Decimal(100) / MONTHS_PER_YEAR
    if fee_basis_convention == "STATED_PRINCIPAL":
        basis = q2(D(current_principal_balance_usd))
    else:
        basis = q2(D(current_principal_balance_usd) - D(ara_amount_usd))
    raw = q2(basis * monthly_rate)
    amount = dmax(MONTHLY_FEE_FLOOR_USD, raw)
    rate_pct = q6(monthly_rate * Decimal(100))
    return q2(basis), rate_pct, q2(amount)


# --------------------------------------- 12. workout_fee_accrual
def workout_fee_accrual(collection_amount_usd, workout_fee_rate_pct):
    basis = q2(D(collection_amount_usd))
    rate_pct = q6(workout_fee_rate_pct)
    amount = dmin(FEE_CAP_USD, q2(D(collection_amount_usd) * rate_pct / Decimal(100)))
    return basis, rate_pct, q2(amount)


def liquidation_fee_amount(gross_proceeds_usd, liquidation_fee_rate_pct):
    return dmin(FEE_CAP_USD,
                q2(D(gross_proceeds_usd) * D(liquidation_fee_rate_pct) / Decimal(100)))
