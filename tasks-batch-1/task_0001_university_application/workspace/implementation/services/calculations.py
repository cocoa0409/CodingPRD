"""§1.3 calculation rules.

All money is in integer USD cents. All round-half-up is via Decimal with
ROUND_HALF_UP. Composite uses per-component rounding before summation.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import db


# Constants
SHELTER_PER_PERSON_CENTS = 800000
INCOME_ASSESSMENT_RATE = Decimal("0.22")
ASSET_ASSESSMENT_RATE = Decimal("0.05")

WEIGHT_GPA = Decimal("0.40")
WEIGHT_SAT = Decimal("0.20")
WEIGHT_ESSAY = Decimal("0.15")
WEIGHT_REC = Decimal("0.25")
NULL_SAT_NEUTRAL = Decimal("50.00")

ON_TARGET_THRESHOLD = Decimal("0.85")
OVER_TARGET_THRESHOLD = Decimal("1.00")


def _round_half_up_int(value: Decimal) -> int:
    """Round a Decimal to the nearest integer using round-half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_half_up_2dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- efc_calc
def efc_calc(profile_type: str, household_income_cents: int, household_size: int,
             declared_assets_cents: int) -> int:
    """Expected Family Contribution.

    Rounding order pinned: income component first, asset component second,
    sum of two already-rounded integers is final.
    """
    shelter = SHELTER_PER_PERSON_CENTS * household_size
    adjusted_income = max(0, household_income_cents - shelter)
    # base = round_half_up(adjusted_income * 0.22)
    base = _round_half_up_int(Decimal(adjusted_income) * INCOME_ASSESSMENT_RATE)
    if profile_type == "FAFSA":
        return base
    # CSS_PROFILE
    asset_contrib = _round_half_up_int(
        Decimal(declared_assets_cents) * ASSET_ASSESSMENT_RATE
    )
    return base + asset_contrib


# ---------------------------------------------------------------- composite_score_calc
def composite_score_calc(application: dict) -> Optional[Decimal]:
    """Compute Application.composite_score per §1.3.

    Returns a Decimal with two decimals (or None if applicant doesn't exist).
    The caller persists this as a number; we return a Decimal so the route
    layer can serialize to a JSON number via float() or string-formatting.
    """
    applicant = db.applicants.get(application["applicant_id"])
    if applicant is None:
        return None

    # gpa_normalized = round_half_up(gpa / 4.00 * 100, 2)
    gpa = Decimal(str(applicant["gpa_unweighted"]))
    gpa_normalized = _round_half_up_2dp(gpa / Decimal("4.00") * Decimal("100"))

    # sat_normalized
    sat_total = applicant.get("sat_total")
    if sat_total is None:
        sat_normalized = NULL_SAT_NEUTRAL
    else:
        sat_normalized = _round_half_up_2dp(
            (Decimal(sat_total) - Decimal("400")) / Decimal("1200") * Decimal("100")
        )

    # essay_count: completed essays for this application
    essay_count = sum(
        1
        for e in db.essays.values()
        if e["application_id"] == application["id"] and e["completed"] is True
    )
    essay_score = min(Decimal("100.00"), Decimal(essay_count) * Decimal("20.00"))

    # rec_avg_rating: SUBMITTED recommendation requests for (applicant_id, school_id)
    matching = [
        r
        for r in db.recommendation_requests.values()
        if r["applicant_id"] == application["applicant_id"]
        and r["school_id"] == application["school_id"]
        and r["status"] == "SUBMITTED"
    ]
    if matching:
        total = sum(r["rating"] for r in matching)
        rec_avg_rating = Decimal(total) / Decimal(len(matching))
    else:
        rec_avg_rating = Decimal("0")
    rec_score = _round_half_up_2dp(rec_avg_rating / Decimal("5.00") * Decimal("100"))

    # Per-component round then sum
    gpa_term = _round_half_up_2dp(gpa_normalized * WEIGHT_GPA)
    sat_term = _round_half_up_2dp(sat_normalized * WEIGHT_SAT)
    essay_term = _round_half_up_2dp(essay_score * WEIGHT_ESSAY)
    rec_term = _round_half_up_2dp(rec_score * WEIGHT_REC)

    composite = _round_half_up_2dp(gpa_term + sat_term + essay_term + rec_term)
    return composite


def composite_score_as_number(application: dict):
    """Return composite as a float for JSON or None if not computable."""
    d = composite_score_calc(application)
    if d is None:
        return None
    return float(d)


# ---------------------------------------------------------------- net_cost_calc
def net_cost_calc(aid_package: dict) -> int:
    application = db.applications[aid_package["application_id"]]
    school = db.schools[application["school_id"]]
    applicant = db.applicants[application["applicant_id"]]
    residency = applicant["residency"]
    if residency == "IN_STATE":
        tuition = school["in_state_tuition_cents"]
    elif residency == "OUT_OF_STATE":
        tuition = school["out_of_state_tuition_cents"]
    else:
        tuition = school["international_tuition_cents"]
    total_award = aid_package["grant_cents"] + aid_package["loan_cents"] + aid_package["work_study_cents"]
    return tuition - total_award


# ---------------------------------------------------------------- yield_posture_calc
def yield_posture_calc(school: dict) -> str:
    admitted = Decimal(school["admitted_count"])
    enrolled = Decimal(school["enrolled_count"])
    yield_rate = Decimal(str(school["assumed_yield_rate"]))
    target = Decimal(school["target_class_size"])
    projected = _round_half_up_int(admitted * yield_rate + enrolled)
    # ratio compared as float-ish with >=; use Decimal for fidelity
    ratio = Decimal(projected) / target
    if ratio >= OVER_TARGET_THRESHOLD:
        return "OVER_TARGET"
    if ratio >= ON_TARGET_THRESHOLD:
        return "ON_TARGET"
    return "OPEN"


def recompute_yield_posture(school: dict):
    school["yield_posture"] = yield_posture_calc(school)


def recompute_application_composite(application: dict):
    """Update application.composite_score in place."""
    score = composite_score_as_number(application)
    application["composite_score"] = score
