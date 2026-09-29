"""Program outcome reviews and improvement plans (PRD 3.8)."""

from flask import Blueprint, g

import calc
import domain
import serialize
from db import db, new_entity, now, touch
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from response import list_response, object_response
from routes.programs import find_program
from validation import (
    get_body,
    opt_str,
    pagination,
    q_enum,
    q_str,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("reviews", __name__)

SUPERSEDABLE_PLAN_STATUSES = ("SUBMITTED", "REJECTED")


def find_review(review_id):
    row = db.reviews.get(review_id)
    if row is None:
        raise ApiError(
            "ERR_REVIEW_NOT_FOUND", "no ProgramOutcomeReview with id %s" % review_id
        )
    return row


def find_plan(plan_id):
    row = db.plans.get(plan_id)
    if row is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "no ImprovementPlan with id %s" % plan_id)
    return row


# --------------------------------------------------------------------------- #
# outcome reviews
# --------------------------------------------------------------------------- #


@bp.post("/outcome-reviews")
def create_review():
    authenticate(["QualityOfficer"])
    body = get_body()
    program_id = req_str(body, "program_id")
    period_start_on = req_date(body, "period_start_on")
    period_end_on = req_date(body, "period_end_on")
    if period_end_on < period_start_on:
        raise ApiError("ERR_VALIDATION", "period_end_on may not precede period_start_on")
    cohort_size = req_int(body, "cohort_size", minimum=0)
    observed_survivor_count = req_int(body, "observed_survivor_count", minimum=0)
    if observed_survivor_count > cohort_size:
        raise ApiError(
            "ERR_VALIDATION", "observed_survivor_count may not exceed cohort_size"
        )

    program = find_program(program_id)

    # priority 15 -- single-program containment
    domain.require_same_program(
        [program["id"], g.staff["program_id"] if g.staff is not None else None]
    )

    rate = program["expected_one_year_survival_rate"]
    expected_count, oe_ratio, flag_level, requires_plan = calc.outcome_metrics(
        cohort_size, observed_survivor_count, rate
    )

    row = new_entity(
        "ProgramOutcomeReview",
        {
            "program_id": program["id"],
            "period_start_on": period_start_on.isoformat(),
            "period_end_on": period_end_on.isoformat(),
            "cohort_size": cohort_size,
            "observed_survivor_count": observed_survivor_count,
            "expected_survival_rate_used": rate,
            "expected_survivor_count": expected_count,
            "oe_ratio": oe_ratio,
            "flag_level": flag_level,
            "requires_improvement_plan": requires_plan,
            "status": "DRAFT",
            "finalized_at": None,
        },
    )
    db.reviews[row["id"]] = row
    return object_response(serialize.outcome_review(row), 201)


@bp.post("/outcome-reviews/<review_id>/finalization")
def finalize_review(review_id):
    authenticate(["QualityOfficer"])
    review = find_review(review_id)
    get_body()

    # priority 8 -- FINALIZED is terminal
    if review["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a review in %s may not be finalized" % review["status"],
        )

    program = domain.program_of_review(review)

    # priority 17 -- one FINALIZED review per period pair per program
    for other in domain.reviews_of_program(program):
        if other["id"] == review["id"] or other["status"] != "FINALIZED":
            continue
        if (
            other["period_start_on"] == review["period_start_on"]
            and other["period_end_on"] == review["period_end_on"]
        ):
            raise ApiError(
                "ERR_DUPLICATE_REVIEW_PERIOD",
                "the program already holds a FINALIZED review for this period",
            )

    review["status"] = "FINALIZED"
    review["finalized_at"] = now()
    touch(review)

    domain.refresh_posture(program)
    return object_response(serialize.outcome_review(review))


@bp.get("/outcome-reviews")
def list_reviews():
    authenticate(ALL_ROLES)
    program_id = q_str("program_id")
    flag_level = q_enum("flag_level", calc.FLAG_LEVELS)
    status = q_enum("status", calc.REVIEW_STATUSES)
    limit, offset = pagination()

    rows = list(db.reviews.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if flag_level is not None:
        rows = [r for r in rows if r["flag_level"] == flag_level]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.outcome_review(r) for r in page], limit, offset, total)


@bp.get("/outcome-reviews/<review_id>")
def get_review(review_id):
    authenticate(ALL_ROLES)
    review = find_review(review_id)
    return object_response(serialize.outcome_review(review))


@bp.get("/outcome-reviews/<review_id>/improvement-plans")
def list_review_plans(review_id):
    authenticate(ALL_ROLES)
    review = find_review(review_id)
    status = q_enum("status", calc.PLAN_STATUSES)
    limit, offset = pagination()

    rows = domain.plans_of_review(review)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.improvement_plan(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# improvement plans
# --------------------------------------------------------------------------- #


@bp.post("/improvement-plans")
def create_plan():
    authenticate(["QualityOfficer"])
    body = get_body()
    review_id = req_str(body, "program_outcome_review_id")
    expected_review_version = req_int(body, "expected_review_version", minimum=0)
    title = req_str(body, "title")
    milestone_count = req_int(body, "milestone_count", minimum=1)
    target_completion_on = req_date(body, "target_completion_on")

    # priority 5
    review = find_review(review_id)

    # priority 6 -- optimistic concurrency on the parent review
    if expected_review_version != review["version"]:
        raise ApiError(
            "ERR_STALE_REVIEW_VERSION",
            "expected_review_version %s does not match the review's current version %s"
            % (expected_review_version, review["version"]),
        )

    # priority 15 -- single-program containment
    program = domain.program_of_review(review)
    domain.require_same_program(
        [program["id"], g.staff["program_id"] if g.staff is not None else None]
    )

    # priority 23 -- only a WATCH or FLAGGED review asked for a plan
    if review["flag_level"] not in ("WATCH", "FLAGGED"):
        raise ApiError(
            "ERR_PLAN_NOT_REQUIRED",
            "the parent review's flag_level is %s" % review["flag_level"],
        )

    for existing in domain.plans_of_review(review):
        if existing["status"] in SUPERSEDABLE_PLAN_STATUSES:
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = new_entity(
        "ImprovementPlan",
        {
            "program_outcome_review_id": review["id"],
            "title": title,
            "milestone_count": milestone_count,
            "target_completion_on": target_completion_on.isoformat(),
            "status": "SUBMITTED",
            "decision_reason_code": None,
            "decided_at": None,
            "closed_at": None,
        },
    )
    db.plans[row["id"]] = row

    # the parent review moved, so a competing writer's version is now stale
    touch(review)
    return object_response(serialize.improvement_plan(row), 201)


@bp.post("/improvement-plans/<plan_id>/transitions")
def transition_plan(plan_id):
    authenticate(["ProgramAdmin"])
    plan = find_plan(plan_id)

    body = get_body()
    action = req_enum(body, "action", calc.PLAN_ACTIONS)
    decision_reason_code = opt_str(body, "decision_reason_code")
    if action in ("ACCEPT", "REJECT") and decision_reason_code is None:
        raise ApiError("ERR_VALIDATION", "decision_reason_code is required for a decision")

    # priority 8
    allowed_from = {"ACCEPT": "SUBMITTED", "REJECT": "SUBMITTED", "CLOSE": "ACCEPTED"}
    if plan["status"] != allowed_from[action]:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a plan in %s does not accept the %s action" % (plan["status"], action),
        )

    review = db.reviews[plan["program_outcome_review_id"]]

    # priority 9
    if review["status"] != "FINALIZED":
        raise ApiError(
            "ERR_REVIEW_NOT_FINALIZED", "the plan's parent review is not FINALIZED"
        )

    clock = now()
    if action == "ACCEPT":
        plan["status"] = "ACCEPTED"
        plan["decided_at"] = clock
        plan["decision_reason_code"] = decision_reason_code
    elif action == "REJECT":
        plan["status"] = "REJECTED"
        plan["decided_at"] = clock
        plan["decision_reason_code"] = decision_reason_code
    else:
        plan["status"] = "CLOSED"
        plan["closed_at"] = clock
    touch(plan)

    domain.refresh_posture(domain.program_of_review(review))
    return object_response(serialize.improvement_plan(plan))
