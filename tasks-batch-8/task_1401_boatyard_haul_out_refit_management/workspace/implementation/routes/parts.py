"""Parts and owner-supplied policy (PRD 3.7)."""

from flask import Blueprint, request

import db
import response
from errors import (
    not_found, validation, invalid_state, already_terminal, ApiError,
    ERR_OWNER_PARTS_PROHIBITED,
)
from middleware import require_roles, check_owner_job
from money import dec, rhu, OWNER_PARTS_FEE_PCT
from services import storage as storage_svc
from validation import (
    get_body, req_str, req_enum, req_bool, req_int, opt_str, parse_pagination, page,
)
from .jobs import get_job_or_404

bp = Blueprint("parts", __name__)

PART_CATEGORIES = ("BOTTOM_PAINT", "MECHANICAL", "ELECTRICAL", "RIGGING", "OTHER")
# Job states in which a part may be registered.
REGISTRABLE_JOB_STATES = (
    "INTAKE", "HAUL_SCHEDULED", "ON_HARD", "WORK_IN_PROGRESS", "READY_FOR_SPLASH",
)
INSPECT_OUTCOMES = ("RECEIVED", "REJECTED")


def get_part_or_404(part_id):
    part = db.parts.get(part_id)
    if part is None:
        raise not_found(f"Part '{part_id}' does not exist")
    return part


@bp.post("/yard/parts")
@require_roles("Owner", "ServiceWriter")
def create_part():
    body = get_body()
    job_id = req_str(body, "job_id")
    job = get_job_or_404(job_id)
    # Ownership scope (gate 3) for the Owner role.
    check_owner_job(job)
    description = req_str(body, "description")
    category = req_enum(body, "category", PART_CATEGORIES)
    owner_supplied = req_bool(body, "owner_supplied")
    declared_value = req_int(body, "declared_value_cents", ge=0)

    if job["status"] not in REGISTRABLE_JOB_STATES:
        raise invalid_state(f"Parts cannot be registered while the job is {job['status']}")
    if owner_supplied and category == "BOTTOM_PAINT":
        raise ApiError(ERR_OWNER_PARTS_PROHIBITED, 422,
                       "Owner-supplied bottom paint violates yard policy")

    now = db.now_iso()
    part = {
        "id": db.new_id(),
        "job_id": job["id"],
        "description": description,
        "category": category,
        "owner_supplied": owner_supplied,
        "declared_value_cents": declared_value,
        "status": "EXPECTED",
        "inspect_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.parts[part["id"]] = part
    return response.success_object(db.pub(part), status=201)


@bp.get("/yard/refit-jobs/<jobId>/parts")
@require_roles("ServiceWriter", "YardManager", "Owner")
def list_parts(jobId):
    job = get_job_or_404(jobId)
    check_owner_job(job)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [p for p in db.parts.values() if p["job_id"] == job["id"]]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)


@bp.post("/yard/parts/<partId>/inspect")
@require_roles("ServiceWriter")
def inspect_part(partId):
    part = get_part_or_404(partId)
    body = get_body()
    outcome = req_enum(body, "outcome", INSPECT_OUTCOMES)
    note = opt_str(body, "inspect_note")
    if part["status"] in ("RECEIVED", "REJECTED"):
        raise already_terminal(f"Part is already {part['status']}")
    part["status"] = outcome
    part["inspect_note"] = note
    db.touch(part)
    if outcome == "RECEIVED" and part["owner_supplied"]:
        fee = rhu(OWNER_PARTS_FEE_PCT * dec(part["declared_value_cents"]))
        if fee > 0:
            storage_svc.post_ledger(
                part["job_id"], "CHARGE", "PARTS_HANDLING", fee,
                memo=f"Owner-supplied parts handling fee for part {part['id']}",
                source_part_id=part["id"],
            )
    return response.success_object(db.pub(part))
