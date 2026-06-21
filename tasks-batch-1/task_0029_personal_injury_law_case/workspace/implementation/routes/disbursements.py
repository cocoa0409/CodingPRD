"""Disbursement routes (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

from db import disbursements, cases, medical_liens, bump
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_CROSS_ENTITY_STATE,
    ERR_STALE_CASE_VERSION,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import get_or_404_path
from services.cascades import cascade_release_disbursement


bp = Blueprint("disbursements", __name__)


def _view(d: dict) -> dict:
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "gross_settlement_cents": d["gross_settlement_cents"],
        "contingency_fee_cents": d["contingency_fee_cents"],
        "total_lien_payout_cents": d["total_lien_payout_cents"],
        "net_to_client_cents": d["net_to_client_cents"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.get("/disbursements/<did>")
def get_disbursement(did):
    require_auth({"Attorney", "ManagingPartner", "Paralegal"})()
    d = get_or_404_path(disbursements, did, "Disbursement")
    return ok_object(_view(d), 200)


@bp.get("/disbursements")
def list_disbursements():
    require_auth({"Attorney", "ManagingPartner", "Paralegal"})()
    limit, offset = paginate_params(request.args)
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    items = list(disbursements.values())
    if case_id is not None:
        items = [d for d in items if d["case_id"] == case_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_view(d) for d in page], limit, offset, total, 200)


@bp.post("/disbursements/<did>/release")
def release(did):
    require_auth({"ManagingPartner"})()
    d = get_or_404_path(disbursements, did, "Disbursement")
    if d["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Disbursement must be PENDING to release")
    case = cases.get(d["case_id"])
    if case is None:
        raise APIError(ERR_INVALID_STATE, 409, "Parent case not found")
    if case["status"] != "SETTLED":
        raise APIError(ERR_CROSS_ENTITY_STATE, 409, "Case must be SETTLED to release")
    # Every lien on the case must be AGREED.
    for l in medical_liens.values():
        if l["case_id"] == case["id"] and l["status"] != "AGREED":
            raise APIError(
                ERR_CROSS_ENTITY_STATE, 409,
                "Every MedicalLien on this case must be AGREED to release the disbursement",
            )

    # OCC (priority 19).
    body = get_json_body()
    expected_v = body.get("expected_case_version")
    if expected_v is None or isinstance(expected_v, bool) or not isinstance(expected_v, int):
        raise APIError(ERR_INVALID_REQUEST, 400,
                       "expected_case_version (integer) is required")
    if expected_v != int(case["version"]):
        raise APIError(
            ERR_STALE_CASE_VERSION, 412,
            f"expected_case_version {expected_v} does not match {case['version']}",
        )

    cascade_release_disbursement(case, d)
    return ok_object(_view(d), 200)
