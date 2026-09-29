"""Loan file valuation, loan-to-value banding and the underwriting cascade."""

import db
from validate import bps_of
from services import constants as C


def impact_for(ltv_bps):
    """Decision impact bands, upper bounds inclusive."""
    if ltv_bps is None:
        return None
    if ltv_bps <= C.LTV_NO_IMPACT_MAX_BPS:
        return "NO_IMPACT"
    if ltv_bps <= C.LTV_PRICING_MAX_BPS:
        return "PRICING_ADJUSTMENT"
    if ltv_bps <= C.LTV_CONDITION_MAX_BPS:
        return "CONDITION_REQUIRED"
    return "DENIAL_RECOMMENDED"


def revision_delta_sum(appraisal_id):
    """Signed sum of every value revision recorded against an appraisal,
    compensating entries included."""
    total = 0
    for rev in db.value_revisions.values():
        if rev["appraisal_id"] == appraisal_id:
            total += rev["delta_cents"]
    return total


def recompute_loan_values(loan):
    """Recompute current_appraised_value_cents, effective_value_cents, ltv_bps
    and decision_impact, then run the underwriting cascade."""
    vor_id = loan.get("value_of_record_appraisal_id")
    appraisal = db.appraisals.get(vor_id) if vor_id else None
    if appraisal is None:
        return
    current = appraisal["reported_value_cents"] + revision_delta_sum(appraisal["id"])
    loan["current_appraised_value_cents"] = current
    if loan["loan_purpose"] == "PURCHASE" and loan.get("contract_price_cents") is not None:
        effective = min(current, loan["contract_price_cents"])
    else:
        effective = current
    loan["effective_value_cents"] = effective
    loan["ltv_bps"] = bps_of(loan["loan_amount_cents"], effective) if effective > 0 else None
    loan["decision_impact"] = impact_for(loan["ltv_bps"])
    db.touch(loan)
    apply_underwriting_cascade(loan)


def apply_underwriting_cascade(loan):
    """DENIAL_RECOMMENDED suspends; any softer tier reinstates a suspended
    loan to CONDITIONALLY_APPROVED regardless of where it was suspended from."""
    impact = loan.get("decision_impact")
    status = loan["underwriting_status"]
    if impact == "DENIAL_RECOMMENDED":
        if status in ("SUBMITTED", "CONDITIONALLY_APPROVED"):
            loan["underwriting_status"] = "SUSPENDED"
            db.touch(loan)
    elif impact is not None:
        if status == "SUSPENDED":
            loan["underwriting_status"] = "CONDITIONALLY_APPROVED"
            db.touch(loan)


def appraisal_quarantined(appraisal):
    if appraisal is None:
        return False
    return appraisal["bias_screen_status"] == "SUBSTANTIATED" or appraisal["review_status"] == "QUARANTINED"


def loan_quarantined(loan):
    if loan["collateral_status"] == "QUARANTINED":
        return True
    vor_id = loan.get("value_of_record_appraisal_id")
    if vor_id:
        return appraisal_quarantined(db.appraisals.get(vor_id))
    return False


def refresh_rov_count(loan):
    loan["rov_request_count"] = sum(
        1 for r in db.rov_requests.values() if r["loan_file_id"] == loan["id"])
    db.touch(loan)


def collateral_for_review_status(review_status):
    """Projection used when a bias quarantine is lifted on appeal."""
    if review_status == "VALUE_ACCEPTED":
        return "VALUE_ACCEPTED"
    if review_status == "VALUE_REVISED":
        return "VALUE_REVISED"
    if review_status == "VALUE_CONTESTED":
        return "VALUE_CONTESTED"
    if review_status in ("IN_DESK_REVIEW", "ESCALATED", "RETURNED_TO_AMC"):
        return "UNDER_REVIEW"
    return "PENDING_APPRAISAL"
