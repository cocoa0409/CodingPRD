"""CareAssessment business logic."""
from decimal import Decimal, ROUND_HALF_UP

from clock import iso_now, now, parse_dt
import datetime as _dt
from db import get_db
from errors import APIError
from helpers import touch
from services import audit


W_ADL = Decimal("0.5")
W_COG = Decimal("1.0")
W_MED = Decimal("1.0")


def compute_composite_and_classification(adl, cog, med):
    composite = (Decimal(100 - adl) * W_ADL
                 + Decimal(30 - cog) * W_COG
                 + Decimal(med) * W_MED)
    composite = composite.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    composite_float = float(composite)
    if composite_float >= 80:
        classification = "INTENSIVE"
    elif composite_float >= 60:
        classification = "L4"
    elif composite_float >= 40:
        classification = "L3"
    elif composite_float >= 20:
        classification = "L2"
    else:
        classification = "L1"
    return composite_float, classification


def approve(assessment, user_id, role):
    """PENDING_APPROVAL -> APPROVED. Cascade ACTIVE care plan to UNDER_REVIEW
    if its care_level_snapshot differs from this classification.
    """
    db = get_db()
    prev = assessment["status"]
    if prev != "PENDING_APPROVAL":
        raise APIError("ERR_INVALID_STATE",
                       f"Assessment is {prev}, expected PENDING_APPROVAL", 409)
    if user_id == assessment.get("assessor_id"):
        raise APIError("ERR_SEGREGATION_OF_DUTIES",
                       "Approver must differ from assessor", 403)
    assessment["status"] = "APPROVED"
    assessment["approver_id"] = user_id
    eff_from = now()
    assessment["effective_from"] = iso_now()
    due = eff_from + _dt.timedelta(days=90)
    from clock import format_dt
    assessment["due_for_reassessment_at"] = format_dt(due)
    touch(assessment)

    # Update elder.current_care_level
    elder = db.elders.get(assessment["elder_id"])
    if elder is not None:
        elder["current_care_level"] = assessment["classification"]
        touch(elder)
        # Cascade ACTIVE plan(s) whose snapshot differs
        for plan in list(db.care_plans.values()):
            if (plan["elder_id"] == elder["id"]
                    and plan["status"] == "ACTIVE"
                    and plan.get("care_level_snapshot") != assessment["classification"]):
                pprev = plan["status"]
                plan["status"] = "UNDER_REVIEW"
                touch(plan)
                audit.log(role, user_id, "CarePlan", plan["id"],
                          "REVIEW_FLAGGED", pprev, plan["status"])
        # Update queued waitlist entries' priority for this elder
        from services import waitlist as waitlist_svc
        for entry in db.waitlist.values():
            if entry["elder_id"] == elder["id"] and entry["status"] == "QUEUED":
                entry["priority_score"] = waitlist_svc.compute_priority(elder)

    audit.log(role, user_id, "CareAssessment", assessment["id"],
              "APPROVE", prev, assessment["status"])


def reject(assessment, user_id, role):
    prev = assessment["status"]
    if prev != "PENDING_APPROVAL":
        raise APIError("ERR_INVALID_STATE",
                       f"Assessment is {prev}, expected PENDING_APPROVAL", 409)
    if user_id == assessment.get("assessor_id"):
        raise APIError("ERR_SEGREGATION_OF_DUTIES",
                       "Reviewer must differ from assessor", 403)
    assessment["status"] = "REJECTED"
    touch(assessment)
    audit.log(role, user_id, "CareAssessment", assessment["id"],
              "REJECT", prev, assessment["status"])


def return_for_revision(assessment, user_id, role):
    prev = assessment["status"]
    if prev != "PENDING_APPROVAL":
        raise APIError("ERR_INVALID_STATE",
                       f"Assessment is {prev}, expected PENDING_APPROVAL", 409)
    if user_id == assessment.get("assessor_id"):
        raise APIError("ERR_SEGREGATION_OF_DUTIES",
                       "Reviewer must differ from assessor", 403)
    assessment["status"] = "DRAFT"
    touch(assessment)
    audit.log(role, user_id, "CareAssessment", assessment["id"],
              "RETURN_FOR_REVISION", prev, assessment["status"])
