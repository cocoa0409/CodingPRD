"""Estate endpoints (SCAFFOLD §1.5 estates)."""
from __future__ import annotations

from flask import Blueprint, request

from config import US_STATE_CODES, ESTATE_PHASES, PROBATE_POSTURES
from db import store
from errors import ApiError
from middleware import current_role, current_user_id, require_auth
from response import list_success, success
from services.calculations import compute_probate_posture
from services.common import bump, check_version, get_json_body, pop_pagination, require_estate, sort_by_created_at, paginate
from services.estate_engine import transition_estate
from services.serializers import serialize_estate
from utils import new_uuid


bp = Blueprint("estates", __name__)


def _require_str(body: dict, key: str, max_len: int | None = None) -> str:
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_BAD_REQUEST", 400, f"{key} is required and must be a non-empty string.")
    if max_len is not None and len(v) > max_len:
        raise ApiError("ERR_BAD_REQUEST", 400, f"{key} exceeds the maximum length of {max_len}.")
    return v


@bp.post("/estates")
@require_auth(["Executor"])
def create_estate():
    body = get_json_body(request)
    testator_name = _require_str(body, "testator_name", 500)
    domicile = _require_str(body, "domicile_state")
    if domicile not in US_STATE_CODES:
        raise ApiError("ERR_BAD_REQUEST", 400, "domicile_state must be a valid US two-letter state code.")
    filing_court_id = _require_str(body, "filing_court_id")

    eid = new_uuid()
    now = store.now()
    estate = {
        "id": eid,
        "testator_name": testator_name,
        "domicile_state": domicile,
        "filing_court_id": filing_court_id,
        "gross_estate_value_cents": 0,
        "net_estate_value_cents": 0,
        "admin_phase": "DRAFT",
        "petition_filed_at": None,
        "settlement_due_at": None,
        "contested_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock:
        store.estates[eid] = estate
    return success(serialize_estate(estate), 201)


@bp.get("/estates/<estate_id>")
@require_auth(["Executor", "Beneficiary", "CourtClerk", "Fiduciary"])
def get_estate(estate_id: str):
    with store.lock:
        e = require_estate(estate_id)
    return success(serialize_estate(e), 200)


@bp.get("/estates")
@require_auth(["CourtClerk"])
def list_estates():
    limit, offset = pop_pagination(request.args)
    phase_f = request.args.get("admin_phase")
    posture_f = request.args.get("probate_posture")
    if phase_f is not None and phase_f not in ESTATE_PHASES:
        raise ApiError("ERR_BAD_REQUEST", 400, "admin_phase filter invalid.")
    if posture_f is not None and posture_f not in PROBATE_POSTURES:
        raise ApiError("ERR_BAD_REQUEST", 400, "probate_posture filter invalid.")

    with store.lock:
        rows = list(store.estates.values())
        if phase_f:
            rows = [r for r in rows if r["admin_phase"] == phase_f]
        if posture_f:
            rows = [r for r in rows if compute_probate_posture(r) == posture_f]
        rows = sort_by_created_at(rows)
        page, total = paginate(rows, limit, offset)
        items = [serialize_estate(r) for r in page]
    return list_success(items, limit, offset, total, 200)


@bp.patch("/estates/<estate_id>")
@require_auth(["Executor"])
def patch_estate(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        e = require_estate(estate_id)
        check_version(e, body)
        if e["admin_phase"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Estate non-state fields can only be updated while DRAFT.")
        if "testator_name" in body:
            v = body["testator_name"]
            if not isinstance(v, str) or not v.strip():
                raise ApiError("ERR_BAD_REQUEST", 400, "testator_name must be a non-empty string.")
            e["testator_name"] = v
        if "domicile_state" in body:
            v = body["domicile_state"]
            if not isinstance(v, str) or v not in US_STATE_CODES:
                raise ApiError("ERR_BAD_REQUEST", 400, "domicile_state must be a valid US state code.")
            e["domicile_state"] = v
        if "filing_court_id" in body:
            v = body["filing_court_id"]
            if not isinstance(v, str) or not v.strip():
                raise ApiError("ERR_BAD_REQUEST", 400, "filing_court_id must be a non-empty string.")
            e["filing_court_id"] = v
        bump(e)
    return success(serialize_estate(e), 200)


@bp.post("/estates/<estate_id>/state")
@require_auth(["Executor", "CourtClerk"])
def transition_estate_state(estate_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in ESTATE_PHASES:
        raise ApiError("ERR_INVALID_STATE", 409, "Unknown target status for estate transition.")
    with store.lock:
        e = require_estate(estate_id)
        check_version(e, body)
        transition_estate(e, to_status, current_role())
    return success(serialize_estate(e), 200)
