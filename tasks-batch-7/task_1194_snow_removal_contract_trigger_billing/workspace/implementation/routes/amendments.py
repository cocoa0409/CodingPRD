"""ContractAmendment endpoints."""
from flask import Blueprint
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import _touch

bp = Blueprint("amendments", __name__)

ALLOWED_FIELDS = {"contract_id", "expected_contract_version", "effective_from",
                  "trigger_depth_inches", "per_push_rate_cents", "sla_miss_penalty_cents",
                  "require_photo_verification"}

CHANGE_FIELDS = {"trigger_depth_inches", "per_push_rate_cents", "sla_miss_penalty_cents", "require_photo_verification"}


@bp.route("/amendments", methods=["POST"])
def create_amendment():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    contract_id = body.get("contract_id")
    if not contract_id:
        raise ApiError(ERR_INVALID_REQUEST, "contract_id is required", 400)
    contract = db.contracts.get(contract_id)
    if not contract:
        raise ApiError(ERR_NOT_FOUND, f"Contract {contract_id} not found", 404)

    # OCC check
    expected_version = body.get("expected_contract_version")
    if expected_version is None:
        raise ApiError(ERR_INVALID_REQUEST, "expected_contract_version is required", 400)
    if expected_version != contract.get("version"):
        raise ApiError(ERR_STALE_CONTRACT_VERSION, f"Expected version {expected_version}, current is {contract.get('version')}", 412)

    # effective_from window check
    effective_from = body.get("effective_from")
    if not effective_from:
        raise ApiError(ERR_INVALID_REQUEST, "effective_from is required", 400)
    ef = db._parse_iso(effective_from)
    if not ef:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid effective_from", 400)
    ss = db._parse_iso(contract.get("season_start"))
    se = db._parse_iso(contract.get("season_end"))
    if not ss or not se:
        raise ApiError(ERR_INVALID_REQUEST, "Contract season dates invalid", 400)
    if ef <= ss or ef > se:
        raise ApiError(ERR_AMENDMENT_WINDOW_INVALID, "effective_from must be in (season_start, season_end]", 422)

    # At least one change field
    has_change = any(body.get(f) is not None for f in CHANGE_FIELDS)
    if not has_change:
        raise ApiError(ERR_INVALID_REQUEST, "At least one change field required", 400)

    # Supersede existing PENDING amendment
    for a in db.amendments.list_all():
        if a.get("contract_id") == contract_id and a.get("status") == "PENDING":
            a["status"] = "SUPERSEDED"
            _touch(a)
            db.amendments.update(a["id"], a)

    amendment = {
        "id": db._new_id(),
        "contract_id": contract_id,
        "effective_from": effective_from,
        "trigger_depth_inches": body.get("trigger_depth_inches"),
        "per_push_rate_cents": body.get("per_push_rate_cents"),
        "sla_miss_penalty_cents": body.get("sla_miss_penalty_cents"),
        "require_photo_verification": body.get("require_photo_verification"),
        "status": "PENDING",
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.amendments.create(amendment)

    # Increment contract version
    _touch(contract)
    db.contracts.update(contract_id, contract)

    return success_created(amendment)


@bp.route("/contracts/<id>/amendments", methods=["GET"])
def list_contract_amendments(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    contract = db.contracts.get(id)
    if not contract:
        raise ApiError(ERR_NOT_FOUND, f"Contract {id} not found", 404)
    if role == "ClientContact" and contract.get("client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your contract", 403)
    limit, offset = get_pagination()
    all_amendments = sorted(
        [a for a in db.amendments.list_all() if a.get("contract_id") == id],
        key=lambda a: a.get("created_at", ""),
    )
    total = len(all_amendments)
    page = all_amendments[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/amendments/<id>/approve", methods=["POST"])
def approve_amendment(id):
    user_id, role = require_roles("OpsDispatcher")
    amendment = db.amendments.get(id)
    if not amendment:
        raise ApiError(ERR_NOT_FOUND, f"Amendment {id} not found", 404)
    if amendment["status"] != "PENDING":
        if amendment["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
            raise ApiError(ERR_ALREADY_TERMINAL, f"Amendment already {amendment['status']}", 409)
        raise ApiError(ERR_INVALID_STATE, f"Cannot approve from {amendment['status']}", 409)

    contract = db.contracts.get(amendment["contract_id"])
    if not contract:
        raise ApiError(ERR_NOT_FOUND, "Contract not found", 404)
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "Contract must be ACTIVE to approve amendment", 409)

    # Apply non-null change fields
    for field in CHANGE_FIELDS:
        val = amendment.get(field)
        if val is not None:
            contract[field] = val

    amendment["status"] = "APPROVED"
    _touch(amendment)
    db.amendments.update(id, amendment)

    _touch(contract)
    db.contracts.update(contract["id"], contract)

    return success_object(amendment)


@bp.route("/amendments/<id>/reject", methods=["POST"])
def reject_amendment(id):
    user_id, role = require_roles("OpsDispatcher")
    amendment = db.amendments.get(id)
    if not amendment:
        raise ApiError(ERR_NOT_FOUND, f"Amendment {id} not found", 404)
    if amendment["status"] != "PENDING":
        if amendment["status"] in ("APPROVED", "REJECTED", "SUPERSEDED"):
            raise ApiError(ERR_ALREADY_TERMINAL, f"Amendment already {amendment['status']}", 409)
        raise ApiError(ERR_INVALID_STATE, f"Cannot reject from {amendment['status']}", 409)
    amendment["status"] = "REJECTED"
    _touch(amendment)
    db.amendments.update(id, amendment)
    return success_object(amendment)
