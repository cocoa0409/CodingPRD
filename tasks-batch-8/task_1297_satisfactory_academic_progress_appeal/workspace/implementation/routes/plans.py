"""AcademicPlan endpoints: create, read, list, revise.

Creation guards run in the global order: existence (student, appeal,
start term, checkpoint terms left to right), plan admissibility, coverage
exclusivity, credit balance, checkpoint term validity, and finally body
well-formedness.
"""

from flask import Blueprint, g, request

import errors
from db import _new_id, now, store
from middleware import (
    authenticate,
    check_student_ownership,
    get_body,
    paginate,
    pagination_params,
    require_roles,
)
from response import success
from serializers import pub_checkpoint, pub_plan, pub_student
from services import audit
from services.metrics import to_decimal

bp = Blueprint("plans", __name__)

ANY_ROLE = ("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _coverage_overlaps(student_id, start_seq, end_seq):
    """Half-open [start, end) intersection with any other plan of the student
    (any status); strict adjacency is allowed."""
    for p in store.plans.values():
        if p["student_id"] != student_id:
            continue
        if start_seq < p["coverage_end_seq_exclusive"] and p["coverage_start_seq"] < end_seq:
            return True
    return False


def _check_contiguity(start_term, checkpoint_terms):
    """Checkpoint seqs must be contiguous starting at start_term.seq."""
    seqs = sorted(t["seq"] for t in checkpoint_terms)
    expected = list(range(start_term["seq"], start_term["seq"] + len(seqs)))
    return seqs == expected


def _validate_checkpoint_bodies(checkpoints):
    if not isinstance(checkpoints, list):
        errors.fail(errors.ERR_INVALID_REQUEST, "checkpoints must be an array")
    for cp in checkpoints:
        if not isinstance(cp, dict):
            errors.fail(errors.ERR_INVALID_REQUEST, "each checkpoint must be an object")
        if not isinstance(cp.get("term_id"), str):
            errors.fail(errors.ERR_INVALID_REQUEST, "checkpoint term_id is required")
        if not _is_num(cp.get("required_term_gpa")):
            errors.fail(errors.ERR_INVALID_REQUEST, "required_term_gpa must be a number")
        if not _is_num(cp.get("required_term_pace_pct")):
            errors.fail(errors.ERR_INVALID_REQUEST, "required_term_pace_pct must be a number")
        if not _is_int(cp.get("required_earned_credits")):
            errors.fail(errors.ERR_INVALID_REQUEST, "required_earned_credits must be an integer")


def _credit_sum(checkpoints):
    total = 0
    for cp in checkpoints:
        if isinstance(cp, dict) and _is_int(cp.get("required_earned_credits")):
            total += cp["required_earned_credits"]
        else:
            return None
    return total


def _make_checkpoint(plan_id, cp_body):
    ts = now()
    row = {
        "id": _new_id(),
        "plan_id": plan_id,
        "term_id": cp_body["term_id"],
        "required_term_gpa": to_decimal(cp_body["required_term_gpa"]),
        "required_term_pace_pct": to_decimal(cp_body["required_term_pace_pct"]),
        "required_earned_credits": cp_body["required_earned_credits"],
        "actual_term_gpa": None,
        "actual_term_pace_pct": None,
        "actual_earned_credits": None,
        "outcome": "PENDING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.checkpoints[row["id"]] = row
    return row


@bp.post("/sap/plans")
def create_plan():
    authenticate()
    require_roles("AidOfficer")
    body = get_body()

    # Existence, left to right: student_id, appeal_id, start_term_id, then the
    # term identifiers inside the checkpoint list in order.
    student_id = body.get("student_id")
    student = None
    if student_id is not None:
        student = store.students.get(student_id)
        if student is None:
            errors.fail(errors.ERR_NOT_FOUND, "Student %s does not exist" % student_id)
    appeal_id = body.get("appeal_id")
    appeal = None
    if appeal_id is not None:
        appeal = store.appeals.get(appeal_id)
        if appeal is None:
            errors.fail(errors.ERR_NOT_FOUND, "Appeal %s does not exist" % appeal_id)
    start_term_id = body.get("start_term_id")
    start_term = None
    if start_term_id is not None:
        start_term = store.terms.get(start_term_id)
        if start_term is None:
            errors.fail(errors.ERR_NOT_FOUND, "Term %s does not exist" % start_term_id)
    checkpoints = body.get("checkpoints")
    checkpoint_terms = []
    checkpoints_resolvable = isinstance(checkpoints, list)
    if isinstance(checkpoints, list):
        for cp in checkpoints:
            term_id = cp.get("term_id") if isinstance(cp, dict) else None
            if term_id is None:
                checkpoints_resolvable = False
                continue
            term = store.terms.get(term_id)
            if term is None:
                errors.fail(errors.ERR_NOT_FOUND, "Term %s does not exist" % term_id)
            checkpoint_terms.append(term)

    # Plan admissibility (12): the appeal must be an APPROVED WITH_PLAN appeal
    # of this student, who must currently await the plan.
    if student is not None and appeal is not None:
        if (appeal["status"] != "APPROVED"
                or appeal["resolution"] != "WITH_PLAN"
                or appeal["student_id"] != student["id"]
                or student["sap_status"] != "PLAN_PENDING"):
            errors.fail(errors.ERR_PLAN_NOT_ALLOWED,
                        "Plan creation requires an APPROVED WITH_PLAN appeal and "
                        "standing PLAN_PENDING")

    # Coverage exclusivity (16): half-open interval against every other plan
    # of the same student.
    if start_term is not None and isinstance(checkpoints, list) and checkpoints_resolvable:
        cov_start = start_term["seq"]
        cov_end = (max(t["seq"] for t in checkpoint_terms) + 1) if checkpoint_terms else cov_start
        if student is not None and _coverage_overlaps(student["id"], cov_start, cov_end):
            errors.fail(errors.ERR_PLAN_TERM_OVERLAP,
                        "Plan coverage intersects another plan of the same student")

    # Credit balance (17).
    total_required = body.get("total_required_credits")
    if isinstance(checkpoints, list) and _is_int(total_required):
        summed = _credit_sum(checkpoints)
        if summed is not None and summed != total_required:
            errors.fail(errors.ERR_PLAN_CREDIT_MISMATCH,
                        "Checkpoint credits do not sum to total_required_credits")

    # Checkpoint term validity (18): start strictly after the suspension term,
    # contiguous seqs from the start term.
    if (start_term is not None and appeal is not None
            and isinstance(checkpoints, list) and checkpoints_resolvable):
        evaluation = store.evaluations.get(appeal["sap_evaluation_id"])
        suspension_term = store.terms.get(evaluation["term_id"]) if evaluation else None
        if suspension_term is not None and start_term["seq"] <= suspension_term["seq"]:
            errors.fail(errors.ERR_CHECKPOINT_TERM_INVALID,
                        "Plan start term must follow the suspension term")
        if not _check_contiguity(start_term, checkpoint_terms):
            errors.fail(errors.ERR_CHECKPOINT_TERM_INVALID,
                        "Checkpoint terms must be contiguous from the start term")

    # Body well-formedness (22), last.
    if not isinstance(student_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "student_id is required")
    if not isinstance(appeal_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "appeal_id is required")
    if not isinstance(start_term_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "start_term_id is required")
    if not _is_int(total_required):
        errors.fail(errors.ERR_INVALID_REQUEST, "total_required_credits must be an integer")
    _validate_checkpoint_bodies(checkpoints)

    ts = now()
    cov_start = start_term["seq"]
    cov_end = (max(t["seq"] for t in checkpoint_terms) + 1) if checkpoint_terms else cov_start
    plan = {
        "id": _new_id(),
        "student_id": student_id,
        "appeal_id": appeal_id,
        "start_term_id": start_term_id,
        "total_required_credits": total_required,
        "coverage_start_seq": cov_start,
        "coverage_end_seq_exclusive": cov_end,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.plans[plan["id"]] = plan
    for cp in checkpoints:
        _make_checkpoint(plan["id"], cp)

    # PLAN_PENDING -> PLAN_ACTIVE on plan creation.
    student_before = pub_student(student)
    student["sap_status"] = "PLAN_ACTIVE"
    student["updated_at"] = ts
    student["version"] += 1

    audit.record("PLAN_CREATED", "AcademicPlan", plan["id"], student_id, None, pub_plan(plan))
    audit.record("STANDING_CHANGED", "Student", student["id"], student["id"],
                 student_before, pub_student(student))
    return success(pub_plan(plan), status=201)


@bp.get("/sap/plans/<pid>")
def get_plan(pid):
    authenticate()
    require_roles(*ANY_ROLE)
    row = store.plans.get(pid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "AcademicPlan %s does not exist" % pid)
    check_student_ownership(row["student_id"])
    return success(pub_plan(row))


@bp.get("/sap/plans")
def list_plans():
    authenticate()
    require_roles(*ANY_ROLE)
    limit, offset = pagination_params()
    rows = list(store.plans.values())
    if g.user_role == "Student":
        rows = [p for p in rows if p["student_id"] == g.user_id]
    student_id = request.args.get("student_id")
    if student_id is not None:
        rows = [p for p in rows if p["student_id"] == student_id]
    appeal_id = request.args.get("appeal_id")
    if appeal_id is not None:
        rows = [p for p in rows if p["appeal_id"] == appeal_id]
    start_term_id = request.args.get("start_term_id")
    if start_term_id is not None:
        rows = [p for p in rows if p["start_term_id"] == start_term_id]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, meta = paginate(rows, limit, offset)
    return success([pub_plan(p) for p in page], response_type="array", pagination=meta)


@bp.post("/sap/plans/<pid>/revise")
def revise_plan(pid):
    authenticate()
    require_roles("AidOfficer")
    plan = store.plans.get(pid)
    if plan is None:
        errors.fail(errors.ERR_NOT_FOUND, "AcademicPlan %s does not exist" % pid)
    body = get_body()
    checkpoints = body.get("checkpoints")

    # Existence of the replacement checkpoint term ids, in order.
    checkpoint_terms = []
    resolvable = isinstance(checkpoints, list)
    if isinstance(checkpoints, list):
        for cp in checkpoints:
            term_id = cp.get("term_id") if isinstance(cp, dict) else None
            if term_id is None:
                resolvable = False
                continue
            term = store.terms.get(term_id)
            if term is None:
                errors.fail(errors.ERR_NOT_FOUND, "Term %s does not exist" % term_id)
            checkpoint_terms.append(term)

    # From-state: the plan must be ACTIVE with every checkpoint still PENDING.
    existing = [c for c in store.checkpoints.values() if c["plan_id"] == plan["id"]]
    if plan["status"] != "ACTIVE" or any(c["outcome"] != "PENDING" for c in existing):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only an ACTIVE plan with all checkpoints PENDING can be revised")

    # Credit balance against the unchanged budget.
    if isinstance(checkpoints, list):
        summed = _credit_sum(checkpoints)
        if summed is not None and summed != plan["total_required_credits"]:
            errors.fail(errors.ERR_PLAN_CREDIT_MISMATCH,
                        "Checkpoint credits do not sum to total_required_credits")

    # Checkpoint term validity against the plan's (unchanged) start term.
    start_term = store.terms.get(plan["start_term_id"])
    if start_term is not None and isinstance(checkpoints, list) and resolvable:
        appeal = store.appeals.get(plan["appeal_id"])
        evaluation = store.evaluations.get(appeal["sap_evaluation_id"]) if appeal else None
        suspension_term = store.terms.get(evaluation["term_id"]) if evaluation else None
        if suspension_term is not None and start_term["seq"] <= suspension_term["seq"]:
            errors.fail(errors.ERR_CHECKPOINT_TERM_INVALID,
                        "Plan start term must follow the suspension term")
        if not _check_contiguity(start_term, checkpoint_terms):
            errors.fail(errors.ERR_CHECKPOINT_TERM_INVALID,
                        "Checkpoint terms must be contiguous from the start term")

    _validate_checkpoint_bodies(checkpoints)

    before = pub_plan(plan)
    for c in existing:
        del store.checkpoints[c["id"]]
    for cp in checkpoints:
        _make_checkpoint(plan["id"], cp)
    if start_term is not None:
        plan["coverage_start_seq"] = start_term["seq"]
        plan["coverage_end_seq_exclusive"] = (
            max(t["seq"] for t in checkpoint_terms) + 1
            if checkpoint_terms else start_term["seq"]
        )
    plan["updated_at"] = now()
    plan["version"] += 1
    audit.record("PLAN_REVISED", "AcademicPlan", plan["id"], plan["student_id"],
                 before, pub_plan(plan))
    return success(pub_plan(plan))
