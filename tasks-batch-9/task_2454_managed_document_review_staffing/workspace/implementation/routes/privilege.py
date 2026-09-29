"""The privilege log: authoring, validation and amendment (PRD 3.7, 3.8)."""

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
    user_id,
)
from response import created_response, object_response, paginated
from services import compute
from validation import bad, opt_str, req_bool, req_enum, req_str

bp = Blueprint("privilege", __name__)

PRIVILEGE_BASES = ("ATTORNEY_CLIENT", "WORK_PRODUCT", "COMMON_INTEREST")
DISPOSITIONS = ("WITHHELD", "REDACTED")
VALIDATION_BATCH_STATUSES = ("SECOND_LEVEL", "QC_SAMPLING", "QC_PASSED", "QC_FAILED")


def _require_active_session(reviewer_id, matter_id):
    """Rank 23."""
    if compute.active_session(reviewer_id, matter_id) is None:
        raise ApiError("ERR_NO_ACTIVE_SESSION",
                       "The reviewer holds no ACTIVE session containing the clock.")


@bp.route("/batches/<batch_id>/privilege-log-entries", methods=["POST"])
def log_entry(batch_id):
    require_roles(ROLE_REVIEWER)
    batch = compute.get_batch(batch_id)
    matter = compute.matter_of_batch(batch)
    payload = body()
    document_ref = req_str(payload, "document_ref", 1, 64)
    privilege_basis = req_enum(payload, "privilege_basis", PRIVILEGE_BASES)
    disposition = req_enum(payload, "disposition", DISPOSITIONS)

    for existing in compute.entries_of_batch(batch["id"]):
        if existing["document_ref"] == document_ref:
            raise bad("'document_ref' must be unique within the batch.")

    protocol = compute.effective_protocol(matter["id"])
    if protocol is not None and privilege_basis not in protocol["privilege_criteria"]:
        raise bad("'privilege_basis' is not in the approved protocol's privilege criteria.")

    _require_active_session(user_id(), matter["id"])

    row = base_row()
    row.update({
        "matter_id": matter["id"],
        "batch_id": batch["id"],
        "authored_by_reviewer_id": user_id(),
        "document_ref": document_ref,
        "privilege_basis": privilege_basis,
        "disposition": disposition,
        "status": "DRAFT",
        "challenge_note": None,
        "validated_at": None,
    })
    db.privilege_entries[row["id"]] = row
    return created_response(compute.privilege_entry_out(row))


@bp.route("/privilege-log-entries/<entry_id>", methods=["GET"])
def read_entry(entry_id):
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_QC_LEAD,
                  ROLE_REVIEWER, ROLE_CLIENT_COUNSEL)
    entry = compute.get_privilege_entry(entry_id)
    return object_response(compute.privilege_entry_out(entry))


@bp.route("/privilege-log-entries", methods=["GET"])
def list_entries():
    require_roles(ROLE_ENGAGEMENT_MANAGER, ROLE_STAFFING_COORDINATOR, ROLE_QC_LEAD,
                  ROLE_REVIEWER, ROLE_CLIENT_COUNSEL)
    rows = by_creation(list(db.privilege_entries.values()))
    matter_id = request.args.get("matter_id")
    batch_id = request.args.get("batch_id")
    authored_by = request.args.get("authored_by_reviewer_id")
    status = request.args.get("status")
    if matter_id:
        rows = [r for r in rows if r["matter_id"] == matter_id]
    if batch_id:
        rows = [r for r in rows if r["batch_id"] == batch_id]
    if authored_by:
        rows = [r for r in rows if r["authored_by_reviewer_id"] == authored_by]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, compute.privilege_entry_out)


@bp.route("/privilege-log-entries/<entry_id>/validate", methods=["POST"])
def validate_entry(entry_id):
    require_roles(ROLE_QC_LEAD)
    entry = compute.get_privilege_entry(entry_id)
    batch = compute.get_batch(entry["batch_id"])
    payload = body()
    accepted = req_bool(payload, "accepted")
    challenge_note = opt_str(payload, "challenge_note", 1, 2000, None)
    if not accepted and (challenge_note is None or challenge_note.strip() == ""):
        raise bad("'challenge_note' must be supplied and non-blank on a challenge.")

    if entry["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT entry may be validated.")
    if accepted and batch["status"] not in VALIDATION_BATCH_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "Privilege validation cannot begin before coding is finished.")

    if accepted:
        entry["status"] = "VALIDATED"
        entry["validated_at"] = db.now_iso()
    else:
        entry["status"] = "CHALLENGED"
        entry["challenge_note"] = challenge_note
    touch(entry)
    return object_response(compute.privilege_entry_out(entry))


@bp.route("/privilege-log-entries/<entry_id>/amend", methods=["POST"])
def amend_entry(entry_id):
    require_roles(ROLE_REVIEWER)
    entry = compute.get_privilege_entry(entry_id)
    if user_id() != entry["authored_by_reviewer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the authoring reviewer may amend this entry.")
    payload = body()
    privilege_basis = req_enum(payload, "privilege_basis", PRIVILEGE_BASES)
    disposition = req_enum(payload, "disposition", DISPOSITIONS)

    if entry["status"] != "CHALLENGED":
        raise ApiError("ERR_INVALID_STATE", "Only a CHALLENGED entry may be amended.")
    _require_active_session(entry["authored_by_reviewer_id"], entry["matter_id"])

    entry["privilege_basis"] = privilege_basis
    entry["disposition"] = disposition
    entry["challenge_note"] = None
    entry["status"] = "DRAFT"
    touch(entry)
    return object_response(compute.privilege_entry_out(entry))
