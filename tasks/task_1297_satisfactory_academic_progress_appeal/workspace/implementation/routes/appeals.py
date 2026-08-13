"""Appeal endpoints: submit (with OCC + supersede), read, list, screen,
request-info, resubmit, and committee decide.

Guard ordering follows the global validation ladder: authentication,
authorization, existence, ownership, stale-version, from-state, the specific
state/business guards in priority order, and body well-formedness last.
"""

from flask import Blueprint, g, request

import errors
from db import _new_id, now, store, trunc_second
from middleware import (
    authenticate,
    caller_student,
    check_student_ownership,
    get_body,
    paginate,
    pagination_params,
    require_roles,
)
from response import success
from serializers import pub_appeal, pub_notification, pub_student
from services import audit
from services.pipeline import queue_notification

bp = Blueprint("appeals", __name__)

ANY_ROLE = ("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")
REASON_CATEGORIES = ("MEDICAL", "FAMILY_EMERGENCY", "MILITARY", "OTHER")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _docs_well_formed(documents):
    return (
        isinstance(documents, list)
        and all(isinstance(d, dict)
                and isinstance(d.get("doc_type"), str)
                and isinstance(d.get("description"), str)
                for d in documents)
    )


@bp.post("/sap/appeals")
def create_appeal():
    authenticate()
    require_roles("Student")
    body = get_body()

    # Existence, left to right: the caller's student record, then the cited evaluation.
    student = caller_student()
    eval_id = body.get("sap_evaluation_id")
    evaluation = None
    if eval_id is not None:
        evaluation = store.evaluations.get(eval_id)
        if evaluation is None:
            errors.fail(errors.ERR_NOT_FOUND, "SapEvaluation %s does not exist" % eval_id)

    # Stale-version guard (OCC) runs before any standing/window/docs question.
    expected = body.get("expected_student_version")
    if _is_int(expected) and expected != student["version"]:
        errors.fail(errors.ERR_STALE_VERSION,
                    "expected_student_version does not match the student's current version")

    # Suspension precondition, then review exclusivity.
    if student["sap_status"] != "SUSPENSION":
        errors.fail(errors.ERR_STUDENT_NOT_SUSPENDED,
                    "Appeal submission requires current standing SUSPENSION")
    for a in store.appeals.values():
        if a["student_id"] == student["id"] and a["status"] == "UNDER_REVIEW":
            errors.fail(errors.ERR_APPEAL_UNDER_REVIEW,
                        "An appeal is already under committee review")

    # Appeal window (deadline inclusive), then documentation, then referential
    # integrity of the cited evaluation — in that pinned order.
    if evaluation is not None:
        if trunc_second(now()) > trunc_second(evaluation["appeal_deadline_at"]):
            errors.fail(errors.ERR_APPEAL_WINDOW_CLOSED,
                        "The appeal deadline of the referenced evaluation has passed")

    documents = body.get("documents")
    if isinstance(documents, list) and len(documents) == 0:
        errors.fail(errors.ERR_APPEAL_DOCS_REQUIRED,
                    "An appeal must carry at least one document")

    if evaluation is not None:
        if (evaluation["status"] != "OFFICIAL"
                or evaluation["student_id"] != student["id"]
                or evaluation["result_standing"] != "SUSPENSION"):
            errors.fail(errors.ERR_EVALUATION_MISMATCH,
                        "sap_evaluation_id must reference the caller's OFFICIAL "
                        "suspension evaluation")

    # Body well-formedness, deliberately last.
    if not isinstance(eval_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "sap_evaluation_id is required")
    reason_category = body.get("reason_category")
    if reason_category not in REASON_CATEGORIES:
        errors.fail(errors.ERR_INVALID_REQUEST, "reason_category is invalid")
    statement = body.get("statement")
    if not isinstance(statement, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "statement is required")
    if not _docs_well_formed(documents):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "documents must be an array of {doc_type, description}")
    if not _is_int(expected):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "expected_student_version is required and must be an integer")

    ts = now()
    row = {
        "id": _new_id(),
        "student_id": student["id"],
        "sap_evaluation_id": eval_id,
        "reason_category": reason_category,
        "statement": statement,
        "documents": [dict(d) for d in documents],
        "status": "SUBMITTED",
        "resolution": None,
        "rationale": None,
        "submitted_at": ts,
        "decided_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.appeals[row["id"]] = row

    # Submission increments the student's version by exactly one.
    student["updated_at"] = ts
    student["version"] += 1

    # Retire the student's older unfinished appeal(s).
    superseded = []
    for a in store.appeals.values():
        if (a["id"] != row["id"] and a["student_id"] == student["id"]
                and a["status"] in ("SUBMITTED", "MORE_INFO_REQUESTED")):
            before = pub_appeal(a)
            a["status"] = "SUPERSEDED"
            a["updated_at"] = ts
            a["version"] += 1
            superseded.append((before, a))

    audit.record("APPEAL_SUBMITTED", "Appeal", row["id"], student["id"], None, pub_appeal(row))
    for before, a in superseded:
        audit.record("APPEAL_SUPERSEDED", "Appeal", a["id"], student["id"], before, pub_appeal(a))

    return success(pub_appeal(row), status=201)


@bp.get("/sap/appeals/<aid>")
def get_appeal(aid):
    authenticate()
    require_roles(*ANY_ROLE)
    row = store.appeals.get(aid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Appeal %s does not exist" % aid)
    check_student_ownership(row["student_id"])
    return success(pub_appeal(row))


@bp.get("/sap/appeals")
def list_appeals():
    authenticate()
    require_roles(*ANY_ROLE)
    limit, offset = pagination_params()
    rows = list(store.appeals.values())
    if g.user_role == "Student":
        rows = [a for a in rows if a["student_id"] == g.user_id]
    student_id = request.args.get("student_id")
    if student_id is not None:
        rows = [a for a in rows if a["student_id"] == student_id]
    eval_id = request.args.get("sap_evaluation_id")
    if eval_id is not None:
        rows = [a for a in rows if a["sap_evaluation_id"] == eval_id]
    status = request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page, meta = paginate(rows, limit, offset)
    return success([pub_appeal(a) for a in page], response_type="array", pagination=meta)


@bp.post("/sap/appeals/<aid>/screen")
def screen_appeal(aid):
    authenticate()
    require_roles("AidOfficer")
    row = store.appeals.get(aid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Appeal %s does not exist" % aid)
    if row["status"] != "SUBMITTED":
        errors.fail(errors.ERR_INVALID_STATE, "Only a SUBMITTED appeal can be screened")
    before = pub_appeal(row)
    row["status"] = "UNDER_REVIEW"
    row["updated_at"] = now()
    row["version"] += 1
    audit.record("APPEAL_SCREENED", "Appeal", row["id"], row["student_id"], before, pub_appeal(row))
    return success(pub_appeal(row))


@bp.post("/sap/appeals/<aid>/request-info")
def request_info(aid):
    authenticate()
    require_roles("AidOfficer")
    row = store.appeals.get(aid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Appeal %s does not exist" % aid)
    if row["status"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only an UNDER_REVIEW appeal can receive an info request")
    body = get_body()
    note = body.get("info_request_note")
    if not isinstance(note, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "info_request_note is required")
    before = pub_appeal(row)
    row["status"] = "MORE_INFO_REQUESTED"
    row["rationale"] = note
    row["updated_at"] = now()
    row["version"] += 1
    audit.record("APPEAL_INFO_REQUESTED", "Appeal", row["id"], row["student_id"],
                 before, pub_appeal(row))
    return success(pub_appeal(row))


@bp.post("/sap/appeals/<aid>/resubmit")
def resubmit_appeal(aid):
    authenticate()
    require_roles("Student")
    row = store.appeals.get(aid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Appeal %s does not exist" % aid)
    # Ownership is screened before the from-state check.
    check_student_ownership(row["student_id"])
    if row["status"] != "MORE_INFO_REQUESTED":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only a MORE_INFO_REQUESTED appeal can be resubmitted")
    body = get_body()
    documents = body.get("documents")
    if isinstance(documents, list) and len(documents) == 0:
        errors.fail(errors.ERR_APPEAL_DOCS_REQUIRED,
                    "A resubmission must carry at least one document")
    if not _docs_well_formed(documents):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "documents must be an array of {doc_type, description}")
    statement = body.get("statement")
    if statement is not None and not isinstance(statement, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "statement must be a string")

    before = pub_appeal(row)
    row["documents"] = row["documents"] + [dict(d) for d in documents]
    if statement is not None:
        row["statement"] = statement
    row["status"] = "SUBMITTED"
    row["updated_at"] = now()
    row["version"] += 1
    audit.record("APPEAL_RESUBMITTED", "Appeal", row["id"], row["student_id"],
                 before, pub_appeal(row))
    return success(pub_appeal(row))


@bp.post("/sap/appeals/<aid>/decide")
def decide_appeal(aid):
    authenticate()
    require_roles("CommitteeMember")
    row = store.appeals.get(aid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Appeal %s does not exist" % aid)
    # Terminal outcomes reject as invalid state; pre-review states as
    # decision-requires-review.
    if row["status"] in ("APPROVED", "DENIED", "SUPERSEDED"):
        errors.fail(errors.ERR_INVALID_STATE, "The appeal has already reached a terminal state")
    if row["status"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_DECISION_REQUIRES_REVIEW,
                    "A decision requires the appeal to be UNDER_REVIEW")

    body = get_body()
    decision = body.get("decision")
    if decision not in ("APPROVED", "DENIED"):
        errors.fail(errors.ERR_INVALID_REQUEST, "decision must be APPROVED or DENIED")
    rationale = body.get("rationale")
    if not isinstance(rationale, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "rationale is required")
    resolution = body.get("resolution")
    if decision == "APPROVED":
        if resolution not in ("WITH_PLAN", "PROBATION_ONLY"):
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "An approval must name its resolution (WITH_PLAN or PROBATION_ONLY)")

    ts = now()
    before = pub_appeal(row)
    row["status"] = decision
    row["decided_at"] = ts
    row["rationale"] = rationale
    if decision == "APPROVED":
        row["resolution"] = resolution
    row["updated_at"] = ts
    row["version"] += 1

    # Standing cascade: WITH_PLAN -> PLAN_PENDING; PROBATION_ONLY -> PROBATION;
    # DENIED changes nothing.
    student = store.students.get(row["student_id"])
    student_before = None
    standing_changed = False
    if decision == "APPROVED" and student is not None and student["sap_status"] == "SUSPENSION":
        student_before = pub_student(student)
        student["sap_status"] = "PLAN_PENDING" if resolution == "WITH_PLAN" else "PROBATION"
        student["updated_at"] = ts
        student["version"] += 1
        standing_changed = True

    notice = queue_notification(
        row["student_id"],
        "APPEAL_DECISION",
        "Appeal decided: %s" % decision,
        ts,
    )

    audit.record("APPEAL_DECIDED", "Appeal", row["id"], row["student_id"], before, pub_appeal(row))
    if standing_changed:
        audit.record("STANDING_CHANGED", "Student", student["id"], student["id"],
                     student_before, pub_student(student))
    audit.record("NOTIFICATION_QUEUED", "Notification", notice["id"], row["student_id"],
                 None, pub_notification(notice))
    return success(pub_appeal(row))
