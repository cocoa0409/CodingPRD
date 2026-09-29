"""Assessor assignments, rubric scores and scoring completion."""
from flask import Blueprint, request

from db import (assignments_of_claim, db, new_row, order_rows,
                outcomes_of_course, portfolio_of_claim, scores_of_assignment)
from errors import ApiError
from middleware import (ROLE_ASSESSOR, ROLE_COORDINATOR, ROLE_REGISTRAR,
                        ROLE_REVIEWER, ROLE_STUDENT, authenticate,
                        find_or_404, scoped_assignment)
from response import created, ok, ok_list, read_pagination
from serializers import assignment_out, rubric_score_out
from services.coverage import (assignment_verified_coverage, mastery_threshold,
                               pass_threshold, score_ratio_bp)
from services.selection import (assignment_window, create_assignment,
                                create_replacement, eligible_pool, resolve_named)
from services.sla import freeze_posture, refresh_posture
from util import (RUBRIC_MAX_POINTS, TERMINAL_ASSESSMENT_STATES, as_enum,
                  as_id, as_int, as_str, dtv, json_body, present, put_dt,
                  require, touch)

bp = Blueprint("assignments", __name__)

READ_ROLES = [ROLE_COORDINATOR, ROLE_REGISTRAR, ROLE_ASSESSOR, ROLE_REVIEWER]
SCORE_READ_ROLES = [ROLE_COORDINATOR, ROLE_ASSESSOR, ROLE_REVIEWER, ROLE_STUDENT]


# ---------------------------------------------------------------- creation
@bp.post("/pla-claims/<claim_id>/assessor-assignments")
def create_claim_assignment(claim_id):
    authenticate([ROLE_COORDINATOR])
    claim = find_or_404("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body = json_body()
    named = None
    if present(body, "assessor_id") and isinstance(body["assessor_id"], str):
        named = db.assessors.get(body["assessor_id"])
        if named is None:
            raise ApiError("ERR_ASSESSOR_NOT_FOUND")
    if present(body, "assessor_id"):
        as_id(body["assessor_id"], "assessor_id")
    # rung 14
    if claim["assessment_status"] in TERMINAL_ASSESSMENT_STATES:
        raise ApiError("ERR_CLAIM_ALREADY_TERMINAL")
    # rung 15a
    if claim["assessment_status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED")

    course = db.courses.get(claim["course_id"])
    window = assignment_window(claim, db.clock)
    if named is not None:
        # rungs 31 and 32, with the failure modes distinguished
        chosen = resolve_named(named, course, claim, (window[0], window[1]))
        reason = "EXPLICIT"
    else:
        pool = eligible_pool(course, claim, (window[0], window[1]))
        if not pool:
            raise ApiError("ERR_NO_ELIGIBLE_ASSESSOR")
        chosen = pool[0]
        reason = "AUTO_SELECTED"
    # rung 42: the fiscal gate sits at the bottom of the ladder
    if claim["fee_status"] not in ("PAID", "WAIVED"):
        raise ApiError("ERR_ASSESSMENT_FEE_UNPAID")

    assignment = create_assignment(claim, chosen, reason)
    return created(assignment_out(assignment))


# ---------------------------------------------------------------- reads
@bp.get("/assessor-assignments/<assignment_id>")
def read_assignment(assignment_id):
    authenticate(READ_ROLES)
    assignment = find_or_404("assignments", assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    return ok(assignment_out(assignment))


@bp.get("/assessor-assignments")
def list_assignments():
    authenticate(READ_ROLES)
    limit, offset = read_pagination()
    rows = list(db.assignments.values())
    for row in rows:
        refresh_posture(row)
    for name in ("claim_id", "assessor_id", "status", "sla_state"):
        wanted = request.args.get(name)
        if wanted is not None and wanted != "":
            rows = [r for r in rows if r.get(name) == wanted]
    rows = order_rows(rows, [(lambda r: dtv(r, "assigned_at"), False)])
    return ok_list(rows, assignment_out, limit, offset)


# ---------------------------------------------------------------- accept / decline
@bp.post("/assessor-assignments/<assignment_id>/accept")
def accept_assignment(assignment_id):
    ctx = authenticate([ROLE_ASSESSOR])
    assignment = scoped_assignment(ctx, assignment_id)
    # rung 17
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_NOT_PENDING")
    assessor = db.assessors.get(assignment["assessor_id"])
    if assessor is None or assessor["status"] != "ACTIVE":
        raise ApiError("ERR_ASSESSOR_INACTIVE")

    assignment["status"] = "ACCEPTED"
    put_dt(assignment, "accepted_at", db.clock)
    refresh_posture(assignment)
    touch(assignment)
    return ok(assignment_out(assignment))


@bp.post("/assessor-assignments/<assignment_id>/decline")
def decline_assignment(assignment_id):
    ctx = authenticate([ROLE_ASSESSOR])
    assignment = scoped_assignment(ctx, assignment_id)
    body = json_body()
    decline_reason = as_str(require(body, "decline_reason"), "decline_reason", 1)
    # rung 17
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_NOT_PENDING")

    claim = db.claims.get(assignment["claim_id"])
    assessor = db.assessors.get(assignment["assessor_id"])
    freeze_posture(assignment)
    assignment["status"] = "DECLINED"
    assignment["decline_reason"] = decline_reason
    touch(assignment)
    if assessor is not None:
        assessor["active_assignment_count"] = max(0, assessor["active_assignment_count"] - 1)
        touch(assessor)
    if claim is not None:
        create_replacement(claim)
    return ok(assignment_out(assignment))


# ---------------------------------------------------------------- rubric scores
@bp.post("/assessor-assignments/<assignment_id>/rubric-scores")
def create_rubric_score(assignment_id):
    ctx = authenticate([ROLE_ASSESSOR])
    assignment = scoped_assignment(ctx, assignment_id)
    body = json_body()
    outcome = None
    if present(body, "learning_outcome_id") and isinstance(body["learning_outcome_id"], str):
        outcome = db.outcomes.get(body["learning_outcome_id"])
        if outcome is None:
            raise ApiError("ERR_OUTCOME_NOT_FOUND")
    as_id(require(body, "learning_outcome_id"), "learning_outcome_id")
    points = as_int(require(body, "points_awarded"), "points_awarded")
    narrative = None
    if present(body, "narrative"):
        narrative = as_str(body["narrative"], "narrative", 1)
    # rung 11
    if points < 0 or points > RUBRIC_MAX_POINTS:
        raise ApiError("ERR_RUBRIC_POINTS_OUT_OF_RANGE")
    # rung 17
    if assignment["status"] != "ACCEPTED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACCEPTED")
    claim = db.claims.get(assignment["claim_id"])
    # rung 23
    if claim is None or outcome["course_id"] != claim["course_id"]:
        raise ApiError("ERR_OUTCOME_NOT_IN_COURSE")
    # rung 30b
    for existing in scores_of_assignment(assignment["id"]):
        if existing["learning_outcome_id"] == outcome["id"]:
            raise ApiError("ERR_DUPLICATE_RUBRIC_SCORE")

    ratio = score_ratio_bp(points)
    score = new_row("RubricScore")
    score["assignment_id"] = assignment["id"]
    score["learning_outcome_id"] = outcome["id"]
    score["points_awarded"] = points
    score["points_possible"] = RUBRIC_MAX_POINTS
    score["score_ratio_bp"] = ratio
    score["outcome_met"] = ratio >= mastery_threshold(outcome)
    score["narrative"] = narrative
    db.rubric_scores[score["id"]] = score
    return created(rubric_score_out(score))


@bp.get("/rubric-scores/<score_id>")
def read_rubric_score(score_id):
    authenticate(SCORE_READ_ROLES)
    score = find_or_404("rubric_scores", score_id, "ERR_RUBRIC_SCORE_NOT_FOUND")
    return ok(rubric_score_out(score))


@bp.get("/rubric-scores")
def list_rubric_scores():
    authenticate(SCORE_READ_ROLES)
    limit, offset = read_pagination()
    rows = list(db.rubric_scores.values())
    for name in ("assignment_id", "learning_outcome_id"):
        wanted = request.args.get(name)
        if wanted is not None and wanted != "":
            rows = [r for r in rows if r.get(name) == wanted]
    rows = order_rows(rows, [(lambda r: r["created_at"], False)])
    return ok_list(rows, rubric_score_out, limit, offset)


# ---------------------------------------------------------------- completion
@bp.post("/assessor-assignments/<assignment_id>/complete")
def complete_assignment(assignment_id):
    ctx = authenticate([ROLE_ASSESSOR])
    assignment = scoped_assignment(ctx, assignment_id)
    body = json_body()
    submitted = as_enum(require(body, "recommendation"), "recommendation", ["PASS", "FAIL"])
    # rung 17
    if assignment["status"] != "ACCEPTED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACCEPTED")

    claim = db.claims.get(assignment["claim_id"])
    course = db.courses.get(claim["course_id"]) if claim is not None else None
    student = db.students.get(claim["student_id"]) if claim is not None else None
    program = db.programs.get(student["program_id"]) if student is not None else None
    outcomes = outcomes_of_course(course["id"]) if course is not None else []
    scored_ids = set(s["learning_outcome_id"] for s in scores_of_assignment(assignment["id"]))
    # rung 36
    if not outcomes or any(o["id"] not in scored_ids for o in outcomes):
        raise ApiError("ERR_INCOMPLETE_RUBRIC")
    verified = assignment_verified_coverage(assignment, course)
    computed = "PASS" if verified >= pass_threshold(program) else "FAIL"
    if submitted != computed:
        raise ApiError("ERR_RECOMMENDATION_INCONSISTENT")

    freeze_posture(assignment)
    assignment["status"] = "SCORING_COMPLETE"
    put_dt(assignment, "rubric_submitted_at", db.clock)
    assignment["verified_coverage_bp"] = verified
    assignment["recommendation"] = computed
    touch(assignment)
    assessor = db.assessors.get(assignment["assessor_id"])
    if assessor is not None:
        assessor["active_assignment_count"] = max(0, assessor["active_assignment_count"] - 1)
        touch(assessor)
    claim["verified_coverage_bp"] = verified
    claim["assessor_recommendation"] = computed
    claim["assessment_status"] = "SCORED"
    touch(claim)
    portfolio = portfolio_of_claim(claim["id"])
    if portfolio is not None and portfolio["status"] == "SUBMITTED":
        portfolio["status"] = "LOCKED"
        portfolio["verified_coverage_bp"] = verified
        touch(portfolio)
    return ok(assignment_out(assignment))
