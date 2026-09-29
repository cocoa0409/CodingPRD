"""Desk review quality scoring and the escalation requirement matrix."""

import db
from services import constants as C
from services.appraisal import eligible_comps, distance_ceiling


def rule_penalty(appraisal):
    return (C.RULE_FAIL_PENALTY_BPS * appraisal["rule_check_fail_count"]
            + C.RULE_WARN_PENALTY_BPS * appraisal["rule_check_warn_count"])


def distance_penalty(appraisal, loan):
    ceiling = distance_ceiling(loan)
    for comp in eligible_comps(appraisal["id"]):
        if comp["distance_miles"] > ceiling:
            return C.DISTANCE_PENALTY_BPS
    return 0


def bias_penalty(appraisal):
    status = appraisal["bias_screen_status"]
    if status == "INDICATED":
        return C.BIAS_INDICATED_PENALTY_BPS
    if status == "SUBSTANTIATED":
        return C.BIAS_SUBSTANTIATED_PENALTY_BPS
    return 0


def preliminary_score(appraisal):
    base = appraisal["completeness_score_bps"] or 0
    return max(0, base - rule_penalty(appraisal))


def final_score(appraisal, loan):
    base = appraisal["completeness_score_bps"] or 0
    return max(0, base - rule_penalty(appraisal)
               - distance_penalty(appraisal, loan) - bias_penalty(appraisal))


def required_escalation(appraisal, risk_tier, score_bps):
    """Clause 1 short circuits on bias; clause 2 reads the risk tier snapshot;
    clause 3 can only upgrade NONE."""
    if appraisal["bias_screen_status"] in ("INDICATED", "SUBSTANTIATED"):
        return "SECOND_APPRAISAL"

    if risk_tier == "HIGH":
        if score_bps < 7000:
            result = "SECOND_APPRAISAL"
        elif score_bps < 8500:
            result = "FIELD_REVIEW"
        else:
            result = "NONE"
    elif risk_tier == "ELEVATED":
        if score_bps < 6000:
            result = "SECOND_APPRAISAL"
        elif score_bps < 8000:
            result = "FIELD_REVIEW"
        else:
            result = "NONE"
    elif risk_tier == "STANDARD":
        result = "FIELD_REVIEW" if score_bps < 6000 else "NONE"
    else:
        result = "FIELD_REVIEW" if score_bps < 5000 else "NONE"

    if result == "NONE" and appraisal["max_gross_adjustment_bps"] > C.GROSS_ADJ_FAIL_ABOVE:
        result = "FIELD_REVIEW"
    return result


def open_review_for(appraisal_id):
    for review in db.ordered(db.desk_reviews):
        if review["appraisal_id"] == appraisal_id and review["status"] in ("DRAFT", "SUBMITTED"):
            return review
    return None
