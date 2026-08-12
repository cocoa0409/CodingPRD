"""ContractSite endpoints."""
from flask import Blueprint
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import check_season_overlap, _touch

bp = Blueprint("contract_sites", __name__)

ALLOWED_FIELDS = {"contract_id", "site_id", "priority_sequence", "completion_target_minutes",
                  "trigger_depth_inches", "per_push_rate_cents", "salt_included_lbs"}


@bp.route("/contract-sites", methods=["POST"])
def create_contract_site():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    contract_id = body.get("contract_id")
    site_id = body.get("site_id")
    if not contract_id:
        raise ApiError(ERR_INVALID_REQUEST, "contract_id is required", 400)
    if not site_id:
        raise ApiError(ERR_INVALID_REQUEST, "site_id is required", 400)

    contract = db.contracts.get(contract_id)
    if not contract:
        raise ApiError(ERR_NOT_FOUND, f"Contract {contract_id} not found", 404)
    site = db.sites.get(site_id)
    if not site:
        raise ApiError(ERR_NOT_FOUND, f"Site {site_id} not found", 404)

    priority_sequence = body.get("priority_sequence")
    if priority_sequence is None:
        raise ApiError(ERR_INVALID_REQUEST, "priority_sequence is required", 400)
    completion_target = body.get("completion_target_minutes")
    if completion_target is None or completion_target <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "completion_target_minutes must be > 0", 400)

    # Uniqueness: priority_sequence per contract
    for cs in db.contract_sites.list_all():
        if cs.get("contract_id") == contract_id and cs.get("priority_sequence") == priority_sequence:
            raise ApiError(ERR_PRIORITY_SEQUENCE_CONFLICT, f"priority_sequence {priority_sequence} already used in contract", 409)

    # Season overlap check
    if check_season_overlap(contract_id, site_id, exclude_contract_id=contract_id):
        raise ApiError(ERR_SEASON_WINDOW_OVERLAP, "Season overlap with another ACTIVE/SUSPENDED contract", 409)

    # Compute effective values
    trigger_override = body.get("trigger_depth_inches")
    rate_override = body.get("per_push_rate_cents")
    effective_trigger = trigger_override if trigger_override is not None else contract.get("trigger_depth_inches", 2.00)
    effective_rate = rate_override if rate_override is not None else contract.get("per_push_rate_cents")

    cs_obj = {
        "id": db._new_id(),
        "contract_id": contract_id,
        "site_id": site_id,
        "trigger_depth_inches": trigger_override,
        "per_push_rate_cents": rate_override,
        "priority_sequence": priority_sequence,
        "completion_target_minutes": completion_target,
        "salt_included_lbs": body.get("salt_included_lbs", 0),
        "effective_trigger_depth_inches": effective_trigger,
        "effective_per_push_rate_cents": effective_rate,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.contract_sites.create(cs_obj)
    return success_created(cs_obj)


@bp.route("/contract-sites/<id>", methods=["GET"])
def get_contract_site(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    cs = db.contract_sites.get(id)
    if not cs:
        raise ApiError(ERR_NOT_FOUND, f"ContractSite {id} not found", 404)
    if role == "ClientContact":
        contract = db.contracts.get(cs.get("contract_id"))
        if contract and contract.get("client_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your contract", 403)
    return success_object(cs)


@bp.route("/contracts/<id>/contract-sites", methods=["GET"])
def list_contract_sites(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    contract = db.contracts.get(id)
    if not contract:
        raise ApiError(ERR_NOT_FOUND, f"Contract {id} not found", 404)
    if role == "ClientContact" and contract.get("client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your contract", 403)
    limit, offset = get_pagination()
    all_cs = sorted(
        [cs for cs in db.contract_sites.list_all() if cs.get("contract_id") == id],
        key=lambda c: c.get("created_at", ""),
    )
    total = len(all_cs)
    page = all_cs[offset:offset + limit]
    return success_list(page, total, limit, offset)
