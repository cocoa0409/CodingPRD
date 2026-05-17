"""Follow-up routes."""
from flask import Blueprint, jsonify, request

from app.auth import require_roles
from app.errors import err_forbidden, err_invalid_state, err_not_found
from app.responses import success_object
from app.store import store
from app.clock import clock
from app.utils import (
    bump_version_and_timestamp,
    check_version_if_supplied,
    parse_iso_datetime,
    parse_json_body,
)


bp = Blueprint("followups", __name__)


@bp.get("/telemed/followups/<fid>")
@require_roles(["ComplianceOfficer", "Physician"])
def get_followup(fid: str):
    fu = store.followups.get(fid)
    if not fu:
        raise err_not_found()
    return jsonify(success_object(fu)), 200


@bp.post("/telemed/followups/<fid>/complete")
@require_roles(["Physician"])
def complete_followup(fid: str):
    fu = store.followups.get(fid)
    if not fu:
        raise err_not_found()
    body = parse_json_body()
    if fu["status"] != "SCHEDULED":
        raise err_invalid_state("FollowUp is not in SCHEDULED state")
    # Acting physician must own the owning consult.
    consult = store.consults.get(fu["consult_id"])
    if not consult:
        raise err_not_found()
    user_id = request.headers.get("X-User-ID")
    if consult.get("physician_id") != user_id:
        raise err_forbidden()
    check_version_if_supplied(fu, body)
    # Must complete on or before due_by.
    try:
        due_by = parse_iso_datetime(fu["due_by"])
    except ValueError:
        raise err_invalid_state("Malformed due_by")
    if clock.now() > due_by:
        raise err_invalid_state("FollowUp window has passed (due_by exceeded)")
    with store.lock:
        if fu["status"] != "SCHEDULED":
            raise err_invalid_state("FollowUp is not in SCHEDULED state")
        fu["status"] = "COMPLETED"
        bump_version_and_timestamp(fu, store.now_iso())
    return jsonify(success_object(fu)), 200


@bp.post("/telemed/followups/<fid>/cancel")
@require_roles(["ComplianceOfficer"])
def cancel_followup(fid: str):
    fu = store.followups.get(fid)
    if not fu:
        raise err_not_found()
    body = parse_json_body()
    if fu["status"] != "SCHEDULED":
        raise err_invalid_state("FollowUp is not in SCHEDULED state")
    check_version_if_supplied(fu, body)
    with store.lock:
        if fu["status"] != "SCHEDULED":
            raise err_invalid_state("FollowUp is not in SCHEDULED state")
        fu["status"] = "CANCELLED"
        bump_version_and_timestamp(fu, store.now_iso())
    return jsonify(success_object(fu)), 200
