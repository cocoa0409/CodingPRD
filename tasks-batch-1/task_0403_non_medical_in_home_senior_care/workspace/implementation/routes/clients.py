"""Client endpoints + lifecycle (PRD §3.3)."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth, require_roles
from response import success, list_success
from services import requtil
from services.lookup import get_agency, get_client

bp = Blueprint("clients", __name__)

READ_ROLES = {"AgencyAdmin", "Scheduler", "BillingClerk", "Caregiver"}


@bp.post("/clients")
def create_client():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler"})
    body = requtil.get_body()

    agency_id = requtil.require_str(body, "agency_id")
    full_name = requtil.require_str(body, "full_name")
    residence_state_code = requtil.require_str(body, "residence_state_code")
    get_agency(agency_id)
    requires_live_in = requtil.optional_bool(body, "requires_live_in", False)

    client = {
        "agency_id": agency_id,
        "full_name": full_name,
        "residence_state_code": residence_state_code,
        "requires_live_in": requires_live_in,
        "continuity_score": 0,
        "status": "INTAKE",
    }
    db.stamp_new(client)
    db.clients[client["id"]] = client
    return success(db.public(client), status=201)


@bp.get("/clients")
def list_clients():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler", "BillingClerk"})
    limit, offset = requtil.pagination()
    agency_id = request.args.get("agency_id")
    items = list(db.clients.values())
    if agency_id is not None:
        items = [c for c in items if c["agency_id"] == agency_id]
    page, total = requtil.paginate(items, limit, offset)
    return list_success([db.public(c) for c in page], limit, offset, total)


@bp.get("/clients/<cid>")
def get_client_route(cid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    client = get_client(cid)
    return success(db.public(client))


@bp.post("/clients/<cid>/transition")
def transition_client(cid):
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin", "Scheduler"})
    client = get_client(cid)
    body = requtil.get_body()
    action = requtil.require_enum(body, "action", {"ACTIVATE", "HOLD", "RESUME", "DISCHARGE"})

    status = client["status"]
    if action == "ACTIVATE":
        if status != "INTAKE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "ACTIVATE requires INTAKE")
        client["status"] = "ACTIVE"
    elif action == "HOLD":
        if status != "ACTIVE":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "HOLD requires ACTIVE")
        client["status"] = "ON_HOLD"
    elif action == "RESUME":
        if status != "ON_HOLD":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "RESUME requires ON_HOLD")
        client["status"] = "ACTIVE"
    elif action == "DISCHARGE":
        if status == "DISCHARGED":
            raise ApiError(errors.ERR_INVALID_STATE, 409, "already DISCHARGED")
        client["status"] = "DISCHARGED"

    db.touch(client)
    return success(db.public(client))
