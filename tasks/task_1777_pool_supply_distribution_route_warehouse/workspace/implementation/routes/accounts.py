"""Account endpoints (PRD 3.2)."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import ALL_READ_ROLES, STAFF_ROLES, get_one, list_response, public
from services import new_record, touch
from validate import (
    get_body, opt_bool, opt_nullable_date, req_enum, req_str, require_path_resource,
)

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = {"DEALER", "SERVICE_CO"}
ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.post("/pool-supply/accounts")
def create_account():
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    body = get_body()
    rec = new_record("accounts", {
        "account_number": req_str(body, "account_number"),
        "account_type": req_enum(body, "account_type", ACCOUNT_TYPES),
        # tier / ytd_volume_cents are computed — client input is ignored
        "tier": "PRO",
        "ytd_volume_cents": 0,
        "hazmat_delivery_license_expiry": opt_nullable_date(body, "hazmat_delivery_license_expiry"),
        "willcall_authorized": opt_bool(body, "willcall_authorized", True),
        "credit_hold": opt_bool(body, "credit_hold", False),
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/pool-supply/accounts")
def list_accounts():
    filters = {
        "account_type": request.args.get("account_type"),
        "tier": request.args.get("tier"),
    }
    return list_response("accounts", STAFF_ROLES, filters)


@bp.get("/pool-supply/accounts/<rid>")
def get_account(rid):
    return get_one("accounts", rid, ALL_READ_ROLES)


@bp.patch("/pool-supply/accounts/<rid>")
def patch_account(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    account = require_path_resource("accounts", rid)
    body = get_body()
    changed = False
    if "credit_hold" in body and body["credit_hold"] is not None:
        v = body["credit_hold"]
        if not isinstance(v, bool):
            raise_error(ERR_INVALID_REQUEST, "credit_hold must be a boolean")
        if account["credit_hold"] != v:
            account["credit_hold"] = v
            changed = True
    if "willcall_authorized" in body and body["willcall_authorized"] is not None:
        v = body["willcall_authorized"]
        if not isinstance(v, bool):
            raise_error(ERR_INVALID_REQUEST, "willcall_authorized must be a boolean")
        if account["willcall_authorized"] != v:
            account["willcall_authorized"] = v
            changed = True
    if "hazmat_delivery_license_expiry" in body:
        v = opt_nullable_date(body, "hazmat_delivery_license_expiry")
        if account["hazmat_delivery_license_expiry"] != v:
            account["hazmat_delivery_license_expiry"] = v
            changed = True
    if "status" in body and body["status"] is not None:
        v = body["status"]
        if not isinstance(v, str) or v not in ACCOUNT_STATUSES:
            raise_error(ERR_INVALID_REQUEST, "status must be ACTIVE or SUSPENDED")
        if account["status"] != v:
            account["status"] = v
            changed = True
    if changed:
        touch(account)
    return success_object(public(account))
