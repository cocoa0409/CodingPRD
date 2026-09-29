"""Confidentiality agreements: issuance, execution, lazy expiry (PRD 3.5)."""

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_REVIEWER,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
    role,
    user_id,
)
from response import created_response, object_response, paginated
from routes.matters import require_not_suspended
from services import cascade, compute
from validation import opt_bool, present, req_id, req_instant, req_str

bp = Blueprint("agreements", __name__)


@bp.route("/confidentiality-agreements", methods=["POST"])
def issue_agreement():
    require_roles(ROLE_STAFFING_COORDINATOR)
    payload = body()

    reviewer = None
    matter = None
    if present(payload, "reviewer_id") and isinstance(payload["reviewer_id"], str):
        reviewer = compute.get_reviewer(payload["reviewer_id"])
    if present(payload, "matter_id") and isinstance(payload["matter_id"], str):
        matter = compute.get_matter(payload["matter_id"])

    req_id(payload, "reviewer_id")
    req_id(payload, "matter_id")
    if reviewer is None:
        reviewer = compute.get_reviewer(payload["reviewer_id"])
    if matter is None:
        matter = compute.get_matter(payload["matter_id"])
    start_dt, start_raw = req_instant(payload, "coverage_start_utc")
    end_dt, end_raw = req_instant(payload, "coverage_end_utc")
    remote_work_addendum = opt_bool(payload, "remote_work_addendum", False)

    # Rank 9 - the start must be strictly before the end.
    if not start_dt < end_dt:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "'coverage_start_utc' must be strictly before 'coverage_end_utc'.")

    require_not_suspended(matter)
    if reviewer["engagement_status"] == "REMOVED":
        raise ApiError("ERR_REVIEWER_REMOVED", "The reviewer has been removed.")
    if not compute.has_cleared_screening(reviewer["id"], matter["id"]):
        raise ApiError("ERR_CONFLICTS_NOT_CLEARED",
                       "No CLEARED conflicts screening exists for this pair.")

    # Rank 27 consults the pair's live agreements, so lazy expiry applies first.
    cascade.apply_lazy_expiry_many(compute.agreements_of_pair(reviewer["id"], matter["id"]))
    for existing in compute.agreements_of_pair(reviewer["id"], matter["id"]):
        if existing["status"] not in ("PENDING", "EXECUTED"):
            continue
        if compute.coverage_overlaps(existing, start_dt, end_dt):
            raise ApiError("ERR_CA_COVERAGE_OVERLAP",
                           "Coverage collides with an existing agreement for this pair.")

    row = base_row()
    row.update({
        "reviewer_id": reviewer["id"],
        "matter_id": matter["id"],
        "coverage_start_utc": start_raw,
        "coverage_end_utc": end_raw,
        "_coverage_start_dt": start_dt,
        "_coverage_end_dt": end_dt,
        "remote_work_addendum": remote_work_addendum,
        "status": "PENDING",
        "executed_at": None,
        "signature_name": None,
        "revocation_reason": None,
    })
    db.agreements[row["id"]] = row
    return created_response(compute.agreement_out(row))


@bp.route("/confidentiality-agreements/<agreement_id>", methods=["GET"])
def read_agreement(agreement_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    agreement = compute.get_agreement(agreement_id)
    cascade.apply_lazy_expiry(agreement)
    return object_response(compute.agreement_out(agreement))


@bp.route("/confidentiality-agreements", methods=["GET"])
def list_agreements():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR,
                  ROLE_QC_LEAD, ROLE_REVIEWER)
    rows = by_creation(list(db.agreements.values()))
    reviewer_id = request.args.get("reviewer_id")
    matter_id = request.args.get("matter_id")
    status = request.args.get("status")
    if reviewer_id:
        rows = [r for r in rows if r["reviewer_id"] == reviewer_id]
    if matter_id:
        rows = [r for r in rows if r["matter_id"] == matter_id]
    # Lazy expiry applies to every row the listing would return.
    cascade.apply_lazy_expiry_many(rows)
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, compute.agreement_out)


@bp.route("/confidentiality-agreements/<agreement_id>/execute", methods=["POST"])
def execute_agreement(agreement_id):
    require_roles(ROLE_REVIEWER)
    agreement = compute.get_agreement(agreement_id)
    matter = compute.get_matter(agreement["matter_id"])
    if role() == ROLE_REVIEWER and user_id() != agreement["reviewer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the named reviewer may execute this agreement.")
    payload = body()
    signature_name = req_str(payload, "signature_name", 1, 120)

    if agreement["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING agreement may be executed.")
    require_not_suspended(matter)
    if db.now() > agreement["_coverage_end_dt"]:
        raise ApiError("ERR_INVALID_STATE",
                       "The coverage interval has already elapsed.")

    agreement["status"] = "EXECUTED"
    agreement["executed_at"] = db.now_iso()
    agreement["signature_name"] = signature_name
    touch(agreement)
    cascade.sync_matter_staffing(matter)
    return object_response(compute.agreement_out(agreement))
