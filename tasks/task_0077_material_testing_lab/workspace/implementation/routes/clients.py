"""Client routes: register, read, patch (OCC on version)."""

from flask import Blueprint, g

from db import DB, new_id, LOCK
from errors import ERR_NOT_FOUND, ERR_VALIDATION, raise_error
from middleware import auth_required
from response import success_response
from services.common import get_json_body, require_fields, check_version, bump_version
from services.serializers import serialize_client
from services.time_util import now_iso

bp = Blueprint("clients", __name__)


@bp.post("/clients")
@auth_required(["LabManager"])
def create_client():
    body = get_json_body()
    require_fields(body, ["name", "contact_email"])
    name = body["name"]
    email = body["contact_email"]
    if not isinstance(name, str) or not name:
        raise_error(ERR_VALIDATION, "name must be a non-empty string")
    if not isinstance(email, str) or not email:
        raise_error(ERR_VALIDATION, "contact_email must be a non-empty string")
    contract_id = body.get("contract_id")
    if contract_id is not None and not isinstance(contract_id, str):
        raise_error(ERR_VALIDATION, "contract_id must be a string or null")
    now = now_iso()
    with LOCK:
        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "name": name,
            "contact_email": email,
            "contract_id": contract_id,
            "deposit_balance_cents": 0,
            "outstanding_balance_cents": 0,
        }
        DB["clients"][row["id"]] = row
    return success_response(serialize_client(row), 201)


@bp.get("/clients/<cid>")
@auth_required(["LabManager", "LabClerk"])
def read_client(cid):
    row = DB["clients"].get(cid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Client not found")
    return success_response(serialize_client(row), 200)


@bp.patch("/clients/<cid>")
@auth_required(["LabManager"])
def update_client(cid):
    body = get_json_body()
    row = DB["clients"].get(cid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Client not found")
    check_version(body, row)
    with LOCK:
        # Re-check version inside the lock to enforce first-writer-wins
        # on concurrent same-version PATCH requests.
        row = DB["clients"].get(cid)
        if row is None:
            raise_error(ERR_NOT_FOUND, "Client not found")
        check_version(body, row)
        changed = False
        if "contact_email" in body:
            if not isinstance(body["contact_email"], str) or not body["contact_email"]:
                raise_error(ERR_VALIDATION, "contact_email must be a non-empty string")
            row["contact_email"] = body["contact_email"]
            changed = True
        if "contract_id" in body:
            ci = body["contract_id"]
            if ci is not None and not isinstance(ci, str):
                raise_error(ERR_VALIDATION, "contract_id must be string or null")
            row["contract_id"] = ci
            changed = True
        if changed:
            bump_version(row)
    return success_response(serialize_client(row), 200)
