"""CarePlan and CourtReview routes."""

from flask import Blueprint, request

from clock import clock, parse_iso
from db import db, stamp_create, stamp_update
from errors import err
from middleware import get_identity, require_role
from response import object_response, array_response
from validators import (
    ALL_ROLES,
    get_json_body,
    require_string,
    require_int,
    require_enum,
    parse_pagination,
    paginate,
)
from services import (
    resolve_path,
    resolve_ref,
    care_plans_for_case,
    derive_care_plan_status,
)

bp = Blueprint("careplans", __name__)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap. One ending exactly when another begins is
    NOT an overlap (exclusive upper bound)."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# CarePlan
# ---------------------------------------------------------------------------
@bp.route("/gc/care-plans", methods=["POST"])
def create_care_plan():
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    residence_type = require_enum(
        body, "residence_type", {"HOME", "ASSISTED_LIVING", "NURSING_FACILITY", "HOSPITAL"}
    )
    visitation = require_int(body, "visitation_min_per_month", minimum=0)
    window_start = require_string(body, "window_start_iso")
    window_end = require_string(body, "window_end_iso")
    resolve_ref(db.cases, case_id)

    record = {
        "case_id": case_id,
        "residence_type": residence_type,
        "visitation_min_per_month": visitation,
        "window_start_iso": window_start,
        "window_end_iso": window_end,
        "status": "DRAFT",
    }
    stamp_create(record)
    with db.lock:
        db.care_plans[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/care-plans/<cid>", methods=["GET"])
def get_care_plan(cid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    plan = resolve_path(db.care_plans, cid)
    derive_care_plan_status(plan)
    return object_response(plan, 200)


@bp.route("/gc/care-plans", methods=["GET"])
def list_care_plans():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.care_plans.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [c for c in items if c["case_id"] == case_id]
    for c in items:
        derive_care_plan_status(c)
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/care-plans/<cid>/activate", methods=["POST"])
def activate_care_plan(cid):
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    plan = resolve_path(db.care_plans, cid)
    if plan["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Care plan must be DRAFT")
    case = db.cases.get(plan["case_id"])
    if case is None or case["status"] != "ACTIVE":
        raise err("ERR_CASE_NOT_ACTIVE", "Case must be ACTIVE to activate a care plan")
    # Window well-formedness (priority 6: ERR_INVALID_WINDOW).
    try:
        start = parse_iso(plan["window_start_iso"])
        end = parse_iso(plan["window_end_iso"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_WINDOW", "Care plan window is malformed")
    if not (start < end):
        raise err("ERR_INVALID_WINDOW", "window_start_iso must be strictly before window_end_iso")
    # Overlap check against other ACTIVE plans on the same case (priority 16).
    for other in care_plans_for_case(plan["case_id"]):
        if other["id"] == plan["id"]:
            continue
        # Re-derive expiry so a lapsed plan does not block.
        derive_care_plan_status(other)
        if other["status"] != "ACTIVE":
            continue
        try:
            o_start = parse_iso(other["window_start_iso"])
            o_end = parse_iso(other["window_end_iso"])
        except (ValueError, TypeError):
            continue
        if _windows_overlap(start, end, o_start, o_end):
            raise err("ERR_CARE_PLAN_OVERLAP", "Window overlaps another ACTIVE care plan")

    plan["status"] = "ACTIVE"
    stamp_update(plan)
    return object_response(plan, 200)


@bp.route("/gc/care-plans/<cid>/replace", methods=["POST"])
def replace_care_plan(cid):
    _, role = get_identity()
    require_role(role, ["Fiduciary"])
    plan = resolve_path(db.care_plans, cid)
    # Re-derive expiry first so an expired plan is not treated as ACTIVE.
    derive_care_plan_status(plan)
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Care plan must be ACTIVE")
    plan["status"] = "REPLACED"
    stamp_update(plan)
    return object_response(plan, 200)


# ---------------------------------------------------------------------------
# CourtReview
# ---------------------------------------------------------------------------
@bp.route("/gc/reviews", methods=["POST"])
def create_review():
    _, role = get_identity()
    require_role(role, ["Judge", "CourtClerk"])
    body = get_json_body()
    case_id = require_string(body, "case_id")
    subject_kind = require_enum(body, "subject_kind", {"ACCOUNTING", "CARE_PLAN"})
    subject_ref_id = require_string(body, "subject_ref_id")
    window_start = require_string(body, "review_window_start_iso")
    window_end = require_string(body, "review_window_end_iso")
    case = resolve_ref(db.cases, case_id)

    # Resolve the polymorphic subject; must exist and belong to the same case.
    if subject_kind == "ACCOUNTING":
        subject = db.accountings.get(subject_ref_id)
    else:
        subject = db.care_plans.get(subject_ref_id)
    if subject is None or subject["case_id"] != case_id:
        raise err("ERR_REFERENCE_NOT_FOUND", "Subject does not resolve within this case")

    record = {
        "case_id": case_id,
        "subject_kind": subject_kind,
        "subject_ref_id": subject_ref_id,
        "review_window_start_iso": window_start,
        "review_window_end_iso": window_end,
        "outcome": "PENDING",
        "status": "SCHEDULED",
    }
    stamp_create(record)
    with db.lock:
        db.reviews[record["id"]] = record
    return object_response(record, 201)


@bp.route("/gc/reviews/<rid>", methods=["GET"])
def get_review(rid):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    return object_response(resolve_path(db.reviews, rid), 200)


@bp.route("/gc/reviews", methods=["GET"])
def list_reviews():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.reviews.values())
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [r for r in items if r["case_id"] == case_id]
    window, total = paginate(items, limit, offset)
    return array_response(window, limit, offset, total)


@bp.route("/gc/reviews/<rid>/hold", methods=["POST"])
def hold_review(rid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    review = resolve_path(db.reviews, rid)
    if review["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Review must be SCHEDULED")
    case = db.cases.get(review["case_id"])
    if case is None or case["status"] != "UNDER_REVIEW":
        raise err("ERR_CASE_NOT_UNDER_REVIEW", "Case must be UNDER_REVIEW to hold a review")
    try:
        start = parse_iso(review["review_window_start_iso"])
    except (ValueError, TypeError):
        raise err("ERR_REVIEW_WINDOW_NOT_OPEN", "Review window is malformed")
    if clock.now_dt() < start:
        raise err("ERR_REVIEW_WINDOW_NOT_OPEN", "Review window has not opened")
    review["status"] = "HELD"
    stamp_update(review)
    return object_response(review, 200)


@bp.route("/gc/reviews/<rid>/dispose", methods=["POST"])
def dispose_review(rid):
    _, role = get_identity()
    require_role(role, ["Judge"])
    body = get_json_body()
    review = resolve_path(db.reviews, rid)
    if review["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "Review must be HELD")
    outcome = require_enum(body, "outcome", {"ACCEPTED", "CONTINUED", "SANCTIONED"})

    review["outcome"] = outcome
    review["status"] = "CLOSED"
    stamp_update(review)
    # SANCTIONED + ACCOUNTING subject currently SUBMITTED -> RETURNED_FOR_CORRECTION.
    if outcome == "SANCTIONED" and review["subject_kind"] == "ACCOUNTING":
        report = db.accountings.get(review["subject_ref_id"])
        if report is not None and report["status"] == "SUBMITTED":
            report["status"] = "RETURNED_FOR_CORRECTION"
            stamp_update(report)
    return object_response(review, 200)
