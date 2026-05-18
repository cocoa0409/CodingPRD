"""Asset endpoints (SCAFFOLD §1.5 assets)."""
from __future__ import annotations

from flask import Blueprint, request

from config import ASSET_CLASSES, ASSET_STATUSES, ASSET_DESCRIPTION_MAX
from db import store
from errors import ApiError
from middleware import require_auth
from response import list_success, success
from services.asset_engine import transition_asset
from services.common import (
    bump,
    check_version,
    get_json_body,
    paginate,
    pop_pagination,
    require_child,
    require_estate,
    sort_by_created_at,
)
from services.serializers import serialize_asset
from utils import new_uuid


bp = Blueprint("assets", __name__)


def _is_non_neg_int(v) -> bool:
    if isinstance(v, bool):
        return False
    return isinstance(v, int) and v >= 0


def _poa_gate_check(asset: dict, estate: dict):
    """Enforce SCAFFOLD §1.4 priority 8 (PRD §3.2): when estate is DRAFT and
    asset.requires_poa_for_mutation is true, an ACTIVE POA whose asset_class_scope
    covers this asset's asset_class is required.
    """
    if estate["admin_phase"] != "DRAFT":
        return
    if not asset.get("requires_poa_for_mutation"):
        return
    cls = asset["asset_class"]
    for p in store.poas.values():
        if p["estate_id"] != estate["id"]:
            continue
        if p["status"] != "ACTIVE":
            continue
        scope = p.get("asset_class_scope") or []
        if scope == "ALL" or "ALL" in scope or cls in scope:
            return  # covered
    raise ApiError("ERR_POA_SCOPE_INSUFFICIENT", 403,
                   f"No ACTIVE POA covers asset_class {cls}.")


@bp.post("/estates/<estate_id>/assets")
@require_auth(["Executor"])
def create_asset(estate_id: str):
    body = get_json_body(request)
    with store.lock:
        estate = require_estate(estate_id)
        if estate["admin_phase"] not in ("DRAFT", "IN_PROBATE"):
            # PRD §3.1 implies asset declaration during DRAFT; once estate is
            # past DRAFT the executor may still declare newly discovered
            # assets up until INVENTORIED (per PRD §3.4 they walk the table).
            # Allow declaration while DRAFT/IN_PROBATE (DECLARED→INVENTORIED
            # requires IN_PROBATE/INVENTORIED).
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Assets may only be declared while estate is DRAFT or IN_PROBATE.")

        asset_class = body.get("asset_class")
        if asset_class not in ASSET_CLASSES:
            raise ApiError("ERR_BAD_REQUEST", 400, "asset_class must be one of the enum literals.")
        description = body.get("description")
        if not isinstance(description, str) or not description:
            raise ApiError("ERR_BAD_REQUEST", 400, "description is required.")
        if len(description) > ASSET_DESCRIPTION_MAX:
            raise ApiError("ERR_BAD_REQUEST", 400,
                           f"description exceeds {ASSET_DESCRIPTION_MAX} characters.")
        declared = body.get("declared_value_cents")
        if not _is_non_neg_int(declared):
            raise ApiError("ERR_BAD_REQUEST", 400,
                           "declared_value_cents must be a non-negative integer.")
        req_poa = body.get("requires_poa_for_mutation", False)
        if not isinstance(req_poa, bool):
            raise ApiError("ERR_BAD_REQUEST", 400, "requires_poa_for_mutation must be a boolean.")

        aid = new_uuid()
        now = store.now()
        asset = {
            "id": aid,
            "estate_id": estate_id,
            "asset_class": asset_class,
            "description": description,
            "declared_value_cents": int(declared),
            "appraised_value_cents": None,
            "status": "DECLARED",
            "distribution_id": None,
            "requires_poa_for_mutation": req_poa,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.assets[aid] = asset
    return success(serialize_asset(asset), 201)


@bp.get("/estates/<estate_id>/assets/<asset_id>")
@require_auth(["Executor", "Beneficiary", "CourtClerk", "Fiduciary"])
def get_asset(estate_id: str, asset_id: str):
    with store.lock:
        require_estate(estate_id)
        a = require_child(store.assets, estate_id, asset_id)
    return success(serialize_asset(a), 200)


@bp.get("/estates/<estate_id>/assets")
@require_auth(["Executor", "Beneficiary", "CourtClerk", "Fiduciary"])
def list_assets(estate_id: str):
    limit, offset = pop_pagination(request.args)
    status_f = request.args.get("status")
    class_f = request.args.get("asset_class")
    if status_f is not None and status_f not in ASSET_STATUSES:
        raise ApiError("ERR_BAD_REQUEST", 400, "status filter invalid.")
    if class_f is not None and class_f not in ASSET_CLASSES:
        raise ApiError("ERR_BAD_REQUEST", 400, "asset_class filter invalid.")

    with store.lock:
        require_estate(estate_id)
        rows = [a for a in store.assets.values() if a["estate_id"] == estate_id]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if class_f:
            rows = [r for r in rows if r["asset_class"] == class_f]
        rows = sort_by_created_at(rows)
        page, total = paginate(rows, limit, offset)
        items = [serialize_asset(r) for r in page]
    return list_success(items, limit, offset, total, 200)


@bp.patch("/estates/<estate_id>/assets/<asset_id>")
@require_auth(["Executor"])
def patch_asset(estate_id: str, asset_id: str):
    body = get_json_body(request)
    with store.lock:
        estate = require_estate(estate_id)
        a = require_child(store.assets, estate_id, asset_id)
        check_version(a, body)
        if a["status"] not in ("DECLARED", "INVENTORIED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Asset PATCH allowed only while DECLARED or INVENTORIED.")
        _poa_gate_check(a, estate)
        if "description" in body:
            v = body["description"]
            if not isinstance(v, str) or not v:
                raise ApiError("ERR_BAD_REQUEST", 400, "description must be a non-empty string.")
            if len(v) > ASSET_DESCRIPTION_MAX:
                raise ApiError("ERR_BAD_REQUEST", 400,
                               f"description exceeds {ASSET_DESCRIPTION_MAX} characters.")
            a["description"] = v
        if "declared_value_cents" in body:
            v = body["declared_value_cents"]
            if not _is_non_neg_int(v):
                raise ApiError("ERR_BAD_REQUEST", 400,
                               "declared_value_cents must be a non-negative integer.")
            a["declared_value_cents"] = int(v)
        bump(a)
    return success(serialize_asset(a), 200)


@bp.post("/estates/<estate_id>/assets/<asset_id>/state")
@require_auth(["Executor"])
def transition_asset_state(estate_id: str, asset_id: str):
    body = get_json_body(request)
    to_status = body.get("to_status")
    if to_status not in ASSET_STATUSES:
        raise ApiError("ERR_INVALID_STATE", 409, "Unknown target status for asset transition.")
    with store.lock:
        estate = require_estate(estate_id)
        a = require_child(store.assets, estate_id, asset_id)
        check_version(a, body)
        # POA gate applies before state-machine check (priority 8 vs 6).
        # However scaffold validation priority places state (6) before POA scope (8).
        # We still call POA gate here AFTER state-machine reachability check
        # to honor priority order.
        # Check reachability quickly:
        if (a["status"], to_status) not in {
            ("DECLARED", "INVENTORIED"),
            ("INVENTORIED", "APPRAISED"),
            ("APPRAISED", "DISTRIBUTED"),
            ("DECLARED", "EXCLUDED"),
            ("INVENTORIED", "EXCLUDED"),
        }:
            raise ApiError("ERR_INVALID_STATE", 409,
                           f"Cannot transition asset from {a['status']} to {to_status}.")
        _poa_gate_check(a, estate)
        transition_asset(a, estate, to_status, body)
    return success(serialize_asset(a), 200)
