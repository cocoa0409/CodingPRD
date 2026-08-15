"""SupplementDocumentation (SNS) endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from routes.allocations import get_allocation_or_404
from services import serializers, workflows

bp = Blueprint("sns", __name__)

ALL_ROLES = middleware.ROLES
FILERS = {"ComplianceAnalyst", "FederalProgramsDirector"}
METHODOLOGIES = {"PER_SCHOOL_DISTRIBUTION", "GRADE_SPAN_GROUPING", "PER_PUPIL_FORMULA"}
NARRATIVE_MIN = 50


def get_sns_or_404(doc_id):
    doc = db.sns_docs.get(doc_id)
    if doc is None:
        errors.fail(errors.ERR_NOT_FOUND, "SNS document %s does not exist." % doc_id)
    return doc


@bp.post("/supplement-documentation")
def create_sns():
    _uid, role = middleware.current_user()
    middleware.require_role(role, FILERS)
    data = V.json_body()
    # Tier 3: body FK existence (declared order).
    alloc_ref = data.get("school_allocation_id")
    if alloc_ref is not None and isinstance(alloc_ref, str):
        get_allocation_or_404(alloc_ref)
    # Tier 4: schema, fields validated in declared order.
    V.check_unknown(data, {
        "school_allocation_id", "methodology",
        "coverage_start_date", "coverage_end_date", "narrative",
    })
    alloc_id = V.req_str(data, "school_allocation_id")
    alloc = get_allocation_or_404(alloc_id)
    methodology = V.req_enum(data, "methodology", METHODOLOGIES)
    start_raw = V.req_str(data, "coverage_start_date")
    end_raw = V.req_str(data, "coverage_end_date")
    start = V.parse_date(start_raw, "coverage_start_date")
    end = V.parse_date(end_raw, "coverage_end_date")
    if end <= start:
        errors.fail(
            errors.ERR_INVALID_DATE_RANGE,
            "coverage_end_date must be after coverage_start_date (half-open window).",
        )
    narrative = V.req_str(data, "narrative")
    if len(narrative) < NARRATIVE_MIN:
        errors.fail(
            errors.ERR_NARRATIVE_TOO_SHORT,
            "narrative must be at least 50 characters.",
        )
    # Tier 10: half-open window overlap on the same allocation; touching is fine.
    for other in db.sns_docs.values():
        if other["school_allocation_id"] != alloc["id"]:
            continue
        o_start = V.parse_date(other["coverage_start_date"], "coverage_start_date")
        o_end = V.parse_date(other["coverage_end_date"], "coverage_end_date")
        if start < o_end and o_start < end:
            errors.fail(
                errors.ERR_SNS_WINDOW_OVERLAP,
                "Coverage window overlaps an existing SNS document on this allocation.",
            )
    doc = db.init_common({
        "school_allocation_id": alloc["id"],
        "methodology": methodology,
        "coverage_start_date": start_raw,
        "coverage_end_date": end_raw,
        "narrative": narrative,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "review_note": None,
        "attempt_count": 0,
    })
    db.sns_docs[doc["id"]] = doc
    return response.success_object(serializers.sns_view(doc), 201)


@bp.get("/supplement-documentation")
def list_sns():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    filters = [
        ("school_allocation_id", V.query_filter("school_allocation_id")),
        ("status", V.query_filter("status")),
    ]
    page, limit, offset, total = V.sorted_page(list(db.sns_docs.values()), filters)
    return response.success_list(
        [serializers.sns_view(d) for d in page], limit, offset, total
    )


@bp.get("/supplement-documentation/<doc_id>")
def get_sns(doc_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.sns_view(get_sns_or_404(doc_id)))


@bp.post("/supplement-documentation/<doc_id>/submit")
def submit_sns(doc_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, FILERS)
    doc = get_sns_or_404(doc_id)
    data = V.json_body()
    V.check_unknown(data, set())
    # Tier 5: submit is open from DRAFT, RETURNED (revision), and STALE (re-baseline).
    if doc["status"] not in ("DRAFT", "RETURNED", "STALE"):
        errors.fail(
            errors.ERR_SNS_NOT_SUBMITTABLE,
            "SNS document in status %s cannot be submitted." % doc["status"],
        )
    alloc = db.allocations[doc["school_allocation_id"]]
    if alloc["status"] != "CERTIFIED":
        errors.fail(
            errors.ERR_ALLOCATION_NOT_CERTIFIED,
            "Submission requires the covered allocation to be CERTIFIED.",
        )
    doc["status"] = "SUBMITTED"
    doc["submitted_by_user_id"] = uid
    doc["attempt_count"] += 1
    db.touch(doc)
    return response.success_object(serializers.sns_view(doc))


@bp.post("/supplement-documentation/<doc_id>/review")
def review_sns(doc_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    doc = get_sns_or_404(doc_id)
    data = V.json_body()
    V.check_unknown(data, {"decision", "review_note"})
    decision = V.req_enum(data, "decision", {"ACCEPT", "RETURN"})
    review_note = V.opt_str(data, "review_note")
    if decision == "RETURN" and not review_note:
        errors.fail(errors.ERR_INVALID_REQUEST, "review_note is required when decision is RETURN.")
    # Tier 5: state gate.
    if doc["status"] != "SUBMITTED":
        errors.fail(
            errors.ERR_SNS_NOT_REVIEWABLE,
            "SNS document in status %s cannot be reviewed." % doc["status"],
        )
    # Tier 7: segregation of duties against the submitter.
    if uid == doc["submitted_by_user_id"]:
        errors.fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The reviewer must differ from the document's submitter.",
        )
    doc["reviewed_by_user_id"] = uid
    doc["review_note"] = review_note
    alloc = db.allocations[doc["school_allocation_id"]]
    if decision == "ACCEPT":
        doc["status"] = "ACCEPTED"
        db.touch(doc)
        workflows.refresh_supplement_ok(alloc)
        db.touch(alloc)
    else:
        doc["status"] = "RETURNED"
        db.touch(doc)
    return response.success_object(serializers.sns_view(doc))
