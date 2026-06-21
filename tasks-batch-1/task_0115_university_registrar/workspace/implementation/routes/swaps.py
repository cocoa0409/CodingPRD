"""Swap request routes: atomic add-then-drop, list, get."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, err
from middleware import authenticate, current_user_id, parse_pagination, require_roles
from response import ok_array, ok_object
from services import enroll, helpers as h
from services import serialize
from services.entities import new_common, touch

bp = Blueprint("swaps", __name__)


@bp.post("/swap-requests")
def create_swap_request():
    authenticate()
    require_roles("Student")
    body = h.get_json_body()

    # Body well-formedness (priority 2.5).
    term_id = h.require_string(body, "term_id")
    drop_enrollment_id = h.require_string(body, "drop_enrollment_id")
    add_section_id = h.require_string(body, "add_section_id")
    expected_section_version = h.require_int(body, "expected_section_version")

    # Existence (priority 3), left-to-right: Term, Student (acting), Section,
    # then Enrollment.
    term = h.get_term(term_id)
    student_id = current_user_id()
    h.get_student(student_id)
    add_section = h.get_section(add_section_id)
    drop_enrollment = h.get_enrollment(drop_enrollment_id)

    # Ownership (priority 4): acting Student must own the drop enrollment.
    if drop_enrollment["student_id"] != student_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting Student does not own the drop enrollment")

    # Persist the SwapRequest in PENDING before evaluating the atomic add-leg.
    rec = new_common("SwapRequest")
    rec.update({
        "student_id": student_id,
        "term_id": term_id,
        "drop_enrollment_id": drop_enrollment_id,
        "add_section_id": add_section_id,
        "status": "PENDING",
        "added_enrollment_id": None,
    })
    db.swap_requests[rec["id"]] = rec

    try:
        added = enroll.evaluate_swap(
            student_id, term, drop_enrollment, add_section, expected_section_version
        )
    except APIError as e:
        # ABORT: drop_enrollment untouched, no seat changes; record the outcome
        # and return the failing error to the caller (PRD §3.10).
        rec["status"] = "ABORTED"
        touch(rec)
        raise e

    rec["status"] = "COMMITTED"
    rec["added_enrollment_id"] = added["id"]
    touch(rec)
    return ok_object(serialize.swap_request(rec), 201)


@bp.get("/swap-requests")
def list_swap_requests():
    authenticate()
    require_roles("Registrar", "Advisor")
    limit, offset = parse_pagination()

    term_id = request.args.get("term_id")
    drop_enrollment_id = request.args.get("drop_enrollment_id")
    add_section_id = request.args.get("add_section_id")
    added_enrollment_id = request.args.get("added_enrollment_id")
    status = request.args.get("status")

    recs = [
        sr for sr in db.swap_requests.values()
        if (term_id is None or sr["term_id"] == term_id)
        and (drop_enrollment_id is None or sr["drop_enrollment_id"] == drop_enrollment_id)
        and (add_section_id is None or sr["add_section_id"] == add_section_id)
        and (added_enrollment_id is None or sr["added_enrollment_id"] == added_enrollment_id)
        and (status is None or sr["status"] == status)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.swap_request(sr) for sr in page], limit, offset, total, 200)


@bp.get("/swap-requests/<swap_id>")
def get_swap_request(swap_id):
    authenticate()
    require_roles("Registrar", "Advisor", "Student")
    rec = h.get_swap_request(swap_id)
    return ok_object(serialize.swap_request(rec), 200)
