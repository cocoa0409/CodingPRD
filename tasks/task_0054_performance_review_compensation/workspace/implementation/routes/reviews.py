"""Review, Goal, FeedbackRequest routes + composite score calculation."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_RATING_BAND_UNKNOWN,
    ERR_SEGREGATION_OF_DUTIES, ERR_GOAL_WEIGHTS_INVALID, ERR_VALIDATION,
    ERR_FORBIDDEN_ROLE,
)
from middleware import get_caller, require_role
from response import ok_object, ok_array
from services.common import (
    init_common, touch, public, paginate, get_body, require_fields,
    as_number, as_str,
)
from routes.cycles import bands_for_cycle

bp = Blueprint("reviews", __name__)

GOAL_WEIGHT = Decimal("0.70")
FEEDBACK_WEIGHT = Decimal("0.30")


def review_view(r):
    return public(r)


def goal_view(g):
    return public(g)


def feedback_view(f):
    return public(f)


def _band_labels(cycle_id):
    return set(b["label"] for b in bands_for_cycle(cycle_id))


# ---------------- Review CRUD ----------------

@bp.route("/reviews", methods=["POST"])
def create_review():
    _, role = get_caller()
    require_role(role, {"HrAdmin", "Manager"})
    body = get_body()
    require_fields(body, ["cycle_id", "employee_id", "reviewer_id", "base_salary"])
    cycle_id = body["cycle_id"]
    if cycle_id not in db.cycles:
        raise err(ERR_NOT_FOUND, "cycle_id not found")
    if body["employee_id"] not in db.employees:
        raise err(ERR_NOT_FOUND, "employee_id not found")
    if body["reviewer_id"] not in db.employees:
        raise err(ERR_NOT_FOUND, "reviewer_id not found")
    base_salary = as_number(body["base_salary"], "base_salary")
    if base_salary <= 0:
        raise err(ERR_VALIDATION, "base_salary must be > 0")

    r = {
        "cycle_id": cycle_id,
        "employee_id": body["employee_id"],
        "reviewer_id": body["reviewer_id"],
        "base_salary": base_salary,
        "self_rating": None,
        "manager_rating": None,
        "final_rating": None,
        "status": "DRAFT",
        "composite_score": None,
    }
    init_common(r)
    db.reviews[r["id"]] = r
    return ok_object(review_view(r), 201)


@bp.route("/reviews/<rid>", methods=["GET"])
def get_review(rid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover", "Manager", "Employee"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    return ok_object(review_view(r))


@bp.route("/reviews", methods=["GET"])
def list_reviews():
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover", "Manager"})
    cycle_id = request.args.get("cycle_id")
    employee_id = request.args.get("employee_id")
    reviewer_id = request.args.get("reviewer_id")
    status = request.args.get("status")
    items = [
        r for r in db.reviews.values()
        if (cycle_id is None or r["cycle_id"] == cycle_id)
        and (employee_id is None or r["employee_id"] == employee_id)
        and (reviewer_id is None or r["reviewer_id"] == reviewer_id)
        and (status is None or r["status"] == status)
    ]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([review_view(r) for r in page], limit, offset, total, has_more)


@bp.route("/reviews/<rid>", methods=["PATCH"])
def patch_review(rid):
    user_id, role = get_caller()
    require_role(role, {"Manager", "Employee"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    body = get_body()
    labels = _band_labels(r["cycle_id"])
    changed = False
    if "self_rating" in body and body["self_rating"] is not None:
        if role != "Employee":
            raise err(ERR_FORBIDDEN_ROLE, "Only the employee may set self_rating")
        if body["self_rating"] not in labels:
            raise err(ERR_RATING_BAND_UNKNOWN, "self_rating not a known band label")
        r["self_rating"] = body["self_rating"]
        changed = True
    if "manager_rating" in body and body["manager_rating"] is not None:
        if role != "Manager":
            raise err(ERR_FORBIDDEN_ROLE, "Only the manager may set manager_rating")
        if body["manager_rating"] not in labels:
            raise err(ERR_RATING_BAND_UNKNOWN, "manager_rating not a known band label")
        r["manager_rating"] = body["manager_rating"]
        changed = True
    if changed:
        touch(r)
    return ok_object(review_view(r))


# ---------------- Review transitions ----------------

@bp.route("/reviews/<rid>/begin-self-review", methods=["POST"])
def begin_self_review(rid):
    user_id, role = get_caller()
    require_role(role, {"Employee"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    if r["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Review is not in DRAFT")
    cycle = db.cycles.get(r["cycle_id"])
    if not cycle or cycle["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Parent cycle must be OPEN")
    if user_id != r["employee_id"]:
        raise err(ERR_INVALID_STATE, "Acting employee must be the review subject")
    r["status"] = "SELF_REVIEW"
    touch(r)
    return ok_object(review_view(r))


@bp.route("/reviews/<rid>/submit-self", methods=["POST"])
def submit_self(rid):
    user_id, role = get_caller()
    require_role(role, {"Employee"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    if r["status"] != "SELF_REVIEW":
        raise err(ERR_INVALID_STATE, "Review is not in SELF_REVIEW")
    if user_id != r["employee_id"]:
        raise err(ERR_INVALID_STATE, "Acting employee must be the review subject")
    labels = _band_labels(r["cycle_id"])
    if not r["self_rating"]:
        raise err(ERR_RATING_BAND_UNKNOWN, "self_rating must be set")
    if r["self_rating"] not in labels:
        raise err(ERR_RATING_BAND_UNKNOWN, "self_rating not a known band label")
    r["status"] = "MANAGER_REVIEW"
    touch(r)
    return ok_object(review_view(r))


@bp.route("/reviews/<rid>/submit", methods=["POST"])
def submit_review(rid):
    user_id, role = get_caller()
    require_role(role, {"Manager"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    if r["status"] != "MANAGER_REVIEW":
        raise err(ERR_INVALID_STATE, "Review is not in MANAGER_REVIEW")
    if user_id != r["reviewer_id"]:
        raise err(ERR_INVALID_STATE, "Acting employee must be the reviewer")
    labels = _band_labels(r["cycle_id"])
    if not r["manager_rating"]:
        raise err(ERR_RATING_BAND_UNKNOWN, "manager_rating must be set")
    if r["manager_rating"] not in labels:
        raise err(ERR_RATING_BAND_UNKNOWN, "manager_rating not a known band label")
    goals = [g for g in db.goals.values() if g["review_id"] == rid]
    if len(goals) == 0:
        raise err(ERR_GOAL_WEIGHTS_INVALID, "Cannot submit a review with zero goals")
    if any(g["status"] != "SCORED" for g in goals):
        raise err(ERR_INVALID_STATE, "Every goal must be SCORED")
    weight_sum = sum(g["weight"] for g in goals)
    if not (0 < weight_sum <= 1):
        raise err(ERR_GOAL_WEIGHTS_INVALID, "Goal weight sum must be in (0,1]")
    r["composite_score"] = compute_composite_score(rid)
    r["status"] = "SUBMITTED"
    touch(r)
    return ok_object(review_view(r))


@bp.route("/reviews/<rid>/return", methods=["POST"])
def return_review(rid):
    user_id, role = get_caller()
    require_role(role, {"HrbpPartner"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    if r["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Review is not SUBMITTED")
    cycle = db.cycles.get(r["cycle_id"])
    if not cycle or cycle["status"] not in ("OPEN", "CALIBRATION"):
        raise err(ERR_INVALID_STATE, "Parent cycle must be OPEN or CALIBRATION")
    if user_id == r["reviewer_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Returner must not be the reviewer")
    r["status"] = "RETURNED"
    touch(r)
    return ok_object(review_view(r))


@bp.route("/reviews/<rid>/reopen", methods=["POST"])
def reopen_review(rid):
    user_id, role = get_caller()
    require_role(role, {"Manager"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    if r["status"] != "RETURNED":
        raise err(ERR_INVALID_STATE, "Review is not RETURNED")
    if user_id != r["reviewer_id"]:
        raise err(ERR_INVALID_STATE, "Acting employee must be the reviewer")
    r["status"] = "MANAGER_REVIEW"
    touch(r)
    return ok_object(review_view(r))


# ---------------- composite score ----------------

def compute_composite_score(review_id):
    goals = [g for g in db.goals.values() if g["review_id"] == review_id]
    weight_sum = sum(Decimal(str(g["weight"])) for g in goals)
    goal_raw = sum(
        Decimal(str(g["weight"])) * min(Decimal(str(g["attainment_pct"])), Decimal("1.0"))
        for g in goals
    )
    goal_score = (goal_raw / weight_sum) * Decimal("100")

    submitted = [f for f in db.feedback_requests.values()
                 if f["review_id"] == review_id and f["status"] == "SUBMITTED"]
    if len(submitted) == 0:
        feedback_score = goal_score
    else:
        avg5 = sum(Decimal(str(f["score"])) for f in submitted) / Decimal(len(submitted))
        feedback_score = (avg5 - Decimal("1")) / Decimal("4") * Decimal("100")

    composite = GOAL_WEIGHT * goal_score + FEEDBACK_WEIGHT * feedback_score
    return float(composite.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------- Goal ----------------

@bp.route("/reviews/<rid>/goals", methods=["POST"])
def add_goal(rid):
    _, role = get_caller()
    require_role(role, {"Manager", "Employee"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    body = get_body()
    require_fields(body, ["title", "weight"])
    title = as_str(body["title"], "title")
    if len(title) == 0:
        raise err(ERR_VALIDATION, "title must be non-empty")
    weight = as_number(body["weight"], "weight")
    if not (0 < weight <= 1):
        raise err(ERR_GOAL_WEIGHTS_INVALID, "weight must be in (0,1]")
    attainment = body.get("attainment_pct")
    if attainment is not None:
        attainment = as_number(attainment, "attainment_pct")
        if not (0 <= attainment <= 1.5):
            raise err(ERR_GOAL_WEIGHTS_INVALID, "attainment_pct must be in [0,1.5]")
    # The sum of a review's goal weights must lie in (0, 1]; the check is applied
    # both at submission and when adding a goal (PRD Section 3.3).
    existing_weight = sum(
        Decimal(str(g["weight"])) for g in db.goals.values()
        if g["review_id"] == rid
    )
    if existing_weight + Decimal(str(weight)) > Decimal("1"):
        raise err(ERR_GOAL_WEIGHTS_INVALID,
                  "sum of goal weights must be in (0,1]")

    g = {
        "review_id": rid,
        "title": title,
        "weight": weight,
        "attainment_pct": attainment,
        "status": "OPEN",
    }
    init_common(g)
    db.goals[g["id"]] = g
    return ok_object(goal_view(g), 201)


@bp.route("/reviews/<rid>/goals", methods=["GET"])
def list_goals(rid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "Manager", "Employee"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    items = [g for g in db.goals.values() if g["review_id"] == rid]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([goal_view(g) for g in page], limit, offset, total, has_more)


@bp.route("/goals/<gid>/score", methods=["POST"])
def score_goal(gid):
    _, role = get_caller()
    require_role(role, {"Manager"})
    g = db.goals.get(gid)
    if not g:
        raise err(ERR_NOT_FOUND, "Goal not found")
    if g["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Goal is not OPEN")
    body = get_body()
    require_fields(body, ["attainment_pct"])
    attainment = as_number(body["attainment_pct"], "attainment_pct")
    if not (0 <= attainment <= 1.5):
        raise err(ERR_GOAL_WEIGHTS_INVALID, "attainment_pct must be in [0,1.5]")
    g["attainment_pct"] = attainment
    g["status"] = "SCORED"
    touch(g)
    return ok_object(goal_view(g))


# ---------------- FeedbackRequest ----------------

@bp.route("/reviews/<rid>/feedback-requests", methods=["POST"])
def create_feedback(rid):
    _, role = get_caller()
    require_role(role, {"Manager", "HrbpPartner"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    body = get_body()
    require_fields(body, ["rater_id", "relationship"])
    if body["rater_id"] not in db.employees:
        raise err(ERR_NOT_FOUND, "rater_id not found")
    if body["relationship"] not in ("PEER", "REPORT", "MANAGER", "SELF"):
        raise err(ERR_VALIDATION, "relationship invalid")

    f = {
        "review_id": rid,
        "rater_id": body["rater_id"],
        "relationship": body["relationship"],
        "score": None,
        "status": "PENDING",
    }
    init_common(f)
    db.feedback_requests[f["id"]] = f
    return ok_object(feedback_view(f), 201)


@bp.route("/reviews/<rid>/feedback-requests", methods=["GET"])
def list_review_feedback(rid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "Manager"})
    r = db.reviews.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Review not found")
    items = [f for f in db.feedback_requests.values() if f["review_id"] == rid]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([feedback_view(f) for f in page], limit, offset, total, has_more)


@bp.route("/feedback-requests", methods=["GET"])
def list_feedback():
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "Manager", "Employee"})
    rater_id = request.args.get("rater_id")
    review_id = request.args.get("review_id")
    status = request.args.get("status")
    items = [
        f for f in db.feedback_requests.values()
        if (rater_id is None or f["rater_id"] == rater_id)
        and (review_id is None or f["review_id"] == review_id)
        and (status is None or f["status"] == status)
    ]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([feedback_view(f) for f in page], limit, offset, total, has_more)


@bp.route("/feedback-requests/<fid>", methods=["GET"])
def get_feedback(fid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "Manager", "Employee"})
    f = db.feedback_requests.get(fid)
    if not f:
        raise err(ERR_NOT_FOUND, "Feedback request not found")
    return ok_object(feedback_view(f))


@bp.route("/feedback-requests/<fid>/submit", methods=["POST"])
def submit_feedback(fid):
    _, role = get_caller()
    require_role(role, {"Employee"})
    f = db.feedback_requests.get(fid)
    if not f:
        raise err(ERR_NOT_FOUND, "Feedback request not found")
    if f["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Feedback request is not PENDING")
    body = get_body()
    require_fields(body, ["score"])
    score = as_number(body["score"], "score")
    if not (1 <= score <= 5):
        raise err(ERR_VALIDATION, "score must be in [1,5]")
    f["score"] = score
    f["status"] = "SUBMITTED"
    touch(f)
    return ok_object(feedback_view(f))


@bp.route("/feedback-requests/<fid>/decline", methods=["POST"])
def decline_feedback(fid):
    _, role = get_caller()
    require_role(role, {"Employee"})
    f = db.feedback_requests.get(fid)
    if not f:
        raise err(ERR_NOT_FOUND, "Feedback request not found")
    if f["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Feedback request is not PENDING")
    f["status"] = "DECLINED"
    touch(f)
    return ok_object(feedback_view(f))
