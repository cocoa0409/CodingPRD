"""Record books: ledgering, submission, and review (PRD 3.5; OCC per PRD 2.7)."""

from flask import Blueprint

import clock
import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        require_member_ownership, new_common_fields, touch)
from validation import (get_body, as_int, as_num_range, pagination_params,
                        paginate, sort_by_creation, present)
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_SCREENING_NOT_CLEARED)
from services import calc
from services.serialize import record_book_view, ledger_entry_view

bp = Blueprint("record_books", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Member"]


def _book_owner(book):
    project = db.table("projects").get(book["project_id"])
    if project is None:
        return None
    return db.table("members").get(project["member_id"])


@bp.post("/record-books")
def create_record_book():
    role, user_id = authenticate(["Member"])
    body = get_body()
    # Priority 3: referenced identifiers exist (project_id).
    project = None
    if isinstance(body.get("project_id"), str):
        project = must_find("projects", body["project_id"], "Project")
    resolve_caller(role, user_id)
    # Priority 4: the member opens a book on their own project only.
    if project is not None:
        require_member_ownership(user_id, project["member_id"])
    # Priority 14: request shape.
    project_id = present(body, "project_id")
    if not isinstance(project_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'project_id': must be a string")
    if project is None:
        project = must_find("projects", project_id, "Project")
    program_year = as_int(body, "program_year")
    rec = new_common_fields()
    rec.update({
        "project_id": project["id"],
        "program_year": program_year,
        "status": "DRAFT",
        "submitted_at": None,
        "provisional_score": None,
        "final_score": None,
        "late_days": 0,
        # Section scores from the most recent submission payload; retained so
        # the final score starts from the same weighted sum at approval time.
        "_sections": None,
    })
    db.table("record_books")[rec["id"]] = rec
    return response.success(record_book_view(rec), status=201)


@bp.get("/record-books/<rid>")
def get_record_book(rid):
    role, user_id = authenticate(ALL_ROLES)
    rec = must_find("record_books", rid, "RecordBook")
    resolve_caller(role, user_id)
    return response.success(record_book_view(rec))


@bp.get("/record-books/<rid>/ledger-entries")
def list_record_book_ledger_entries(rid):
    role, user_id = authenticate(ALL_ROLES)
    book = must_find("record_books", rid, "RecordBook")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [e for e in db.table("ledger_entries").values()
         if e["record_book_id"] == book["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([ledger_entry_view(e) for e in page],
                            response_type="array", pagination=meta)


@bp.post("/record-books/<rid>/submit")
def submit_record_book(rid):
    role, user_id = authenticate(["Member"])
    rec = must_find("record_books", rid, "RecordBook")
    resolve_caller(role, user_id)
    project = db.table("projects").get(rec["project_id"])
    if project is not None:
        require_member_ownership(user_id, project["member_id"])
    # Priority 5: state preconditions.
    #   DRAFT -> SUBMITTED requires at least one POSTED ledger line and an
    #   ACTIVE project; RETURNED -> SUBMITTED requires an ACTIVE project.
    if rec["status"] == "DRAFT":
        has_posted = any(e["record_book_id"] == rec["id"] and e["entry_status"] == "POSTED"
                         for e in db.table("ledger_entries").values())
        if not has_posted:
            raise ApiError(ERR_INVALID_STATE, 409,
                           "First submission requires at least one POSTED ledger entry")
        if project is None or project["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Submission requires the project to be ACTIVE")
    elif rec["status"] == "RETURNED":
        if project is None or project["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Resubmission requires the project to be ACTIVE")
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Record book status must be DRAFT or RETURNED to submit")
    # Priority 14: request shape -- OCC field plus the four section scores,
    # each from 0 to 100.
    body = get_body()
    expected_version = as_int(body, "expected_record_book_version")
    completeness = as_num_range(body, "completeness", lo=0, hi=100)
    accuracy = as_num_range(body, "accuracy", lo=0, hi=100)
    financial = as_num_range(body, "financial", lo=0, hi=100)
    reflection = as_num_range(body, "reflection", lo=0, hi=100)
    # Priority 15: optimistic concurrency -- always the final gate.
    if expected_version != rec["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_record_book_version does not match the record book's current version")
    rec["status"] = "SUBMITTED"
    submitted_dt = clock.now()
    rec["submitted_at"] = clock.iso3(submitted_dt)
    rec["late_days"] = calc.record_book_late_days(submitted_dt)
    rec["provisional_score"] = float(calc.record_book_provisional_score(
        completeness, accuracy, financial, reflection))
    rec["_sections"] = {
        "completeness": completeness,
        "accuracy": accuracy,
        "financial": financial,
        "reflection": reflection,
    }
    touch(rec)
    return response.success(record_book_view(rec))


@bp.post("/record-books/<rid>/begin-review")
def begin_review(rid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("record_books", rid, "RecordBook")
    resolve_caller(role, user_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Record book status must be SUBMITTED to begin review")
    # Priority 6: segregation of duties -- the acting volunteer must not be the
    # parent or guardian of the member who owns the book. The data model
    # carries no parent/guardian linkage field on either Member or Volunteer,
    # so no caller can ever be identified as the parent/guardian; the check is
    # structurally inert and the transition proceeds.
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return response.success(record_book_view(rec))


@bp.post("/record-books/<rid>/return")
def return_record_book(rid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("record_books", rid, "RecordBook")
    resolve_caller(role, user_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Record book status must be UNDER_REVIEW to return")
    rec["status"] = "RETURNED"
    touch(rec)
    return response.success(record_book_view(rec))


@bp.post("/record-books/<rid>/approve")
def approve_record_book(rid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("record_books", rid, "RecordBook")
    caller = resolve_caller(role, user_id)
    # Priority 5: state precondition.
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Record book status must be UNDER_REVIEW to approve")
    # Priority 7: only a volunteer whose screening_status is CLEARED may
    # approve a record book.
    if caller["screening_status"] != "CLEARED":
        raise ApiError(ERR_SCREENING_NOT_CLEARED, 422,
                       "Approving a record book requires screening_status CLEARED")
    # Final score: same weighted sum, then leadership bonus capped at 100,
    # then late penalty floored at 0 (pinned order, PRD 3.5).
    sections = rec["_sections"] or {}
    weighted = calc.record_book_weighted_sum(
        sections.get("completeness", 0), sections.get("accuracy", 0),
        sections.get("financial", 0), sections.get("reflection", 0))
    member = _book_owner(rec)
    is_officer = bool(member["is_club_officer"]) if member is not None else False
    rec["final_score"] = float(calc.record_book_final_score(weighted, is_officer, rec["late_days"]))
    rec["status"] = "APPROVED"
    touch(rec)
    if member is not None:
        calc.recompute_member_posture(member)
    return response.success(record_book_view(rec))


@bp.post("/record-books/<rid>/reject")
def reject_record_book(rid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("record_books", rid, "RecordBook")
    resolve_caller(role, user_id)
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Record book status must be UNDER_REVIEW to reject")
    rec["status"] = "REJECTED"
    touch(rec)
    return response.success(record_book_view(rec))
