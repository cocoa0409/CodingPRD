"""/pbm/prior-authorizations — Prior Authorization lifecycle."""
from __future__ import annotations

import re
from datetime import timedelta

from flask import Blueprint, request

from ..auth import require_roles
from ..envelope import success, list_success
from ..errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_PA_REVISION_LIMIT,
    ERR_RESOURCE_NOT_FOUND,
    ERR_VALIDATION,
)
from ..store import STORE
from ..validation import (
    check_version,
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
)

bp = Blueprint("prior_authorizations", __name__)

_NPI_RE = re.compile(r"^[0-9]{10}$")


def serialize_pa(pa: dict) -> dict:
    return {
        "id": pa["id"],
        "member_id": pa["member_id"],
        "drug_id": pa["drug_id"],
        "prescriber_npi": pa["prescriber_npi"],
        "clinical_rationale": pa["clinical_rationale"],
        "status": pa["status"],
        "effective_start": pa.get("effective_start"),
        "effective_end": pa.get("effective_end"),
        "revision_count": pa["revision_count"],
        "denial_reason": pa.get("denial_reason"),
        "created_at": pa["created_at"],
        "updated_at": pa["updated_at"],
        "version": pa["version"],
    }


@bp.post("/pbm/prior-authorizations")
@require_roles("Prescriber")
def create_pa():
    body = get_json_body()
    member_id = require_field(body, "member_id")
    drug_id = require_field(body, "drug_id")
    npi = require_field(body, "prescriber_npi")
    rationale = require_field(body, "clinical_rationale")

    if not isinstance(npi, str) or not _NPI_RE.match(npi):
        raise APIError(ERR_VALIDATION, "prescriber_npi must be 10 digits", 422)
    if not isinstance(rationale, str) or not rationale.strip():
        raise APIError(ERR_VALIDATION, "clinical_rationale must be non-empty", 422)

    with STORE.lock:
        if member_id not in STORE.members:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Member {member_id} not found", 404)
        if drug_id not in STORE.drugs:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Drug {drug_id} not found", 404)
        pa = STORE.init_common_fields({
            "member_id": member_id,
            "drug_id": drug_id,
            "prescriber_npi": npi,
            "clinical_rationale": rationale,
            "status": "DRAFT",
            "effective_start": None,
            "effective_end": None,
            "revision_count": 0,
            "denial_reason": None,
        })
        STORE.prior_authorizations[pa["id"]] = pa
    return success(serialize_pa(pa), status=201)


@bp.get("/pbm/prior-authorizations")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def list_pa():
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    drug_id = request.args.get("drug_id")
    status = request.args.get("status")
    with STORE.lock:
        items = list(STORE.prior_authorizations.values())
    if member_id:
        items = [p for p in items if p["member_id"] == member_id]
    if drug_id:
        items = [p for p in items if p["drug_id"] == drug_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, total = paginate(items, limit, offset)
    return list_success([serialize_pa(p) for p in page], limit=limit, offset=offset, total_count=total)


@bp.get("/pbm/prior-authorizations/<pid>")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def get_pa(pid: str):
    with STORE.lock:
        pa = STORE.prior_authorizations.get(pid)
    if pa is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, f"PriorAuthorization {pid} not found", 404)
    return success(serialize_pa(pa))


def _require_status(pa: dict, expected: str) -> None:
    if pa["status"] != expected:
        raise APIError(
            ERR_INVALID_STATE,
            f"PA must be {expected}; current={pa['status']}",
            409,
        )


@bp.post("/pbm/prior-authorizations/<pid>/submit")
@require_roles("Prescriber")
def submit_pa(pid: str):
    body = get_json_body()
    with STORE.lock:
        pa = STORE.prior_authorizations.get(pid)
        if pa is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"PriorAuthorization {pid} not found", 404)
        _require_status(pa, "DRAFT")
        check_version(body, pa)
        if not pa["clinical_rationale"] or not pa["clinical_rationale"].strip():
            raise APIError(ERR_VALIDATION, "clinical_rationale must be non-empty", 422)
        pa["status"] = "SUBMITTED"
        STORE.bump(pa)
        return success(serialize_pa(pa))


@bp.post("/pbm/prior-authorizations/<pid>/approve")
@require_roles("ClinicalReviewer")
def approve_pa(pid: str):
    body = get_json_body()
    with STORE.lock:
        pa = STORE.prior_authorizations.get(pid)
        if pa is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"PriorAuthorization {pid} not found", 404)
        _require_status(pa, "SUBMITTED")
        member = STORE.members.get(pa["member_id"])
        if member is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, "Member referenced by PA not found", 404)
        if member["enrollment_status"] != "ACTIVE":
            raise APIError(ERR_MEMBER_NOT_ACTIVE, "Referenced member is not ACTIVE", 409)
        check_version(body, pa)
        now = STORE.clock.now()
        pa["effective_start"] = STORE.fmt_ts(now)
        pa["effective_end"] = STORE.fmt_ts(now + timedelta(days=180))
        pa["status"] = "APPROVED"
        STORE.bump(pa)
        return success(serialize_pa(pa))


@bp.post("/pbm/prior-authorizations/<pid>/deny")
@require_roles("ClinicalReviewer")
def deny_pa(pid: str):
    body = get_json_body()
    denial_reason = body.get("denial_reason")
    if denial_reason is None or (isinstance(denial_reason, str) and not denial_reason.strip()):
        raise APIError(ERR_VALIDATION, "denial_reason is required", 422)
    with STORE.lock:
        pa = STORE.prior_authorizations.get(pid)
        if pa is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"PriorAuthorization {pid} not found", 404)
        _require_status(pa, "SUBMITTED")
        check_version(body, pa)
        pa["status"] = "DENIED"
        pa["denial_reason"] = denial_reason
        STORE.bump(pa)
        return success(serialize_pa(pa))


@bp.post("/pbm/prior-authorizations/<pid>/request-info")
@require_roles("ClinicalReviewer")
def request_info_pa(pid: str):
    body = get_json_body()
    with STORE.lock:
        pa = STORE.prior_authorizations.get(pid)
        if pa is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"PriorAuthorization {pid} not found", 404)
        _require_status(pa, "SUBMITTED")
        check_version(body, pa)
        pa["status"] = "INFO_REQUESTED"
        STORE.bump(pa)
        return success(serialize_pa(pa))


@bp.post("/pbm/prior-authorizations/<pid>/resubmit")
@require_roles("Prescriber")
def resubmit_pa(pid: str):
    body = get_json_body()
    rationale = body.get("clinical_rationale")
    if rationale is None or (isinstance(rationale, str) and not rationale.strip()):
        raise APIError(ERR_VALIDATION, "clinical_rationale is required for resubmit", 422)
    with STORE.lock:
        pa = STORE.prior_authorizations.get(pid)
        if pa is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"PriorAuthorization {pid} not found", 404)
        _require_status(pa, "INFO_REQUESTED")
        check_version(body, pa)
        # revision_count must be < 3 at resubmit
        if int(pa["revision_count"]) >= 3:
            raise APIError(ERR_PA_REVISION_LIMIT, "PA revision limit reached (max 3)", 422)
        pa["clinical_rationale"] = rationale
        pa["revision_count"] = int(pa["revision_count"]) + 1
        pa["status"] = "SUBMITTED"
        STORE.bump(pa)
        return success(serialize_pa(pa))


@bp.post("/pbm/prior-authorizations/<pid>/revoke")
@require_roles("ClinicalReviewer")
def revoke_pa(pid: str):
    body = get_json_body()
    with STORE.lock:
        pa = STORE.prior_authorizations.get(pid)
        if pa is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"PriorAuthorization {pid} not found", 404)
        _require_status(pa, "APPROVED")
        check_version(body, pa)
        pa["status"] = "REVOKED"
        STORE.bump(pa)
        return success(serialize_pa(pa))
