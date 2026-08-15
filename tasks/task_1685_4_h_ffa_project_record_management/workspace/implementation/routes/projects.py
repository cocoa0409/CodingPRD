"""Projects (PRD 3.4) and project nested collections."""

from flask import Blueprint

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        require_member_ownership, new_common_fields, touch)
from validation import (get_body, as_enum, as_int, pagination_params,
                        paginate, sort_by_creation, present)
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from services import calc
from services.serialize import project_view, animal_tag_view, record_book_view

bp = Blueprint("projects", __name__)

ALL_ROLES = ["ProgramAdmin", "Volunteer", "Member"]
PROJECT_TYPES = ("BEEF", "SHEEP", "SWINE", "CROPS", "FOODS", "ROBOTICS")
COMPLETION_GRADES = ("A", "B", "C")


@bp.post("/projects")
def create_project():
    role, user_id = authenticate(["Member", "Volunteer"])
    body = get_body()
    # Priority 3: referenced identifiers exist (member_id).
    member = None
    if isinstance(body.get("member_id"), str):
        member = must_find("members", body["member_id"], "Member")
    caller = resolve_caller(role, user_id)
    # Priority 4: a member may only create projects for their own membership.
    if role == "Member" and isinstance(body.get("member_id"), str):
        require_member_ownership(user_id, body["member_id"])
    # Priority 14: request shape.
    member_id = present(body, "member_id")
    if not isinstance(member_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'member_id': must be a string")
    if member is None:
        member = must_find("members", member_id, "Member")
    project_type = as_enum(body, "project_type", PROJECT_TYPES)
    program_year = as_int(body, "program_year")
    rec = new_common_fields()
    rec.update({
        "member_id": member["id"],
        "project_type": project_type,
        "program_year": program_year,
        "status": "PLANNED",
        "grade": "NONE",
    })
    db.table("projects")[rec["id"]] = rec
    return response.success(project_view(rec), status=201)


@bp.get("/projects/<pid>")
def get_project(pid):
    role, user_id = authenticate(ALL_ROLES)
    rec = must_find("projects", pid, "Project")
    resolve_caller(role, user_id)
    return response.success(project_view(rec))


@bp.post("/projects/<pid>/start")
def start_project(pid):
    role, user_id = authenticate(["Member"])
    rec = must_find("projects", pid, "Project")
    resolve_caller(role, user_id)
    require_member_ownership(user_id, rec["member_id"])
    # Priority 5: PLANNED -> ACTIVE, and the member must be ACTIVE.
    if rec["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Project status must be PLANNED to start")
    member = db.table("members").get(rec["member_id"])
    if member is None or member["enrollment_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Project can only start while the member is ACTIVE")
    rec["status"] = "ACTIVE"
    touch(rec)
    return response.success(project_view(rec))


@bp.post("/projects/<pid>/complete")
def complete_project(pid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("projects", pid, "Project")
    resolve_caller(role, user_id)
    # Priority 5: ACTIVE -> COMPLETED, backed by an APPROVED record book.
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Project status must be ACTIVE to complete")
    has_approved_book = any(
        rb["project_id"] == rec["id"] and rb["status"] == "APPROVED"
        for rb in db.table("record_books").values())
    if not has_approved_book:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Completion requires a record book in APPROVED status")
    # Priority 14: the volunteer supplies a grade of A, B, or C.
    body = get_body()
    grade = as_enum(body, "grade", COMPLETION_GRADES)
    rec["status"] = "COMPLETED"
    rec["grade"] = grade
    touch(rec)
    member = db.table("members").get(rec["member_id"])
    if member is not None:
        calc.recompute_member_posture(member)
    return response.success(project_view(rec))


@bp.post("/projects/<pid>/drop")
def drop_project(pid):
    role, user_id = authenticate(["Member"])
    rec = must_find("projects", pid, "Project")
    resolve_caller(role, user_id)
    require_member_ownership(user_id, rec["member_id"])
    # Priority 5: drop is available from PLANNED or from ACTIVE.
    if rec["status"] not in ("PLANNED", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Project status must be PLANNED or ACTIVE to drop")
    was_active = rec["status"] == "ACTIVE"
    rec["status"] = "DROPPED"
    touch(rec)
    # Dropping an ACTIVE project rejects its record book if that book is still
    # in flight; a book already APPROVED or REJECTED is untouched (PRD 3.4).
    if was_active:
        for rb in db.table("record_books").values():
            if (rb["project_id"] == rec["id"]
                    and rb["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED")):
                rb["status"] = "REJECTED"
                touch(rb)
    return response.success(project_view(rec))


@bp.get("/projects/<pid>/animal-tags")
def list_project_animal_tags(pid):
    role, user_id = authenticate(ALL_ROLES)
    project = must_find("projects", pid, "Project")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [t for t in db.table("animal_tags").values() if t["project_id"] == project["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([animal_tag_view(t) for t in page],
                            response_type="array", pagination=meta)


@bp.get("/projects/<pid>/record-books")
def list_project_record_books(pid):
    role, user_id = authenticate(ALL_ROLES)
    project = must_find("projects", pid, "Project")
    resolve_caller(role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(
        [rb for rb in db.table("record_books").values() if rb["project_id"] == project["id"]])
    page, meta = paginate(items, limit, offset)
    return response.success([record_book_view(rb) for rb in page],
                            response_type="array", pagination=meta)
