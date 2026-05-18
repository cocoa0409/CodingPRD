"""BeneficiaryDesignation endpoints (SCAFFOLD §1.5 designations)."""
from __future__ import annotations

from flask import Blueprint, request

from config import DESIGNATION_STATUSES
from db import store
from errors import ApiError
from middleware import require_auth
from response import list_success, success
from services.common import (
    get_json_body,
    paginate,
    pop_pagination,
    require_child,
    require_estate,
    sort_by_created_at,
)
from services.serializers import serialize_designation
from utils import new_uuid


bp = Blueprint("designations", __name__)


def _is_int_in(v, lo: int, hi: int) -> bool:
    if isinstance(v, bool):
        return False
    return isinstance(v, int) and lo <= v <= hi


@bp.post("/estates/<estate_id>/designations")
@require_auth(["Executor"])
def create_designation(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        require_estate(estate_id)
        asset_id = body.get("asset_id")
        beneficiary_id = body.get("beneficiary_id")
        share = body.get("share_basis_points")
        priority = body.get("priority_rank")

        if not isinstance(asset_id, str) or not asset_id:
            raise ApiError("ERR_BAD_REQUEST", 400, "asset_id is required.")
        if not isinstance(beneficiary_id, str) or not beneficiary_id:
            raise ApiError("ERR_BAD_REQUEST", 400, "beneficiary_id is required.")
        if not _is_int_in(share, 0, 10000):
            raise ApiError("ERR_BAD_REQUEST", 400,
                           "share_basis_points must be an integer in [0, 10000].")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ApiError("ERR_BAD_REQUEST", 400, "priority_rank must be an integer.")

        # FK existence within estate scope.
        asset = store.assets.get(asset_id)
        if not asset or asset["estate_id"] != estate_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "asset_id does not reference an asset in this estate.")
        beneficiary = store.beneficiaries.get(beneficiary_id)
        if not beneficiary or beneficiary["estate_id"] != estate_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "beneficiary_id does not reference a beneficiary in this estate.")
        if beneficiary["status"] != "ACTIVE":
            raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                           "Beneficiary must be ACTIVE at designation creation.")

        # Over-allocation guard (priority 10).
        existing_sum = 0
        for d in store.designations.values():
            if d["estate_id"] != estate_id:
                continue
            if d["asset_id"] != asset_id:
                continue
            if d["status"] in ("PROPOSED", "LOCKED"):
                existing_sum += d["share_basis_points"]
        if existing_sum + int(share) > 10000:
            raise ApiError("ERR_DESIGNATION_OVER_ALLOCATED", 422,
                           "Sum of share_basis_points on this asset would exceed 10000.")

        did = new_uuid()
        now = store.now()
        d = {
            "id": did,
            "estate_id": estate_id,
            "asset_id": asset_id,
            "beneficiary_id": beneficiary_id,
            "share_basis_points": int(share),
            "priority_rank": int(priority),
            "status": "PROPOSED",
            "created_at": now,
        }
        store.designations[did] = d
    return success(serialize_designation(d), 201)


@bp.get("/estates/<estate_id>/designations/<designation_id>")
@require_auth(["Executor", "Beneficiary", "CourtClerk"])
def get_designation(estate_id: str, designation_id: str):
    with store.lock:
        require_estate(estate_id)
        d = require_child(store.designations, estate_id, designation_id)
    return success(serialize_designation(d), 200)


@bp.get("/estates/<estate_id>/designations")
@require_auth(["Executor", "Beneficiary", "CourtClerk"])
def list_designations(estate_id: str):
    limit, offset = pop_pagination(request.args)
    asset_f = request.args.get("asset_id")
    beneficiary_f = request.args.get("beneficiary_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in DESIGNATION_STATUSES:
        raise ApiError("ERR_BAD_REQUEST", 400, "status filter invalid.")

    with store.lock:
        require_estate(estate_id)
        rows = [d for d in store.designations.values() if d["estate_id"] == estate_id]
        if asset_f:
            rows = [r for r in rows if r["asset_id"] == asset_f]
        if beneficiary_f:
            rows = [r for r in rows if r["beneficiary_id"] == beneficiary_f]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        rows = sort_by_created_at(rows)
        page, total = paginate(rows, limit, offset)
        items = [serialize_designation(r) for r in page]
    return list_success(items, limit, offset, total, 200)


@bp.delete("/estates/<estate_id>/designations/<designation_id>")
@require_auth(["Executor"])
def delete_designation(estate_id: str, designation_id: str):
    with store.lock:
        require_estate(estate_id)
        d = require_child(store.designations, estate_id, designation_id)
        if d["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Only PROPOSED designations may be voided.")
        d["status"] = "VOIDED"
    return success(serialize_designation(d), 200)
