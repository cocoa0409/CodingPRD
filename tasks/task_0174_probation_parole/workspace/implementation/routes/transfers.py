"""Interstate-transfer endpoints (PRD §2.6, §3.8)."""
from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_STALE_SUPERVISEE_VERSION,
    ERR_TRANSFER_ALREADY_OPEN,
    ERR_TRANSFER_BLOCKED_HIGH_RISK,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.supervisee import cascade_conditions
from services.common import (
    apply_page,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    require_datetime,
    require_fields,
    require_int_min,
    sorted_by_created,
)

bp = Blueprint("transfers", __name__)


def _check_state_code(value, field):
    if (
        not isinstance(value, str)
        or len(value) != 2
        or not value.isalpha()
        or not value.isupper()
    ):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be two uppercase letters.")


@bp.post("/supervisees/<sid>/transfers")
@require_roles("Officer")
def create(sid):
    s = get_supervisee_or_404(sid)
    body = get_body()
    require_fields(body, ["receiving_state_code", "expected_supervisee_version"])
    _check_state_code(body["receiving_state_code"], "receiving_state_code")
    require_int_min(body["expected_supervisee_version"], 0, "expected_supervisee_version")

    # ERR_VALIDATION (422): receiving must differ from the sending state.
    if body["receiving_state_code"] == s["sentence_state_code"]:
        raise ApiError(*ERR_VALIDATION, "receiving_state_code must differ from sentence_state_code.")

    # ERR_TRANSFER_ALREADY_OPEN (409): one live compact claim at a time.
    for t in db.transfers.values():
        if t.get("supervisee_id") == sid and t["status"] in ("REQUESTED", "ACCEPTED"):
            raise ApiError(*ERR_TRANSFER_ALREADY_OPEN, "A live transfer already exists.")

    # OCC (ERR_STALE_SUPERVISEE_VERSION, 412).
    if body["expected_supervisee_version"] != s["version"]:
        raise ApiError(*ERR_STALE_SUPERVISEE_VERSION, "Stale supervisee version.")

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": s["id"],
            "receiving_state_code": body["receiving_state_code"],
            "expected_supervisee_version": body["expected_supervisee_version"],
            "status": "REQUESTED",
            "decided_at": None,
        }
    )
    db.transfers[rec["id"]] = rec
    # Successful request increments the supervisee's version by one.
    db.touch(s)
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/transfers")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_transfers(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [t for t in db.transfers.values() if t.get("supervisee_id") == sid]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/transfers/<tid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_transfer(sid, tid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.transfers, tid, sid, label="Transfer")
    return object_response(public(rec), 200)


@bp.post("/supervisees/<sid>/transfers/<tid>/accept")
@require_roles("CompactAdministrator")
def accept(sid, tid):
    s = get_supervisee_or_404(sid)
    t = get_child_or_404(db.transfers, tid, sid, label="Transfer")
    body = get_body()
    require_fields(body, ["decided_at"])
    require_datetime(body["decided_at"], "decided_at")
    if t["status"] != "REQUESTED":
        raise ApiError(*ERR_INVALID_STATE, "Transfer is not REQUESTED.")
    if s["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Supervisee is not ACTIVE.")
    # ERR_TRANSFER_BLOCKED_HIGH_RISK (409): cumulative points >= 12.
    if s["cumulative_violation_points"] >= 12:
        raise ApiError(*ERR_TRANSFER_BLOCKED_HIGH_RISK, "High-risk case cannot be exported.")
    t["status"] = "ACCEPTED"
    t["decided_at"] = body["decided_at"]
    # Bubble up to root: ACTIVE -> TRANSFERRED_OUT, conditions -> SATISFIED.
    s["status"] = "TRANSFERRED_OUT"
    cascade_conditions(s, ("ACTIVE",), "SATISFIED")
    db.touch(t)
    db.touch(s)
    return object_response(public(t), 200)


@bp.post("/supervisees/<sid>/transfers/<tid>/reject")
@require_roles("CompactAdministrator")
def reject(sid, tid):
    get_supervisee_or_404(sid)
    t = get_child_or_404(db.transfers, tid, sid, label="Transfer")
    body = get_body()
    require_fields(body, ["decided_at"])
    require_datetime(body["decided_at"], "decided_at")
    if t["status"] != "REQUESTED":
        raise ApiError(*ERR_INVALID_STATE, "Transfer is not REQUESTED.")
    t["status"] = "REJECTED"
    t["decided_at"] = body["decided_at"]
    db.touch(t)
    return object_response(public(t), 200)


@bp.post("/supervisees/<sid>/transfers/<tid>/withdraw")
@require_roles("Officer")
def withdraw(sid, tid):
    get_supervisee_or_404(sid)
    t = get_child_or_404(db.transfers, tid, sid, label="Transfer")
    if t["status"] != "REQUESTED":
        raise ApiError(*ERR_INVALID_STATE, "Transfer is not REQUESTED.")
    t["status"] = "WITHDRAWN"
    db.touch(t)
    return object_response(public(t), 200)
