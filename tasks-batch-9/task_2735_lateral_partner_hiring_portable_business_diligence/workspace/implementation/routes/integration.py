"""Integration plans, cross-sell introductions and performance reviews."""

from datetime import timedelta

import calculations as calc
import cascades
import listing
import lookups as lk
import middleware as mw
import services as svc
from db import db, new_row, pub, set_fields
from errors import ApiError
from flask import Blueprint
from response import object_response

bp = Blueprint("integration", __name__, url_prefix="/lateral-hiring")

READ_PLAN = ("SystemAdmin", "RecruitingCoordinator", "PracticeGroupLeader",
             "CommitteeMember", "CommitteeChair", "Candidate")
LIST_PLAN = ("SystemAdmin", "RecruitingCoordinator", "PracticeGroupLeader",
             "CommitteeMember", "CommitteeChair")


@bp.post("/candidates/<candidate_id>/integration-plans")
def create_plan(candidate_id):
    user_id, _role = mw.authenticate(("PracticeGroupLeader",))
    candidate = lk.get_candidate(candidate_id)
    data = mw.body()
    group = None
    offer = None
    if isinstance(data.get("practice_group_id"), str):
        group = lk.get_practice_group(data["practice_group_id"])
    if isinstance(data.get("offer_id"), str):
        offer = lk.get_offer(data["offer_id"])

    mw.v_str(data, "practice_group_id", 1, None)
    mw.v_str(data, "offer_id", 1, None)
    start = mw.v_dt(data, "onboarding_start_date")
    end = mw.v_dt(data, "onboarding_end_date")
    planned_rate = mw.v_num(data, "planned_standard_rate_usd", minimum=0,
                            exclusive_min=True)
    cross_sell_target = mw.v_int(data, "cross_sell_target_count", minimum=0,
                                 maximum=50)

    if user_id != candidate["target_practice_group_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if group["id"] != candidate["target_practice_group_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if candidate["pipeline_status"] != "HIRED":
        raise ApiError("ERR_CANDIDATE_INVALID_STATE")
    if offer["status"] != "ACCEPTED":
        raise ApiError("ERR_OFFER_INVALID_STATE")
    if candidate["earliest_start_date"] is not None and \
            start < candidate["earliest_start_date"]:
        raise ApiError("ERR_NOTICE_PERIOD_NOT_ELAPSED")
    if offer["candidate_id"] != candidate["id"]:
        raise ApiError("ERR_OFFER_CANDIDATE_MISMATCH")
    if end <= start:
        raise ApiError("ERR_LOOKBACK_WINDOW_INVALID")

    row = new_row({
        "candidate_id": candidate["id"],
        "practice_group_id": group["id"],
        "offer_id": offer["id"],
        "onboarding_start_date": start,
        "onboarding_end_date": end,
        "planned_standard_rate_usd": planned_rate,
        "cross_sell_target_count": cross_sell_target,
        "status": "DRAFT",
        "introduction_count": 0,
        "completed_introduction_count": 0,
    })
    db.integration_plans[row["id"]] = row
    return object_response(pub(row), 201)


@bp.get("/integration-plans/<plan_id>")
def read_plan(plan_id):
    mw.authenticate(READ_PLAN)
    return object_response(pub(lk.get_plan(plan_id)))


@bp.get("/integration-plans")
def list_plans():
    mw.authenticate(LIST_PLAN)
    rows = list(db.integration_plans.values())
    rows = listing.eq_filter(rows, "candidate_id")
    rows = listing.eq_filter(rows, "practice_group_id")
    rows = listing.eq_filter(rows, "offer_id")
    rows = listing.eq_filter(rows, "status")
    return listing.paged(rows)


@bp.post("/integration-plans/<plan_id>/abandon")
def abandon_plan(plan_id):
    user_id, _role = mw.authenticate(("PracticeGroupLeader",))
    plan = lk.get_plan(plan_id)
    data = mw.body()
    mw.v_str(data, "abandonment_reason", 1, 500)
    if user_id != plan["practice_group_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INTEGRATION_PLAN_INVALID_STATE")
    cascades.close_plan(plan, "ABANDONED")
    return object_response(pub(plan))


@bp.post("/integration-plans/<plan_id>/activate")
def activate_plan(plan_id):
    user_id, _role = mw.authenticate(("PracticeGroupLeader",))
    plan = lk.get_plan(plan_id)
    if user_id != plan["practice_group_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INTEGRATION_PLAN_INVALID_STATE")
    group = db.practice_groups.get(plan["practice_group_id"])
    if group is None or group["status"] != "OPEN":
        raise ApiError("ERR_PRACTICE_GROUP_FROZEN")
    if group["active_onboarding_count"] >= group["onboarding_capacity"]:
        raise ApiError("ERR_ONBOARDING_CAPACITY_REACHED")
    set_fields(plan, status="ACTIVE")
    svc.sync_group_onboarding(group)
    return object_response(pub(plan))


# ------------------------------------------------------------- introductions

def _closed_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.post("/integration-plans/<plan_id>/introductions")
def create_introduction(plan_id):
    user_id, _role = mw.authenticate(("PracticeGroupLeader",))
    plan = lk.get_plan(plan_id)
    data = mw.body()
    target_client_name = mw.v_str(data, "target_client_name", 1, 120)
    introducing_partner_name = mw.v_str(data, "introducing_partner_name", 1, 120)
    slot_start = mw.v_dt(data, "slot_start_at")
    slot_end = mw.v_dt(data, "slot_end_at")

    if user_id != plan["practice_group_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INTEGRATION_PLAN_INVALID_STATE")
    candidate = db.candidates.get(plan["candidate_id"])
    if candidate is None or candidate["pipeline_status"] != "HIRED":
        raise ApiError("ERR_CANDIDATE_INVALID_STATE")

    # Priority 12 -- prior-firm restrictions.
    if candidate["resignation_date"] is not None:
        bar_end = candidate["resignation_date"] + \
            timedelta(days=candidate["non_solicit_days"])
        if slot_start < bar_end:
            raise ApiError("ERR_NON_SOLICIT_RESTRICTION")
    if candidate["approach_confidential"]:
        for questionnaire in lk.questionnaires_of_candidate(candidate["id"]):
            for entry in lk.entries_of_questionnaire(questionnaire["id"],
                                                     active_only=True):
                if entry["client_consent_status"] == "CONSENT_PENDING" and \
                        entry["client_name"] == target_client_name:
                    raise ApiError("ERR_CONFIDENTIAL_APPROACH_RESTRICTION")

    # Priority 19 -- slot geometry, closed at both ends.
    if slot_start < plan["onboarding_start_date"] or \
            slot_end > plan["onboarding_end_date"]:
        raise ApiError("ERR_INTRODUCTION_OUTSIDE_WINDOW")
    for other in lk.introductions_of_plan(plan["id"]):
        if other["status"] not in ("PROPOSED", "COMPLETED"):
            continue
        if _closed_overlap(slot_start, slot_end, other["slot_start_at"],
                           other["slot_end_at"]):
            raise ApiError("ERR_INTRODUCTION_SLOT_CONFLICT")

    # Priority 20 -- window sanity.
    if slot_end <= slot_start:
        raise ApiError("ERR_LOOKBACK_WINDOW_INVALID")

    row = new_row({
        "integration_plan_id": plan["id"],
        "target_client_name": target_client_name,
        "introducing_partner_name": introducing_partner_name,
        "slot_start_at": slot_start,
        "slot_end_at": slot_end,
        "status": "PROPOSED",
        "completed_at": None,
    })
    db.introductions[row["id"]] = row
    svc.sync_plan_counters(plan)
    return object_response(pub(row), 201)


@bp.get("/introductions/<introduction_id>")
def read_introduction(introduction_id):
    mw.authenticate(LIST_PLAN)
    return object_response(pub(lk.get_introduction(introduction_id)))


@bp.get("/introductions")
def list_introductions():
    mw.authenticate(LIST_PLAN)
    rows = list(db.introductions.values())
    rows = listing.eq_filter(rows, "integration_plan_id")
    rows = listing.eq_filter(rows, "status")
    return listing.paged(rows)


@bp.post("/introductions/<introduction_id>/complete")
def complete_introduction(introduction_id):
    user_id, _role = mw.authenticate(("PracticeGroupLeader",))
    introduction = lk.get_introduction(introduction_id)
    plan = lk.get_plan(introduction["integration_plan_id"])
    if user_id != plan["practice_group_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if introduction["status"] != "PROPOSED":
        raise ApiError("ERR_INTRODUCTION_INVALID_STATE")
    if db.clock < introduction["slot_start_at"]:
        raise ApiError("ERR_INTRODUCTION_INVALID_STATE",
                       "The slot has not started yet.")
    set_fields(introduction, status="COMPLETED", completed_at=db.clock)
    svc.sync_plan_counters(plan)
    return object_response(pub(introduction))


# -------------------------------------------------------- performance reviews

@bp.post("/candidates/<candidate_id>/performance-reviews")
def create_review(candidate_id):
    user_id, _role = mw.authenticate(("PracticeGroupLeader",))
    candidate = lk.get_candidate(candidate_id)
    data = mw.body()
    plan = None
    if isinstance(data.get("integration_plan_id"), str):
        plan = lk.get_plan(data["integration_plan_id"])

    mw.v_str(data, "integration_plan_id", 1, None)
    period_start = mw.v_dt(data, "period_start_date")
    period_end = mw.v_dt(data, "period_end_date")
    variance_basis = mw.v_enum(data, "variance_basis",
                               ("PLAN_BASIS", "RATE_ADJUSTED_BASIS"))
    realized_rate = mw.v_num(data, "realized_standard_rate_usd", minimum=0,
                             exclusive_min=True)

    if user_id != plan["practice_group_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if candidate["pipeline_status"] != "HIRED":
        raise ApiError("ERR_CANDIDATE_INVALID_STATE")
    if period_end <= period_start:
        raise ApiError("ERR_LOOKBACK_WINDOW_INVALID")

    period_days = (period_end.date() - period_start.date()).days + 1
    actual = calc.ZERO
    for record in lk.records_of_candidate(candidate["id"]):
        if record["record_type"] != "POST_HIRE" or record["status"] != "VERIFIED":
            continue
        if period_start <= record["period_end_date"] <= period_end:
            actual += record["amount_usd"]
    actual = calc.r2(actual)

    offer = db.offers.get(plan["offer_id"])
    contribution = offer["expected_contribution_usd"] if offer is not None \
        else calc.ZERO
    plan_target = calc.r2(contribution * calc.D(period_days) / calc.DAYS_PER_YEAR)
    plan_target_adjusted = calc.r2(
        plan_target * realized_rate / plan["planned_standard_rate_usd"])
    if variance_basis == "PLAN_BASIS":
        variance = calc.r2(actual - plan_target)
    else:
        variance = calc.r2(actual - plan_target_adjusted)
    if plan_target == 0:
        attainment = calc.ZERO4
    else:
        attainment = calc.r4(actual / plan_target)

    credits = 0
    for intro in lk.introductions_of_plan(plan["id"]):
        if intro["status"] == "COMPLETED" and intro["completed_at"] is not None \
                and intro["completed_at"] <= period_end:
            credits += 1

    row = new_row({
        "candidate_id": candidate["id"],
        "integration_plan_id": plan["id"],
        "period_start_date": period_start,
        "period_end_date": period_end,
        "period_days": period_days,
        "variance_basis": variance_basis,
        "realized_standard_rate_usd": realized_rate,
        "actual_collections_usd": actual,
        "plan_target_usd": plan_target,
        "plan_target_adjusted_usd": plan_target_adjusted,
        "variance_usd": variance,
        "attainment_pct": attainment,
        "cross_sell_credit_count": credits,
        "performance_flag": calc.performance_flag(attainment),
    })
    db.performance_reviews[row["id"]] = row
    return object_response(pub(row), 201)


@bp.get("/performance-reviews/<review_id>")
def read_review(review_id):
    mw.authenticate(READ_PLAN)
    return object_response(pub(lk.get_review(review_id)))


@bp.get("/performance-reviews")
def list_reviews():
    mw.authenticate(LIST_PLAN)
    rows = list(db.performance_reviews.values())
    rows = listing.eq_filter(rows, "candidate_id")
    rows = listing.eq_filter(rows, "integration_plan_id")
    rows = listing.eq_filter(rows, "performance_flag")
    return listing.paged(rows)
