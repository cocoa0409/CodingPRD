"""Application adjudication and premium pricing (PRD §3.3, §3.4)."""
import db
from clock import parse_iso
from errors import err
from helpers import round_half_up
from services import timecalc

CLASS_MULT = {
    "STANDARD": 1.00,
    "TOBACCO": 1.50,
    "SUBSTANDARD": 2.00,
}


def compute_attained_age(applicant, reference_iso):
    """Whole-year attained age on the reference date (Application.created_at)."""
    dob = parse_iso(applicant["date_of_birth"])
    ref = parse_iso(reference_iso)
    if dob is None or ref is None:
        return 0
    age = ref.year - dob.year
    # Subtract one if this year's birthday has not yet occurred by ref.
    try:
        birthday = dob.replace(year=ref.year)
    except ValueError:
        birthday = dob.replace(year=ref.year, day=28)
    if birthday > ref:
        age -= 1
    return age


def face_tier_for(plan, face_cents):
    for tier in plan.get("face_tiers", []):
        if tier["min_face_cents"] <= face_cents <= tier["max_face_cents"]:
            return tier
    return None


def age_band_for(plan, attained_age):
    for band in plan.get("age_bands", []):
        if band["min_age"] <= attained_age <= band["max_age"]:
            return band
    return None


def submit(application):
    """Submit -> auto-adjudicate (PRD §3.3). Mutates application in place."""
    plan = db.product_plans.get(application["product_plan_id"])
    applicant = db.applicants.get(application["applicant_id"])
    questionnaires = [
        q for q in db.health_questionnaires.values()
        if q["application_id"] == application["id"]
    ]
    if len(questionnaires) != 1:
        raise err("ERR_QUESTIONNAIRE_MISSING", "Exactly one HealthQuestionnaire is required")
    questionnaire = questionnaires[0]

    application["status"] = "SUBMITTED"
    attained = compute_attained_age(applicant, application["created_at"])
    application["attained_age"] = attained

    knockout = questionnaire["knockout_triggered"]
    age_out = attained < plan["min_issue_age"] or attained > plan["max_issue_age"]
    face_tier = face_tier_for(plan, application["requested_face_amount_cents"])
    face_out = face_tier is None

    # Hard decline, precedence: knockout -> age -> face.
    if knockout or age_out or face_out:
        application["status"] = "DECLINED"
        application["rating_class"] = "DECLINE"
        if knockout:
            application["decline_reason"] = "KNOCKOUT_CONDITION"
        elif age_out:
            application["decline_reason"] = "AGE_OUT_OF_BAND"
        else:
            application["decline_reason"] = "FACE_OUT_OF_RANGE"
        return application

    major = questionnaire["major_condition_last_2y"]
    # Soft referral: major condition on a LEVEL_BENEFIT plan.
    if major and plan["benefit_type"] == "LEVEL_BENEFIT":
        application["status"] = "REFERRED"
        return application

    # Otherwise APPROVED.
    _approve(application, plan, applicant, questionnaire)
    return application


def approve_referred(application):
    """Manual approval of a REFERRED application (PRD §3.3)."""
    if application["status"] != "REFERRED":
        raise err("ERR_INVALID_STATE", "Application is not REFERRED")
    plan = db.product_plans.get(application["product_plan_id"])
    applicant = db.applicants.get(application["applicant_id"])
    questionnaire = _questionnaire(application)
    _approve(application, plan, applicant, questionnaire)
    return application


def decline_referred(application):
    if application["status"] != "REFERRED":
        raise err("ERR_INVALID_STATE", "Application is not REFERRED")
    application["status"] = "DECLINED"
    application["rating_class"] = "DECLINE"
    application["decline_reason"] = "KNOCKOUT_CONDITION"
    return application


def _questionnaire(application):
    for q in db.health_questionnaires.values():
        if q["application_id"] == application["id"]:
            return q
    return None


def _approve(application, plan, applicant, questionnaire):
    application["status"] = "APPROVED"
    rating_class = compute_rating_class(plan, applicant, questionnaire)
    application["rating_class"] = rating_class
    application["quoted_monthly_premium_cents"] = compute_premium(
        application, plan, rating_class
    )


def compute_rating_class(plan, applicant, questionnaire):
    """TOBACCO if tobacco_use else STANDARD; SUBSTANDARD if major condition on
    a GRADED_BENEFIT or GUARANTEED_ISSUE plan (PRD §3.3)."""
    major = questionnaire["major_condition_last_2y"]
    if major and plan["benefit_type"] in ("GRADED_BENEFIT", "GUARANTEED_ISSUE"):
        return "SUBSTANDARD"
    if applicant["tobacco_use"]:
        return "TOBACCO"
    return "STANDARD"


def compute_premium(application, plan, rating_class):
    """premium_rate calculation (PRD §3.4), pinned evaluation order."""
    face_units = application["requested_face_amount_cents"] / 100000
    band = age_band_for(plan, application["attained_age"])
    age_factor = band["age_factor"]
    tier = face_tier_for(plan, application["requested_face_amount_cents"])
    tier_load_pct = tier["tier_load_pct"]
    class_mult = CLASS_MULT[rating_class]
    raw = plan["base_monthly_rate_per_1000_cents"] * face_units * age_factor
    loaded = raw * (1 + tier_load_pct)
    premium = round_half_up(loaded * class_mult)
    return premium
