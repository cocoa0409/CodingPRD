"""Beneficiary endpoints (SCAFFOLD §1.5 beneficiaries)."""
from __future__ import annotations

from flask import Blueprint, request

from config import BENEFICIARY_RELATIONSHIPS, BENEFICIARY_STATUSES
from db import store
from errors import ApiError
from middleware import current_role, current_user_id, require_auth
from response import list_success, success
from services.beneficiary_engine import transition_beneficiary
from services.common import (
    check_version,
    get_json_body,
    paginate,
    pop_pagination,
    require_child,
    require_estate,
    sort_by_created_at,
)
from services.serializers import serialize_beneficiary
from utils import new_uuid


bp = Blueprint("beneficiaries", __name__)


@bp.post("/estates/<estate_id>/beneficiaries")
@require_auth(["Executor"])
def create_beneficiary(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        estate = require_estate(estate_id)
        if estate["admin_phase"] == "SETTLED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Cannot nominate beneficiaries on a SETTLED estate.")
        full_name = body.get("full_name")
        if not isinstance(full_name, str) or not full_name.strip():
            raise ApiError("ERR_BAD_REQUEST", 400, "full_name is required.")
        relationship = body.get("relationship")
        if relationship not in BENEFICIARY_RELATIONSHIPS:
            raise ApiError("ERR_BAD_REQUEST", 400, "relationship must be one of the enum literals.")
        is_minor = body.get("is_minor", False)
        if not isinstance(is_minor, bool):
            raise ApiError("ERR_BAD_REQUEST", 400, "is_minor must be a boolean.")

        bid = new_uuid()
        now = store.now()
        b = {
            "id": bid,
            "estate_id": estate_id,
            "full_name": full_name,
            "relationship": relationship,
            "is_minor": is_minor,
            "guardianship_id": None,
            "status": "ACTIVE",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.beneficiaries[bid] = b
    return success(serialize_beneficiary(b), 201)


@bp.get("/estates/<estate_id>/beneficiaries/<beneficiary_id>")
@require_auth(["Executor", "Beneficiary", "CourtClerk"])
def get_beneficiary(estate_id: str, beneficiary_id: str):
    with store.lock:
        require_estate(estate_id)
        b = require_child(store.beneficiaries, estate_id, beneficiary_id)
    return success(serialize_beneficiary(b), 200)


@bp.get("/estates/<estate_id>/beneficiaries")
@require_auth(["Executor", "CourtClerk"])
def list_beneficiaries(estate_id: str):
    limit, offset = pop_pagination(request.args)
    status_f = request.args.get("status")
    if status_f is not None and status_f not in BENEFICIARY_STATUSES:
        raise ApiError("ERR_BAD_REQUEST", 400, "status filter invalid.")

    with store.lock:
        require_estate(estate_id)
        rows = [b for b in store.beneficiaries.values() if b["estate_id"] == estate_id]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        rows = sort_by_created_at(rows)
        page, total = paginate(rows, limit, offset)
        items = [serialize_beneficiary(r) for r in page]
    return list_success(items, limit, offset, total, 200)


@bp.post("/estates/<estate_id>/beneficiaries/<beneficiary_id>/state")
@require_auth(["Beneficiary", "CourtClerk"])
def transition_beneficiary_state(estate_id: str, beneficiary_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in BENEFICIARY_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409, "Unknown target status for beneficiary transition.")
    with store.lock:
        estate = require_estate(estate_id)
        b = require_child(store.beneficiaries, estate_id, beneficiary_id)
        check_version(b, body)
        transition_beneficiary(b, estate, to_status, current_role(), current_user_id())
    return success(serialize_beneficiary(b), 200)
