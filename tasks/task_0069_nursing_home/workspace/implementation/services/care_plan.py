"""CarePlan business logic."""
import datetime as _dt

from clock import format_dt, iso_now, now, parse_dt
from db import get_db
from errors import APIError
from helpers import touch
from services import audit


REVIEW_CYCLE_BY_LEVEL = {
    "L1": 90, "L2": 60, "L3": 45, "L4": 30, "INTENSIVE": 14,
}


def review_cycle_days(level):
    return REVIEW_CYCLE_BY_LEVEL.get(level)


def activate(plan, user_id, role):
    db = get_db()
    prev = plan["status"]
    if prev != "DRAFT":
        raise APIError("ERR_INVALID_STATE",
                       f"Plan is {prev}, expected DRAFT", 409)
    elder = db.elders.get(plan["elder_id"])
    if elder is None:
        raise APIError("ERR_INVALID_STATE", "Elder missing for plan", 409)
    assessment = db.care_assessments.get(plan["based_on_assessment_id"])
    if assessment is None:
        raise APIError("ERR_FK_NOT_FOUND",
                       "based_on_assessment_id not found", 404)
    # Single ACTIVE plan check (priority 14)
    for other in db.care_plans.values():
        if (other["elder_id"] == elder["id"]
                and other["status"] == "ACTIVE"
                and other["id"] != plan["id"]):
            raise APIError("ERR_ACTIVE_PLAN_EXISTS",
                           "Another ACTIVE CarePlan exists for elder", 409)
    if assessment.get("status") != "APPROVED":
        raise APIError("ERR_INVALID_STATE",
                       "based_on assessment must be APPROVED", 409)
    if assessment.get("classification") != elder.get("current_care_level"):
        raise APIError("ERR_PLAN_LEVEL_MISMATCH",
                       "Assessment classification doesn't match elder current_care_level",
                       409)

    plan["status"] = "ACTIVE"
    plan["care_level_snapshot"] = assessment["classification"]
    activated_dt = now()
    plan["activated_at"] = iso_now()
    cycle_days = review_cycle_days(assessment["classification"])
    plan["review_cycle_days"] = cycle_days
    plan["next_review_due_at"] = format_dt(activated_dt + _dt.timedelta(days=cycle_days))
    touch(plan)
    audit.log(role, user_id, "CarePlan", plan["id"],
              "ACTIVATE", prev, plan["status"])


def flag_review(plan, user_id, role):
    prev = plan["status"]
    if prev != "ACTIVE":
        raise APIError("ERR_INVALID_STATE",
                       f"Plan is {prev}, expected ACTIVE", 409)
    plan["status"] = "UNDER_REVIEW"
    touch(plan)
    audit.log(role, user_id, "CarePlan", plan["id"],
              "REVIEW_FLAGGED", prev, plan["status"])


def confirm_review(plan, user_id, role):
    prev = plan["status"]
    if prev != "UNDER_REVIEW":
        raise APIError("ERR_INVALID_STATE",
                       f"Plan is {prev}, expected UNDER_REVIEW", 409)
    plan["status"] = "ACTIVE"
    cycle_days = plan.get("review_cycle_days") or review_cycle_days(plan.get("care_level_snapshot"))
    plan["next_review_due_at"] = format_dt(now() + _dt.timedelta(days=cycle_days))
    touch(plan)
    audit.log(role, user_id, "CarePlan", plan["id"],
              "REVIEW_CONFIRM", prev, plan["status"])


def supersede(plan, new_plan_id, user_id, role):
    db = get_db()
    prev = plan["status"]
    if prev != "UNDER_REVIEW":
        raise APIError("ERR_INVALID_STATE",
                       f"Plan is {prev}, expected UNDER_REVIEW", 409)
    new_plan = db.care_plans.get(new_plan_id)
    if new_plan is None:
        raise APIError("ERR_FK_NOT_FOUND", "new_plan_id not found", 404)
    if new_plan["elder_id"] != plan["elder_id"]:
        raise APIError("ERR_INVALID_STATE",
                       "new_plan_id must belong to same elder", 409)
    if new_plan["status"] != "DRAFT":
        raise APIError("ERR_INVALID_STATE",
                       "new_plan must be DRAFT to be promoted", 409)
    # Activate new plan
    elder = db.elders.get(plan["elder_id"])
    new_assessment = db.care_assessments.get(new_plan["based_on_assessment_id"])
    if new_assessment is None:
        raise APIError("ERR_FK_NOT_FOUND",
                       "new plan's based_on_assessment_id not found", 404)
    new_prev = new_plan["status"]
    new_plan["status"] = "ACTIVE"
    new_plan["care_level_snapshot"] = new_assessment.get("classification")
    activated_dt = now()
    new_plan["activated_at"] = iso_now()
    cycle_days = review_cycle_days(new_plan["care_level_snapshot"])
    new_plan["review_cycle_days"] = cycle_days
    new_plan["next_review_due_at"] = format_dt(activated_dt + _dt.timedelta(days=cycle_days))
    touch(new_plan)
    audit.log(role, user_id, "CarePlan", new_plan["id"],
              "ACTIVATE", new_prev, new_plan["status"])

    # Move old to SUPERSEDED
    plan["status"] = "SUPERSEDED"
    touch(plan)
    db.care_plans_superseded_at[plan["id"]] = now()
    audit.log(role, user_id, "CarePlan", plan["id"],
              "SUPERSEDE", prev, plan["status"])
