"""Batch carving, dissolution and release (PRD 3.6, 3.8)."""

from flask import Blueprint, request

from db import base_row, by_creation, db, touch
from errors import ApiError
from middleware import (
    ROLE_CLIENT_COUNSEL,
    ROLE_ENGAGEMENT_MANAGER,
    ROLE_QC_LEAD,
    ROLE_REVIEWER,
    ROLE_STAFFING_COORDINATOR,
    body,
    require_roles,
)
from response import created_response, object_response, paginated
from routes.matters import require_not_suspended
from services import compute
from validation import opt_int, req_int

bp = Blueprint("batches", __name__)


def require_approved_protocol(matter):
    """Rank 15."""
    protocol = compute.approved_protocol(matter["id"])
    if protocol is None:
        raise ApiError("ERR_PROTOCOL_NOT_APPROVED",
                       "The matter has no review protocol in APPROVED.")
    return protocol


@bp.route("/matters/<matter_id>/batches", methods=["POST"])
def carve_batch(matter_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER)
    matter = compute.get_matter(matter_id)
    payload = body()
    document_count = req_int(payload, "document_count", 0)
    priority_rank = opt_int(payload, "priority_rank", 1, 9, 5)

    if matter["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "A CLOSED matter accepts no fresh batch.")
    require_not_suspended(matter)
    require_approved_protocol(matter)

    # Rank 28 - the deadline must still be ahead of the logical clock.
    if not db.now() < matter["_deadline_dt"]:
        raise ApiError("ERR_MATTER_DEADLINE_PASSED",
                       "The matter's deadline has already passed.")

    # Rank 37 then rank 38.
    if document_count < 1:
        raise ApiError("ERR_ZERO_DOCUMENT_BATCH",
                       "A batch must carry at least one document.")
    if document_count > compute.unbatched_document_count(matter):
        raise ApiError("ERR_INSUFFICIENT_UNBATCHED_DOCUMENTS",
                       "The matter's unbatched pool is too small for that carve.")

    existing = compute.batches_of_matter(matter["id"])
    batch_number = 1
    if existing:
        batch_number = max(b["batch_number"] for b in existing) + 1

    protocol = compute.approved_protocol(matter["id"])
    row = base_row()
    row.update({
        "matter_id": matter["id"],
        "batch_number": batch_number,
        "document_count": document_count,
        "priority_rank": priority_rank,
        "status": "CREATED",
        "released_at": None,
        "_frozen_qc_sample_pct": protocol["qc_sample_pct"],
    })
    db.batches[row["id"]] = row

    # The carve mutates the matter exactly once, closeout continuation included.
    if matter["status"] == "QC_CLOSEOUT":
        matter["status"] = "IN_REVIEW"
    touch(matter)
    return created_response(compute.batch_out(row))


@bp.route("/batches/<batch_id>", methods=["GET"])
def read_batch(batch_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_QC_LEAD,
                  ROLE_REVIEWER, ROLE_CLIENT_COUNSEL)
    batch = compute.get_batch(batch_id)
    return object_response(compute.batch_out(batch))


@bp.route("/batches", methods=["GET"])
def list_batches():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_QC_LEAD,
                  ROLE_REVIEWER, ROLE_CLIENT_COUNSEL)
    rows = by_creation(list(db.batches.values()))
    matter_id = request.args.get("matter_id")
    status = request.args.get("status")
    if matter_id:
        rows = [r for r in rows if r["matter_id"] == matter_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, compute.batch_out)


@bp.route("/batches/<batch_id>/dissolve", methods=["POST"])
def dissolve_batch(batch_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER)
    batch = compute.get_batch(batch_id)
    matter = compute.matter_of_batch(batch)

    # Rank 41 - both conditions report the same identifier.
    if batch["status"] != "CREATED":
        raise ApiError("ERR_BATCH_NOT_DISSOLVABLE",
                       "Only a CREATED batch may be dissolved.")
    for assignment in compute.assignments_of_batch(batch["id"]):
        if assignment["status"] != "VOIDED":
            raise ApiError("ERR_BATCH_NOT_DISSOLVABLE",
                           "The batch still carries a live assignment.")

    batch["status"] = "DISSOLVED"
    touch(batch)
    touch(matter)
    return object_response(compute.batch_out(batch))


@bp.route("/batches/<batch_id>/release", methods=["POST"])
def release_batch(batch_id):
    require_roles(ROLE_QC_LEAD)
    batch = compute.get_batch(batch_id)
    matter = compute.matter_of_batch(batch)

    if batch["status"] != "QC_PASSED":
        raise ApiError("ERR_INVALID_STATE", "A batch is released from QC_PASSED only.")
    require_not_suspended(matter)
    require_approved_protocol(matter)

    # Rank 24 - the privilege log must be sufficiently validated and unchallenged.
    entries = compute.entries_of_batch(batch["id"])
    validated = len([e for e in entries if e["status"] == "VALIDATED"])
    quota = compute.privilege_validation_quota(batch)
    if validated < quota:
        raise ApiError("ERR_PRIVILEGE_LOG_INCOMPLETE",
                       "Fewer validated privilege entries than the release quota.")
    for entry in entries:
        if entry["status"] == "CHALLENGED":
            raise ApiError("ERR_PRIVILEGE_LOG_INCOMPLETE",
                           "A privilege log entry of the batch is still CHALLENGED.")

    batch["status"] = "RELEASED"
    batch["released_at"] = db.now_iso()
    touch(batch)
    for entry in entries:
        if entry["status"] in ("DRAFT", "VALIDATED"):
            entry["status"] = "FINAL"
            touch(entry)
    for assignment in compute.assignments_of_batch(batch["id"]):
        if assignment["status"] == "SUBMITTED":
            assignment["status"] = "COMPLETED"
            touch(assignment)

    if matter["status"] == "IN_REVIEW":
        siblings = compute.batches_of_matter(matter["id"])
        all_done = all(b["status"] in ("RELEASED", "DISSOLVED") for b in siblings)
        if all_done and compute.unbatched_document_count(matter) == 0:
            matter["status"] = "QC_CLOSEOUT"
            touch(matter)
    return object_response(compute.batch_out(batch))
