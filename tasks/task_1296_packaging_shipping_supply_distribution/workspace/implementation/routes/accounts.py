"""Account endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import (err_invalid_request, err_not_found, err_invalid_state)
from middleware import (require_roles, get_json_body, require_str, require_int,
                        optional_bool, check_account_ownership, scoped_account_id)
from response import success_object, success_list, parse_pagination, paginate
from serializers import ser_account
from util import is_int

bp = Blueprint("accounts", __name__)
PREFIX = "/packaging-distribution"

ACCOUNT_TYPES = {"CORPORATE", "RETAIL"}
WAREHOUSE_CODES = {"ATL", "RNO", "DFW"}
ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED"}


def _warehouse_code_exists(code):
    return any(w["code"] == code for w in db.warehouses.values())


def _validate_warehouse_code(value):
    if not isinstance(value, str) or value not in WAREHOUSE_CODES:
        raise err_invalid_request("Field 'default_warehouse_code' must be one of ATL | RNO | DFW.")
    if not _warehouse_code_exists(value):
        raise err_not_found("Referenced warehouse does not exist in the registry.")
    return value


def _get_account(account_id):
    a = db.accounts.get(account_id)
    if a is None:
        raise err_not_found("Account not found.")
    return a


@bp.route(f"{PREFIX}/accounts", methods=["POST"])
@require_roles("PlatformAdmin")
def create_account():
    body = get_json_body(required=True)
    company_name = require_str(body, "company_name")
    account_type = require_str(body, "account_type")
    if account_type not in ACCOUNT_TYPES:
        raise err_invalid_request("Field 'account_type' must be CORPORATE or RETAIL.")
    credit_limit_cents = require_int(body, "credit_limit_cents")
    if credit_limit_cents < 0:
        raise err_invalid_request("Field 'credit_limit_cents' must be >= 0.")
    po_required = optional_bool(body, "po_required")
    if po_required is None:
        po_required = False
    if "default_warehouse_code" not in body or body["default_warehouse_code"] is None:
        raise err_invalid_request("Missing required field: default_warehouse_code.")
    default_warehouse_code = _validate_warehouse_code(body["default_warehouse_code"])

    now = db.now()
    a = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "company_name": company_name,
        "account_type": account_type,
        "status": "ACTIVE",
        "credit_limit_cents": credit_limit_cents,
        "po_required": po_required,
        "default_warehouse_code": default_warehouse_code,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.accounts[a["id"]] = a
    return success_object(ser_account(a), status=201)


@bp.route(f"{PREFIX}/accounts", methods=["GET"])
@require_roles("PlatformAdmin", "CustomerService")
def list_accounts():
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    type_f = request.args.get("account_type")
    if status_f is not None and status_f not in ACCOUNT_STATUSES:
        raise err_invalid_request("Invalid 'status' filter.")
    if type_f is not None and type_f not in ACCOUNT_TYPES:
        raise err_invalid_request("Invalid 'account_type' filter.")
    items = sorted(db.accounts.values(), key=lambda a: (a["created_at"], a["_seq"]))
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if type_f is not None:
        items = [a for a in items if a["account_type"] == type_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_account(a) for a in page], pagination)


@bp.route(f"{PREFIX}/accounts/<account_id>", methods=["GET"])
@require_roles("PlatformAdmin", "CustomerService", "AccountApprover", "Buyer")
def get_account(account_id):
    # For entity-backed roles the path id IS the account id: ownership (403)
    # is decidable without a fetch and outranks existence (404).
    check_account_ownership(account_id)
    a = _get_account(account_id)
    return success_object(ser_account(a))


@bp.route(f"{PREFIX}/accounts/<account_id>", methods=["PATCH"])
@require_roles("PlatformAdmin")
def patch_account(account_id):
    a = _get_account(account_id)
    body = get_json_body(required=True)
    if "credit_limit_cents" in body and body["credit_limit_cents"] is not None:
        v = body["credit_limit_cents"]
        if not is_int(v):
            raise err_invalid_request("Field 'credit_limit_cents' must be an integer.")
        if v < 0:
            raise err_invalid_request("Field 'credit_limit_cents' must be >= 0.")
        a["credit_limit_cents"] = v
    if "po_required" in body and body["po_required"] is not None:
        v = body["po_required"]
        if not isinstance(v, bool):
            raise err_invalid_request("Field 'po_required' must be a boolean.")
        a["po_required"] = v
    if "default_warehouse_code" in body and body["default_warehouse_code"] is not None:
        a["default_warehouse_code"] = _validate_warehouse_code(body["default_warehouse_code"])
    db.touch(a)
    return success_object(ser_account(a))


@bp.route(f"{PREFIX}/accounts/<account_id>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_account(account_id):
    a = _get_account(account_id)
    if a["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE account can be suspended.")
    a["status"] = "SUSPENDED"
    db.touch(a)
    return success_object(ser_account(a))


@bp.route(f"{PREFIX}/accounts/<account_id>/reactivate", methods=["POST"])
@require_roles("PlatformAdmin")
def reactivate_account(account_id):
    a = _get_account(account_id)
    if a["status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED account can be reactivated.")
    a["status"] = "ACTIVE"
    db.touch(a)
    return success_object(ser_account(a))
