"""Enrollment endpoints."""

from flask import Blueprint, request
from decimal import Decimal

from db import store, parse_iso
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import (
    ApiError, invalid_request, invalid_state, not_found, ownership_mismatch, stale_version,
    ERR_SCHOOL_YEAR_NOT_OPEN, ERR_SECTION_FULL, ERR_PLACEMENT_MISMATCH,
    ERR_DUPLICATE_ENROLLMENT,
)
from services.core import (
    base_record, touch, public, get_section, get_student, get_enrollment,
    compute_net_tuition, parse_date, round_half_up_cents,
    recompute_family_outstanding,
)

bp = Blueprint("enrollments", __name__)


@bp.route("/school/sections/<section_id>/enrollments", methods=["POST"])
def create_enrollment(section_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    section = get_section(section_id)
    body = request.get_json(silent=True) or {}
    student_id = body.get("student_id")
    if not isinstance(student_id, str):
        raise invalid_request("student_id is required")
    if "expected_section_version" not in body:
        raise invalid_request("expected_section_version is required")
    expected = body.get("expected_section_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_section_version must be an integer")

    student = get_student(student_id)

    # Ownership: Parent may only enroll students of own family
    if role == "Parent" and student["family_id"] != user_id:
        raise ownership_mismatch()

    year = store.school_years.get(section["school_year_id"])
    if year is None:
        raise not_found("SchoolYear not found")

    # OCC
    if expected != section["version"]:
        raise stale_version("Section version mismatch")

    # year must be OPEN
    if year["status"] != "OPEN":
        raise ApiError(ERR_SCHOOL_YEAR_NOT_OPEN, 409, "School year is not OPEN")

    # domain constraints: placement, capacity, duplicate
    if student["grade"] != section["grade"] or student["hebrew_level"] != section["hebrew_level"]:
        raise ApiError(ERR_PLACEMENT_MISMATCH, 409, "Student grade/level does not match section")
    if section["enrolled_count"] >= section["capacity"]:
        raise ApiError(ERR_SECTION_FULL, 409, "Section is at capacity")
    for e in store.enrollments.values():
        if (
            e["student_id"] == student_id
            and e["school_year_id"] == section["school_year_id"]
            and e["status"] in ("REGISTERED", "ACTIVE")
        ):
            raise ApiError(ERR_DUPLICATE_ENROLLMENT, 409, "Student already enrolled this year")

    rec = base_record()
    rec.update({
        "student_id": student_id,
        "section_id": section["id"],
        "family_id": student["family_id"],
        "school_year_id": section["school_year_id"],
        "status": "REGISTERED",
        "sibling_rank": 0,
        "estimated_tuition_cents": 0,
        "withdrawn_at": None,
        "withdrawal_credit_pct": None,
        "credit_applied": False,
    })
    store.enrollments[rec["id"]] = rec

    family = store.families.get(student["family_id"])
    line, rank = compute_net_tuition(year, family, rec)
    rec["estimated_tuition_cents"] = line
    rec["sibling_rank"] = rank

    # update section
    section["enrolled_count"] += 1
    if section["status"] == "OPEN" and section["enrolled_count"] >= section["capacity"]:
        section["status"] = "FULL"
    touch(section)

    # auto-create Milestone on the student's first enrollment in a year
    has_milestone = any(
        m["student_id"] == student_id and m["school_year_id"] == section["school_year_id"]
        for m in store.milestones.values()
    )
    if not has_milestone:
        m = base_record()
        m.update({
            "student_id": student_id,
            "family_id": student["family_id"],
            "school_year_id": section["school_year_id"],
            "milestone_name": "ANNUAL_CEREMONY",
            "status": "TRACKING",
            "current_attendance_pct": 0.0,
            "projected_attendance_pct": 0.0,
            "ceremony_date": None,
        })
        store.milestones[m["id"]] = m

    # auto-create VolunteerCommitment on the family's first enrollment in a year
    has_commitment = any(
        c["family_id"] == student["family_id"] and c["school_year_id"] == section["school_year_id"]
        for c in store.commitments.values()
    )
    if not has_commitment:
        c = base_record()
        c.update({
            "family_id": student["family_id"],
            "school_year_id": section["school_year_id"],
            "required_hours": year["volunteer_hours_required"],
            "logged_hours": 0,
            "status": "OPEN",
            "entries": [],
        })
        store.commitments[c["id"]] = c

    return success_object(public(rec), status=201)


@bp.route("/school/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment_endpoint(enrollment_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    rec = get_enrollment(enrollment_id)
    if role == "Parent" and rec["family_id"] != user_id:
        raise ownership_mismatch()
    return success_object(public(rec))


@bp.route("/school/enrollments", methods=["GET"])
def list_enrollments():
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    limit, offset = parse_pagination(request.args)
    family_id = request.args.get("family_id")
    student_id = request.args.get("student_id")
    section_id = request.args.get("section_id")
    school_year_id = request.args.get("school_year_id")
    status = request.args.get("status")

    items = list(store.enrollments.values())
    if role == "Parent":
        items = [e for e in items if e["family_id"] == user_id]
        # A parent may not filter by another family's id — but scoping already restricts.
        if family_id is not None and family_id != user_id:
            raise ownership_mismatch()
    if family_id is not None:
        items = [e for e in items if e["family_id"] == family_id]
    if student_id is not None:
        items = [e for e in items if e["student_id"] == student_id]
    if section_id is not None:
        items = [e for e in items if e["section_id"] == section_id]
    if school_year_id is not None:
        items = [e for e in items if e["school_year_id"] == school_year_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(e) for e in page], limit, offset, total)


@bp.route("/school/enrollments/<enrollment_id>/withdraw", methods=["POST"])
def withdraw_enrollment(enrollment_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    rec = get_enrollment(enrollment_id)
    if role == "Parent" and rec["family_id"] != user_id:
        raise ownership_mismatch()
    if rec["status"] not in ("REGISTERED", "ACTIVE"):
        raise invalid_state("Enrollment cannot be withdrawn from current state")

    year = store.school_years.get(rec["school_year_id"])
    section = store.sections.get(rec["section_id"])
    now = store.now()
    now_str = store.now_str()

    rec["status"] = "WITHDRAWN"
    rec["withdrawn_at"] = now_str

    # withdrawal credit tier
    wd = parse_date(year["withdrawal_deadline"])
    ed = parse_date(year["end_date"])
    today = now.date()
    if today < wd:
        pct = 1.0
    elif today < ed:
        pct = float(year["refund_pct_after_deadline"])
    else:
        pct = 0.0
    rec["withdrawal_credit_pct"] = pct
    touch(rec)

    # section side effects
    if section is not None:
        section["enrolled_count"] -= 1
        if section["status"] == "FULL" and section["enrolled_count"] < section["capacity"]:
            section["status"] = "OPEN"
        touch(section)

    # credit side effect
    # Find non-VOID invoice for family+year whose line_items contain a positive line for this enrollment
    billed_invoice = None
    for inv in store.invoices.values():
        if billed_invoice is not None:
            break
        if (
            inv["family_id"] == rec["family_id"]
            and inv["school_year_id"] == rec["school_year_id"]
            and inv["status"] != "VOID"
            and inv.get("kind") == "TUITION"
        ):
            for li in inv.get("line_items", []):
                if li.get("enrollment_id") == rec["id"] and li.get("line_cents", 0) > 0:
                    billed_invoice = inv
                    break

    if (
        billed_invoice is not None
        and billed_invoice.get("paid_cents", 0) > 0
        and not rec.get("credit_applied")
    ):
        credit = round_half_up_cents(Decimal(rec["estimated_tuition_cents"]) * Decimal(str(pct)))
        family = store.families.get(rec["family_id"])
        if family is not None and credit > 0:
            family["credit_balance_cents"] += credit
            rec["credit_applied"] = True
            recompute_family_outstanding(family)
            touch(family)

    return success_object(public(rec))
