from datetime import timedelta

from flask import Blueprint, request

import errors as E
import response
from db import store, new_record, touch, serialize, now, parse_dt
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response
from services.domain import leave_decision_cascade

bp = Blueprint("assessments", __name__)

ASSESSMENT_READ_ROLES = ["BITChair", "CounselingEvaluator", "DeanOfStudents", "CaseManager"]


@bp.post("/bit/mandated-assessments")
def create_assessment():
    uid, _ = require_auth(["BITChair"])
    b = body()
    case_id = b.get("case_id")
    evaluator_id = b.get("evaluator_id")
    case = None
    if isinstance(case_id, str):
        case = store.cases.get(case_id)
        if case is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"care case not found: {case_id}")
    evaluator = None
    if isinstance(evaluator_id, str):
        evaluator = store.staff.get(evaluator_id)
        if evaluator is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"staff member not found: {evaluator_id}")

    # Rank 5: state.
    if case is not None and case["status"] != "PLAN_ACTIVE":
        raise ApiError(
            E.ERR_CASE_NOT_PLAN_ACTIVE, 409, "assessment order requires case PLAN_ACTIVE"
        )

    # Rank 9: required fields, then evaluator/orderer distinctness.
    if case is None:
        raise ApiError(E.ERR_VALIDATION, 400, "case_id is required")
    if evaluator is None:
        raise ApiError(E.ERR_VALIDATION, 400, "evaluator_id is required")
    due_at = parse_dt(b.get("due_at"))
    if due_at is None:
        raise ApiError(E.ERR_VALIDATION, 400, "due_at must be an ISO 8601 UTC timestamp")
    rationale = b.get("rationale")
    if not isinstance(rationale, str) or not rationale:
        raise ApiError(E.ERR_VALIDATION, 400, "rationale is required")
    if evaluator_id == uid:
        raise ApiError(
            E.ERR_EVALUATOR_SAME_AS_ORDERER,
            400,
            "evaluator_id must differ from the ordering BITChair",
        )

    # Rank 10: temporal windows — due window, then slot occupation.
    n = now()
    if not (due_at > n and due_at <= n + timedelta(days=14)):
        raise ApiError(
            E.ERR_ASSESSMENT_DUE_WINDOW_VIOLATION,
            422,
            "due_at must be > now and <= now + 14 days",
        )
    for a in store.assessments.values():
        if (
            a["case_id"] == case["id"]
            and a["status"] == "SCHEDULED"
            and a["created_at"] <= n <= a["due_at"]
        ):
            raise ApiError(
                E.ERR_ASSESSMENT_ALREADY_PENDING,
                409,
                "a SCHEDULED assessment already occupies the case slot",
            )

    rec = new_record()
    rec.update(
        {
            "case_id": case["id"],
            "ordered_by": uid,
            "evaluator_id": evaluator_id,
            "due_at": due_at,
            "rationale": rationale,
            "outcome": None,
            "findings_summary": None,
            "completed_at": None,
            "status": "SCHEDULED",
        }
    )
    store.assessments[rec["id"]] = rec
    case["status"] = "MANDATED_ASSESSMENT"
    touch(case)
    return response.obj(serialize(rec), 201)


@bp.get("/bit/mandated-assessments/<aid>")
def get_assessment(aid):
    require_auth(ASSESSMENT_READ_ROLES)
    rec = get_or_404(store.assessments, aid, "mandated assessment")
    return response.obj(serialize(rec))


@bp.get("/bit/mandated-assessments")
def list_assessments():
    require_auth(ASSESSMENT_READ_ROLES)
    q = request.args
    return list_response(
        store.assessments,
        [
            ("case_id", q.get("case_id")),
            ("ordered_by", q.get("ordered_by")),
            ("evaluator_id", q.get("evaluator_id")),
            ("status", q.get("status")),
        ],
    )


@bp.post("/bit/mandated-assessments/<aid>/record-outcome")
def record_outcome(aid):
    uid, _ = require_auth(["CounselingEvaluator"])
    rec = get_or_404(store.assessments, aid, "mandated assessment")
    case = store.cases.get(rec["case_id"])
    # Rank 5: assessment state, then case state.
    if rec["status"] != "SCHEDULED":
        raise ApiError(
            E.ERR_ASSESSMENT_NOT_SCHEDULED, 409, "record-outcome requires assessment SCHEDULED"
        )
    if case is None or case["status"] != "MANDATED_ASSESSMENT":
        raise ApiError(
            E.ERR_CASE_NOT_MANDATED_ASSESSMENT,
            409,
            "record-outcome requires the case in MANDATED_ASSESSMENT",
        )
    # Rank 7: doubly segregated — assigned evaluator and not the orderer.
    if uid != rec["evaluator_id"] or uid == rec["ordered_by"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES,
            403,
            "outcome recorder must be the assigned evaluator and differ from the orderer",
        )
    # Rank 9: field validity.
    b = body()
    outcome = b.get("outcome")
    if outcome not in ("CLEARED", "NOT_CLEARED"):
        raise ApiError(E.ERR_VALIDATION, 400, "outcome must be CLEARED or NOT_CLEARED")
    findings_summary = b.get("findings_summary")
    if not isinstance(findings_summary, str) or not findings_summary:
        raise ApiError(E.ERR_VALIDATION, 400, "findings_summary is required")

    rec["outcome"] = outcome
    rec["findings_summary"] = findings_summary
    rec["completed_at"] = now()
    rec["status"] = "COMPLETED"
    touch(rec)

    if outcome == "CLEARED":
        case["status"] = "PLAN_ACTIVE"
        touch(case)
    else:
        # NOT_CLEARED: four-link cascade (assessment completed above is link 1).
        leave_decision_cascade(rec)
    return response.obj(serialize(rec))
