"""Fiduciary endpoints (SCAFFOLD §1.5 fiduciaries)."""
from __future__ import annotations

from flask import Blueprint, request

from config import FIDUCIARY_SCOPE_TYPES, FIDUCIARY_STATUSES
from db import store
from errors import ApiError
from middleware import current_role, current_user_id, require_auth
from response import list_success, success
from services.common import (
    check_version,
    get_json_body,
    paginate,
    pop_pagination,
    require_child,
    require_estate,
    sort_by_created_at,
)
from services.fiduciary_engine import transition_fiduciary
from services.serializers import serialize_fiduciary
from utils import new_uuid


bp = Blueprint("fiduciaries", __name__)


def _is_non_neg_int(v) -> bool:
    if isinstance(v, bool):
        return False
    return isinstance(v, int) and v >= 0


@bp.post("/estates/<estate_id>/fiduciaries")
@require_auth(["Executor", "CourtClerk"])
def create_fiduciary(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        require_estate(estate_id)
        scope_type = body.get("scope_type")
        if scope_type not in FIDUCIARY_SCOPE_TYPES:
            raise ApiError("ERR_BAD_REQUEST", 400, "scope_type must be one of the enum literals.")
        full_name = body.get("full_name")
        if not isinstance(full_name, str) or not full_name.strip():
            raise ApiError("ERR_BAD_REQUEST", 400, "full_name is required.")
        contact = body.get("contact_user_id")
        if not isinstance(contact, str) or not contact.strip():
            raise ApiError("ERR_BAD_REQUEST", 400, "contact_user_id is required.")
        bond = body.get("bond_amount_cents")
        if bond is not None and not _is_non_neg_int(bond):
            raise ApiError("ERR_BAD_REQUEST", 400,
                           "bond_amount_cents must be a non-negative integer.")

        fid = new_uuid()
        now = store.now()
        f = {
            "id": fid,
            "estate_id": estate_id,
            "scope_type": scope_type,
            "full_name": full_name,
            "contact_user_id": contact,
            "status": "NOMINATED",
            "bond_amount_cents": int(bond) if bond is not None else None,
            "court_confirmation_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.fiduciaries[fid] = f
    return success(serialize_fiduciary(f), 201)


@bp.get("/estates/<estate_id>/fiduciaries/<fiduciary_id>")
@require_auth(["Executor", "Beneficiary", "CourtClerk", "Fiduciary"])
def get_fiduciary(estate_id: str, fiduciary_id: str):
    with store.lock:
        require_estate(estate_id)
        f = require_child(store.fiduciaries, estate_id, fiduciary_id)
    return success(serialize_fiduciary(f), 200)


@bp.get("/estates/<estate_id>/fiduciaries")
@require_auth(["Executor", "Beneficiary", "CourtClerk", "Fiduciary"])
def list_fiduciaries(estate_id: str):
    limit, offset = pop_pagination(request.args)
    scope_f = request.args.get("scope_type")
    status_f = request.args.get("status")
    if scope_f is not None and scope_f not in FIDUCIARY_SCOPE_TYPES:
        raise ApiError("ERR_BAD_REQUEST", 400, "scope_type filter invalid.")
    if status_f is not None and status_f not in FIDUCIARY_STATUSES:
        raise ApiError("ERR_BAD_REQUEST", 400, "status filter invalid.")

    with store.lock:
        require_estate(estate_id)
        rows = [f for f in store.fiduciaries.values() if f["estate_id"] == estate_id]
        if scope_f:
            rows = [r for r in rows if r["scope_type"] == scope_f]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        rows = sort_by_created_at(rows)
        page, total = paginate(rows, limit, offset)
        items = [serialize_fiduciary(r) for r in page]
    return list_success(items, limit, offset, total, 200)


@bp.post("/estates/<estate_id>/fiduciaries/<fiduciary_id>/state")
@require_auth(["CourtClerk", "Fiduciary"])
def transition_fiduciary_state(estate_id: str, fiduciary_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in FIDUCIARY_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409, "Unknown target status for fiduciary transition.")
    with store.lock:
        estate = require_estate(estate_id)
        f = require_child(store.fiduciaries, estate_id, fiduciary_id)
        check_version(f, body)
        transition_fiduciary(f, estate, to_status, current_role(), current_user_id())
    return success(serialize_fiduciary(f), 200)
