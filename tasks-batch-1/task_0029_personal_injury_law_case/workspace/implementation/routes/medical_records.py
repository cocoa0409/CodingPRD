"""Medical records request routes (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from db import (
    medical_records_requests, medical_providers, cases,
    stamp_common, bump,
)
from errors import (
    APIError, ERR_INVALID_STATE, ERR_DUPLICATE_RECORDS_REQUEST,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_str, get_or_404_path, get_or_fk_404,
)


bp = Blueprint("medical_records_requests", __name__)


def _view(r: dict) -> dict:
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "provider_id": r["provider_id"],
        "status": r["status"],
        "requested_at": r["requested_at"],
        "received_at": r.get("received_at"),
        "reviewed_at": r.get("reviewed_at"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.post("/medical-records-requests")
def create_request():
    require_auth({"Paralegal"})()
    body = get_json_body()
    case_id = require_str(body, "case_id")
    provider_id = require_str(body, "provider_id")

    get_or_fk_404(cases, case_id, "Case")
    get_or_fk_404(medical_providers, provider_id, "MedicalProvider")

    # Duplicate check — any existing in REQUESTED|RECEIVED collides regardless
    # of time (PRD §3.2: "no time buffer on this collision rule").
    for existing in medical_records_requests.values():
        if (existing["case_id"] == case_id
                and existing["provider_id"] == provider_id
                and existing["status"] in ("REQUESTED", "RECEIVED")):
            raise APIError(
                ERR_DUPLICATE_RECORDS_REQUEST, 409,
                "An active records request already exists for this case/provider",
            )

    now = db.get_current_utc()
    r = {
        "case_id": case_id,
        "provider_id": provider_id,
        "status": "REQUESTED",
        "requested_at": now,
        "received_at": None,
        "reviewed_at": None,
    }
    stamp_common(r)
    medical_records_requests[r["id"]] = r
    return ok_object(_view(r), 201)


@bp.get("/medical-records-requests/<rid>")
def get_request(rid):
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    r = get_or_404_path(medical_records_requests, rid, "MedicalRecordsRequest")
    return ok_object(_view(r), 200)


@bp.get("/medical-records-requests")
def list_requests():
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    limit, offset = paginate_params(request.args)
    case_id = request.args.get("case_id")
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    items = list(medical_records_requests.values())
    if case_id is not None:
        items = [r for r in items if r["case_id"] == case_id]
    if provider_id is not None:
        items = [r for r in items if r["provider_id"] == provider_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_view(r) for r in page], limit, offset, total, 200)


@bp.post("/medical-records-requests/<rid>/receive")
def receive(rid):
    require_auth({"Paralegal"})()
    r = get_or_404_path(medical_records_requests, rid, "MedicalRecordsRequest")
    if r["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Request must be REQUESTED to receive")
    r["status"] = "RECEIVED"
    r["received_at"] = db.get_current_utc()
    bump(r)
    return ok_object(_view(r), 200)


@bp.post("/medical-records-requests/<rid>/review")
def review(rid):
    require_auth({"Attorney"})()
    r = get_or_404_path(medical_records_requests, rid, "MedicalRecordsRequest")
    if r["status"] != "RECEIVED":
        raise APIError(ERR_INVALID_STATE, 409, "Request must be RECEIVED to review")
    r["status"] = "REVIEWED"
    r["reviewed_at"] = db.get_current_utc()
    bump(r)
    return ok_object(_view(r), 200)


@bp.post("/medical-records-requests/<rid>/reject")
def reject(rid):
    require_auth({"Paralegal"})()
    r = get_or_404_path(medical_records_requests, rid, "MedicalRecordsRequest")
    if r["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "Request must be REQUESTED to reject")
    r["status"] = "REJECTED"
    bump(r)
    return ok_object(_view(r), 200)
