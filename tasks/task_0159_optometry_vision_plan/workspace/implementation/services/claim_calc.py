"""Claim adjudication cost calculation (PRD §3.8).

ROUTINE: plan_paid = max(0, billed - exam_copay); patient = min(billed, copay).
MEDICAL: plan pays 80% of exam_fee (round half up); patient = (exam - plan)
         + refraction_fee; billed = exam_fee + refraction_fee.
"""
from decimal import Decimal, ROUND_HALF_UP

MEDICAL_COINSURANCE_RATE = Decimal("0.80")


def adjudicate_routine(exam_fee, refraction_fee, exam_copay):
    billed = exam_fee + refraction_fee
    plan_paid = max(0, billed - exam_copay)
    patient_responsibility = min(billed, exam_copay)
    return billed, plan_paid, patient_responsibility


def adjudicate_medical(exam_fee, refraction_fee):
    covered = exam_fee
    # plan pays 80% of the covered exam fee, rounded half up to whole cents,
    # before the patient share is derived from it.
    plan_paid = int((Decimal(covered) * MEDICAL_COINSURANCE_RATE).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    patient_coins = covered - plan_paid
    patient_responsibility = patient_coins + refraction_fee
    billed = covered + refraction_fee
    return billed, plan_paid, patient_responsibility
