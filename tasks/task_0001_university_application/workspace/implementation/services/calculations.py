"""Calculation rules from SCAFFOLD §1.3."""

from decimal import Decimal, ROUND_HALF_UP

import db


# --------------------------------------------------------------------------- #
# demonstrated_need_calc
# --------------------------------------------------------------------------- #

def compute_demonstrated_need(aid_offer_row, fa_profile_row):
    """Integer-cents result.

    aid_offer_row['variant'] selects the applicable EFC:
      FEDERAL       -> fa_profile_row['fafsa_efc_cents']
      INSTITUTIONAL -> fa_profile_row['css_efc_cents']
    """
    if aid_offer_row["variant"] == "FEDERAL":
        applicable_efc = fa_profile_row["fafsa_efc_cents"]
    else:
        applicable_efc = fa_profile_row.get("css_efc_cents")
    if applicable_efc is None:
        applicable_efc = 0
    return max(0, aid_offer_row["cost_of_attendance_cents"] - applicable_efc)


def compute_net_price(aid_offer_row):
    """Integer-cents result, floored at 0."""
    return max(
        0,
        aid_offer_row["cost_of_attendance_cents"]
        - aid_offer_row["grant_cents"]
        - aid_offer_row["loan_cents"]
        - aid_offer_row["work_study_cents"],
    )


# --------------------------------------------------------------------------- #
# applicant_admission_probability_score
# --------------------------------------------------------------------------- #

# Per PRD §3.5 the score is the integer sum of four components, with
# rounding/flooring/capping applied at the per-component step before summation.

PROVISIONAL_LETTER_STATUSES = frozenset({"REQUESTED", "IN_PROGRESS", "SUBMITTED"})
FINAL_LETTER_STATUSES = frozenset({"SUBMITTED"})


def _round_half_up_int(value) -> int:
    """Apply ROUND_HALF_UP to a real value, returning a Python int."""
    quantized = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def compute_admission_probability_score(application_row, variant: str) -> int:
    applicant = db.applicants.get(application_row["applicant_id"])

    # GPA component: round_half_up(gpa * 10), then cap at 40
    gpa_value = applicant["gpa"] if applicant else 0
    gpa_real = Decimal(str(gpa_value)) * Decimal("10")
    gpa_component = min(40, _round_half_up_int(gpa_real))

    # SAT component: floor((sat_total - 400) / 40), capped at 30; 0 if null
    sat_total = applicant.get("sat_total") if applicant else None
    if sat_total is None:
        sat_component = 0
    else:
        sat_component = min(30, (int(sat_total) - 400) // 40)

    # Plan bonus
    plan = application_row["plan"]
    if plan == "EARLY_DECISION":
        plan_bonus = 15
    elif plan == "EARLY_ACTION":
        plan_bonus = 8
    elif plan == "ROLLING":
        plan_bonus = 5
    else:
        plan_bonus = 0

    # Letters factor: 5 * qualifying letter count, capped at 15
    if variant == "FINAL":
        statuses = FINAL_LETTER_STATUSES
    else:
        statuses = PROVISIONAL_LETTER_STATUSES
    letter_count = 0
    for letter in db.recommendation_letters.values():
        if letter["application_id"] == application_row["id"] and letter["status"] in statuses:
            letter_count += 1
    letters_factor = min(15, 5 * letter_count)

    score = gpa_component + sat_component + plan_bonus + letters_factor
    # Score is naturally bounded 0..100 by the per-component caps but guard
    # against negative or out-of-range values just in case.
    return max(0, min(100, int(score)))


def default_score_variant(application_status: str) -> str:
    """Default variant when ?score_variant is not supplied (PRD §3.4)."""
    if application_status in ("DRAFT", "SUBMITTED"):
        return "PROVISIONAL"
    return "FINAL"


# --------------------------------------------------------------------------- #
# school_yield_rate
# --------------------------------------------------------------------------- #

ADMITTED_STATUSES_FOR_YIELD = frozenset({"ADMITTED", "ENROLLED", "DECLINED_OFFER"})


def compute_yield_rate(school_id: str):
    """Return (yield_rate or None, admitted_count, enrolled_count)."""
    admitted = 0
    enrolled = 0
    for app in db.applications.values():
        if app["school_id"] != school_id:
            continue
        if app["status"] in ADMITTED_STATUSES_FOR_YIELD:
            admitted += 1
            if app["status"] == "ENROLLED":
                enrolled += 1
    if admitted == 0:
        return None, 0, 0
    rate = (Decimal(enrolled) / Decimal(admitted)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    # Return as float for JSON friendliness; the four-decimal-place precision
    # is preserved by Decimal.quantize above.
    return float(rate), admitted, enrolled
