"""LadderPage routes: create, get, list, assign, submit-review, request-changes,
approve."""
from flask import Blueprint, request

from db import db, stamp_create, touch, sorted_by_created
from middleware import authenticate, authorize
from validators import (
    get_json_body, require, as_str, as_int, as_enum, parse_pagination, invalid,
)
from lookups import get_page_path, get_yearbook_path, get_ref
from response import success_object, success_array
import serializers as ser
from services.derive import (
    recompute_yearbook, recompute_assignment_page_count, recompute_page_counts,
)
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_PAGE_NUMBER_OUT_OF_BOUNDS,
    ERR_PAGE_NUMBER_CONFLICT, ERR_SUBMISSIONS_INCOMPLETE, ERR_PAGE_UNASSIGNED,
    ERR_PLANT_FROZEN, ERR_REFERENCE_NOT_FOUND,
)

bp = Blueprint("pages", __name__)

SECTIONS = {"STUDENT_LIFE", "ACADEMICS", "SPORTS", "CLUBS", "ADS", "SIGNATURE"}


def _occupied_range(page_number, spread_span):
    return set(range(page_number, page_number + spread_span))


@bp.route("/yearbooks/pages", methods=["POST"])
def create_page():
    _, role = authenticate()
    authorize(role, {"Adviser"})
    body = get_json_body()

    yearbook_id = as_str(require(body, "yearbook_id"), "yearbook_id")
    # body FK existence -> ERR_REFERENCE_NOT_FOUND (404)
    yb = get_ref(db.yearbooks, yearbook_id)

    page_number = as_int(require(body, "page_number"), "page_number")
    section = as_enum(require(body, "section"), "section", SECTIONS)
    template_code = as_str(require(body, "template_code"), "template_code")

    spread_span = body.get("spread_span", 1)
    if spread_span is None:
        spread_span = 1
    spread_span = as_int(spread_span, "spread_span")
    if spread_span not in (1, 2):
        invalid("spread_span must be 1 or 2")

    required_submission_count = body.get("required_submission_count", 1)
    if required_submission_count is None:
        required_submission_count = 1
    required_submission_count = as_int(required_submission_count, "required_submission_count")
    if required_submission_count < 0:
        invalid("required_submission_count must be >= 0")

    if page_number < 1:
        invalid("page_number must be >= 1")

    assigned_staff_id = body.get("assigned_staff_id")
    assignment = None
    if assigned_staff_id is not None:
        assigned_staff_id = as_str(assigned_staff_id, "assigned_staff_id")
        # body FK target existence -> ERR_REFERENCE_NOT_FOUND
        assignment = get_ref(db.staff_assignments, assigned_staff_id)

    # bounds (state-class 409) — occupied range within 1..target_page_count
    occupied = _occupied_range(page_number, spread_span)
    if max(occupied) > yb["target_page_count"]:
        raise ApiError(ERR_PAGE_NUMBER_OUT_OF_BOUNDS, 409,
                       "page spread exceeds the ladder bounds")

    # conflict — overlap with another page on the same yearbook
    for other in db.ladder_pages.values():
        if other["yearbook_id"] != yearbook_id:
            continue
        other_occ = _occupied_range(other["page_number"], other.get("spread_span", 1))
        if occupied & other_occ:
            raise ApiError(ERR_PAGE_NUMBER_CONFLICT, 409,
                           "page_number range overlaps an existing page")

    page = {
        "yearbook_id": yearbook_id,
        "page_number": page_number,
        "section": section,
        "template_code": template_code,
        "spread_span": spread_span,
        "assigned_staff_id": assigned_staff_id,
        "required_submission_count": required_submission_count,
        "approved_submission_count": 0,
        "status": "DRAFT",
    }
    stamp_create(page)
    db.ladder_pages[page["id"]] = page

    if assignment is not None:
        recompute_assignment_page_count(assignment)
    recompute_yearbook(yb)
    return success_object(ser.ladder_page(page), 201)


@bp.route("/yearbooks/pages/<page_id>", methods=["GET"])
def get_page(page_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff", "SalesRep", "Contributor"})
    page = get_page_path(page_id)
    return success_object(ser.ladder_page(page), 200)


@bp.route("/yearbooks/pages", methods=["GET"])
def list_pages():
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff", "SalesRep", "Contributor"})
    limit, offset = parse_pagination()
    yearbook_id = request.args.get("yearbook_id")
    assigned_staff_id = request.args.get("assigned_staff_id")
    records = list(db.ladder_pages.values())
    if yearbook_id is not None:
        records = [r for r in records if r["yearbook_id"] == yearbook_id]
    if assigned_staff_id is not None:
        records = [r for r in records if r.get("assigned_staff_id") == assigned_staff_id]
    records = sorted_by_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.ladder_page(r) for r in page], limit, offset, total, 200)


@bp.route("/yearbooks/pages/<page_id>/assign", methods=["POST"])
def assign_page(page_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    page = get_page_path(page_id)
    body = get_json_body()
    staff_assignment_id = as_str(require(body, "staff_assignment_id"), "staff_assignment_id")
    assignment = get_ref(db.staff_assignments, staff_assignment_id)

    prev_assignment_id = page.get("assigned_staff_id")
    page["assigned_staff_id"] = staff_assignment_id
    touch(page)

    recompute_assignment_page_count(assignment)
    if prev_assignment_id and prev_assignment_id != staff_assignment_id:
        prev = db.staff_assignments.get(prev_assignment_id)
        if prev is not None:
            recompute_assignment_page_count(prev)
    return success_object(ser.ladder_page(page), 200)


@bp.route("/yearbooks/pages/<page_id>/submit-review", methods=["POST"])
def submit_review(page_id):
    _, role = authenticate()
    authorize(role, {"Staff"})
    page = get_page_path(page_id)

    if page["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "page is not in a submittable state")

    # business rule: enough approved submissions
    if page["approved_submission_count"] < page["required_submission_count"]:
        raise ApiError(ERR_SUBMISSIONS_INCOMPLETE, 409,
                       "page lacks enough approved submissions")

    # On the very first submit out of DRAFT, page must have an ACTIVE assigned staff.
    if page["status"] == "DRAFT":
        assignment_id = page.get("assigned_staff_id")
        assignment = db.staff_assignments.get(assignment_id) if assignment_id else None
        if assignment is None or assignment["status"] != "ACTIVE":
            raise ApiError(ERR_PAGE_UNASSIGNED, 409,
                           "page has no active assigned staff member")

    page["status"] = "IN_REVIEW"
    touch(page)
    yb = db.yearbooks.get(page["yearbook_id"])
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.ladder_page(page), 200)


@bp.route("/yearbooks/pages/<page_id>/request-changes", methods=["POST"])
def request_changes(page_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    page = get_page_path(page_id)

    # request-changes is defined-from IN_REVIEW, APPROVED, and LOCKED.
    if page["status"] not in ("IN_REVIEW", "APPROVED", "LOCKED"):
        raise ApiError(ERR_INVALID_STATE, 409, "page is not in a reopenable state")

    # plant-frozen guard for APPROVED/LOCKED: a plant proof freezes the copy.
    if page["status"] in ("APPROVED", "LOCKED"):
        yb_id = page["yearbook_id"]
        frozen = any(
            pr["yearbook_id"] == yb_id and pr["status"] in ("PLANT_SUBMITTED", "PLANT_APPROVED")
            for pr in db.proofs.values()
        )
        if frozen:
            raise ApiError(ERR_PLANT_FROZEN, 409, "plant copy is frozen")

    page["status"] = "CHANGES_REQUESTED"
    touch(page)
    yb = db.yearbooks.get(page["yearbook_id"])
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.ladder_page(page), 200)


@bp.route("/yearbooks/pages/<page_id>/approve", methods=["POST"])
def approve_page(page_id):
    _, role = authenticate()
    authorize(role, {"Adviser"})
    page = get_page_path(page_id)

    if page["status"] != "IN_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "page is not in review")

    if page["approved_submission_count"] < page["required_submission_count"]:
        raise ApiError(ERR_SUBMISSIONS_INCOMPLETE, 409,
                       "page lacks enough approved submissions")

    page["status"] = "APPROVED"
    touch(page)
    yb = db.yearbooks.get(page["yearbook_id"])
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.ladder_page(page), 200)
