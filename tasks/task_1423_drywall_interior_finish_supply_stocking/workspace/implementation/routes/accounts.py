"""ContractorAccount endpoints."""
from flask import Blueprint, request
from db import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_ACCOUNT_SUSPENDED, ERR_ACCOUNT_BALANCE_OPEN,
    ERR_ACCOUNT_NOT_ACTIVE, ERR_INVALID_STATE,
)
from middleware import require_roles
from response import success
from services.helpers import (
    parse_pagination, paginate, body, require_fields, require_int, require_str,
    new_common_fields, touch,
)

bp = Blueprint("accounts", __name__)


def _get_account_or_404(account_id):
    a = db.contractor_accounts.get(account_id)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "ContractorAccount not found", 404)
    return a


def _list_accounts(items, filters):
    out = []
    for a in items:
        if "status" in filters and filters["status"] is not None:
            if a["status"] != filters["status"]:
                continue
        out.append(a)
    out.sort(key=lambda x: (x["created_at"], x["id"]))
    return out


@bp.route("/supply/contractor-accounts", methods=["POST"])
def create_account():
    require_roles("CreditManager")
    b = body()
    require_fields(b, "company_name", "credit_limit_cents", "default_waste_pct_bp")
    company_name = require_str(b, "company_name")
    credit_limit_cents = require_int(b, "credit_limit_cents", min_val=0)
    default_waste_pct_bp = require_int(b, "default_waste_pct_bp", min_val=0, max_val=2000)
    acct = new_common_fields()
    acct.update({
        "company_name": company_name,
        "credit_limit_cents": credit_limit_cents,
        "default_waste_pct_bp": default_waste_pct_bp,
        "ar_outstanding_cents": 0,
        "status": "ACTIVE",
    })
    db.contractor_accounts[acct["id"]] = acct
    return success(acct, status=201)


@bp.route("/supply/contractor-accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    require_roles(
        "CreditManager", "EstimatorUser", "DispatcherUser", "Foreman",
        "AccountsReceivableUser", "WarehouseManager",
    )
    a = _get_account_or_404(account_id)
    return success(a)


@bp.route("/supply/contractor-accounts", methods=["GET"])
def list_accounts():
    require_roles("CreditManager", "AccountsReceivableUser")
    limit, offset = parse_pagination()
    filters = {"status": request.args.get("status")}
    items = _list_accounts(list(db.contractor_accounts.values()), filters)
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/contractor-accounts/<account_id>/suspend", methods=["POST"])
def suspend_account(account_id):
    require_roles("CreditManager")
    a = _get_account_or_404(account_id)
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, "Account must be ACTIVE to suspend", 409)
    a["status"] = "SUSPENDED"
    touch(a)
    # Cancel all DRAFT takeoffs on this account's projects
    for t in db.takeoffs.values():
        if t["status"] == "DRAFT":
            proj = db.projects.get(t["project_id"])
            if proj and proj["account_id"] == account_id:
                t["status"] = "CANCELLED"
                touch(t)
    return success(a)


@bp.route("/supply/contractor-accounts/<account_id>/reinstate", methods=["POST"])
def reinstate_account(account_id):
    require_roles("CreditManager")
    a = _get_account_or_404(account_id)
    if a["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Account must be SUSPENDED to reinstate", 409)
    if a["ar_outstanding_cents"] > a["credit_limit_cents"]:
        raise ApiError(
            ERR_ACCOUNT_BALANCE_OPEN,
            "Outstanding AR exceeds credit limit; cannot reinstate",
            409,
        )
    a["status"] = "ACTIVE"
    touch(a)
    return success(a)


@bp.route("/supply/contractor-accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    require_roles("CreditManager")
    a = _get_account_or_404(account_id)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "Account must be ACTIVE or SUSPENDED to close", 409)
    if a["ar_outstanding_cents"] != 0:
        raise ApiError(
            ERR_ACCOUNT_BALANCE_OPEN,
            "Account has non-zero AR balance",
            409,
        )
    a["status"] = "CLOSED"
    touch(a)
    # Cascade: cancel non-terminal projects and their non-terminal stocking orders
    for p in db.projects.values():
        if p["account_id"] == account_id and p["status"] not in ("STOCKING_CLOSED", "CANCELLED"):
            p["status"] = "CANCELLED"
            touch(p)
            # Cancel non-terminal takeoffs
            for t in db.takeoffs.values():
                if t["project_id"] == p["id"] and t["status"] not in ("LOCKED", "CANCELLED"):
                    t["status"] = "CANCELLED"
                    touch(t)
            # Cancel non-terminal stocking orders
            for o in db.stocking_orders.values():
                if o["project_id"] == p["id"] and o["status"] not in ("STOCKED", "CANCELLED"):
                    o["status"] = "CANCELLED"
                    touch(o)
    return success(a)
