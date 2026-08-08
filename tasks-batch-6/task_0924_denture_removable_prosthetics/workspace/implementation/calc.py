"""The 16 calculation rules (PRD 2.7, 3.x; SCAFFOLD `calculations`).

Money is Decimal throughout, two decimal places, ROUND_HALF_UP, rounded at
each declared step and never once at the end.
"""
from decimal import Decimal

import pconst
from util import ZERO, add_days, add_months, q2

D = Decimal


# 1. impression_quality_band --------------------------------------------------
def impression_quality_band(score):
    if score >= pconst.IMPRESSION_ACCEPT_MIN:
        return "ACCEPTED"
    if score >= pconst.IMPRESSION_PROVISIONAL_MIN:
        return "PROVISIONAL_ACCEPTED"
    return "REJECTED"


# 2. lab_promised_due_at (dual variant: STANDARD / RUSH) ----------------------
def lab_promised_due_at(dispatched_at, lab, turnaround_class):
    days = (
        lab["standard_turnaround_days"]
        if turnaround_class == "STANDARD"
        else lab["rush_turnaround_days"]
    )
    return add_days(dispatched_at, days)


def lab_shelf_life_expires_at(dispatched_at):
    return add_days(dispatched_at, pconst.LAB_SHELF_LIFE_DAYS)


# 3. lab_rush_fee -------------------------------------------------------------
def lab_rush_fee(turnaround_class, unit_count):
    if turnaround_class == "STANDARD":
        return ZERO
    return q2(pconst.LAB_RUSH_FEE_BASE + pconst.LAB_RUSH_FEE_PER_UNIT * unit_count)


# 4. arch_fee_schedule_amount -------------------------------------------------
def arch_fee(prosthesis_type):
    return pconst.FEE_BY_TYPE[prosthesis_type]


# 5. predetermination_plan_payment (dual variant) -----------------------------
def predetermination_estimate(allowed_amount, coverage, requested_amount):
    uncapped = q2(allowed_amount * coverage["coinsurance_major_rate"])
    remaining = coverage_benefit_remaining(coverage)
    plan_payment = uncapped if uncapped < remaining else remaining
    patient = q2(requested_amount - plan_payment)
    return q2(plan_payment), patient


# 6. claim_primary_payment ----------------------------------------------------
def claim_primary_payment(claim, primary):
    uncapped = q2(claim["allowed_amount"] * primary["coinsurance_major_rate"])
    remaining = coverage_benefit_remaining(primary)
    paid = uncapped if uncapped < remaining else remaining
    return q2(paid)


# 7. claim_secondary_cob_payment (dual variant) -------------------------------
def claim_secondary_cob_payment(claim, secondary, convention):
    would_have_paid = q2(claim["allowed_amount"] * secondary["coinsurance_major_rate"])
    patient_balance = q2(claim["billed_amount"] - claim["primary_paid_amount"])
    if patient_balance < ZERO:
        patient_balance = ZERO
    if convention == "STANDARD":
        top_up = q2(claim["allowed_amount"] - claim["primary_paid_amount"])
        raw = top_up if top_up < patient_balance else patient_balance
    else:  # NON_DUPLICATION
        raw = q2(would_have_paid - claim["primary_paid_amount"])
        if raw < ZERO:
            raw = ZERO
    if raw < ZERO:
        raw = ZERO
    remaining = coverage_benefit_remaining(secondary)
    return q2(raw if raw < remaining else remaining)


# 8. warranty_and_replacement_clocks (dual variant) ---------------------------
def warranty_expires_at(delivered_at):
    return add_days(delivered_at, pconst.WARRANTY_WINDOW_DAYS)


def replacement_eligible_date(frequency_anchor_at):
    return add_months(frequency_anchor_at, pconst.REPLACEMENT_FREQUENCY_MONTHS)


# 9. recall_schedule ----------------------------------------------------------
def recall_due_at(delivered_at, prosthesis_type, recall_cycle_count):
    interval = pconst.RECALL_INTERVAL_DAYS[prosthesis_type]
    return add_days(delivered_at, interval * (recall_cycle_count + 1))


# 10. post_delivery_service_charge (dual variant on ADJUSTMENT) ---------------
def post_delivery_service_charge(service, prosthesis, now, warranty_backed):
    if service["service_type"] == "ADJUSTMENT":
        within_count = prosthesis["adjustments_used"] < pconst.ADJUSTMENT_ALLOWANCE_COUNT
        within_window = now <= prosthesis["adjustment_window_ends_at"]
        if within_count and within_window:
            return "INCLUDED", ZERO
        return "CHARGEABLE", pconst.ADJUSTMENT_CHARGEABLE_FEE
    if warranty_backed:
        return "WARRANTY_NO_CHARGE", ZERO
    return "CHARGEABLE", pconst.SERVICE_FEE[service["service_type"]]


# 11. service_frequency_eligibility -------------------------------------------
def service_frequency_eligible(service_type, completed_rows, now):
    months = pconst.SERVICE_FREQ_MONTHS[service_type]
    if months == 0:
        return True
    if not completed_rows:
        return True
    latest = sorted(
        completed_rows, key=lambda r: (r["completed_at"], r["created_at"])
    )[-1]
    return now >= add_months(latest["completed_at"], months)


# 12. lab_remake_credit (dual variant LAB_BORNE / CLINIC_BORNE) ---------------
def lab_remake_credit(verdict, lab_case):
    if verdict == "LAB_FAULT" and lab_case is not None:
        return q2(lab_case["lab_invoice_amount"] * pconst.LAB_FAULT_CREDIT_RATE)
    return ZERO


# 13. case_total_due ----------------------------------------------------------
def prompt_pay_rate(pre_discount):
    if pre_discount >= pconst.PROMPT_PAY_TIER_2_MIN:
        return pconst.PROMPT_PAY_TIER_2_RATE
    if pre_discount >= pconst.PROMPT_PAY_TIER_1_MIN:
        return pconst.PROMPT_PAY_TIER_1_RATE
    return pconst.PROMPT_PAY_TIER_0_RATE


# 14. installment_schedule ----------------------------------------------------
def installment_amounts(principal, count):
    base = q2(principal / D(count))
    amounts = [base] * (count - 1)
    amounts.append(q2(principal - base * (count - 1)))
    return amounts


def installment_due_date(first_due_date, sequence_number, frequency):
    spacing = pconst.PAYMENT_FREQUENCY_DAYS[frequency]
    return add_days(first_due_date, (sequence_number - 1) * spacing)


# --- shared derivations ------------------------------------------------------
def coverage_benefit_remaining(coverage):
    remaining = q2(coverage["annual_maximum_amount"] - coverage["benefit_used_ytd"])
    return remaining if remaining > ZERO else ZERO
