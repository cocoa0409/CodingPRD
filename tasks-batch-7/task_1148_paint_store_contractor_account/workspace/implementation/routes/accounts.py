"""Contractor account endpoints."""
from flask import Blueprint

import db
import services as svc
from authz import require_roles, owner_or_forbid
from envelope import ok_object
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION
from serializers import ser_account
from validate import body_json, req_str, req_int, opt_str, opt_int

bp = Blueprint("accounts", __name__)

ADMIN = ["CorporateAdmin"]
READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "Contractor"]


def _get_account(account_id):
    a = db.contractor_accounts.get(account_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "contractor account %s not found" % account_id)
    return a


@bp.post("/contractor-accounts")
def create_account():
    require_roles(ADMIN)
    data = body_json()
    company_name = req_str(data, "company_name")
    credit_limit = req_int(data, "credit_limit_cents", minimum=0)
    account = svc.stamp_new({
        "company_name": company_name,
        "status": "ACTIVE",
        "tier": "STANDARD",
        "credit_limit_cents": credit_limit,
    })
    db.contractor_accounts[account["id"]] = account
    return ok_object(ser_account(account), 201)


@bp.get("/contractor-accounts/<account_id>")
def get_account(account_id):
    uid, role = require_roles(READERS)
    # Ownership is derivable from the path itself for this endpoint and is
    # checked ahead of path existence per the pipeline order.
    owner_or_forbid(uid, role, account_id)
    return ok_object(ser_account(_get_account(account_id)))


@bp.patch("/contractor-accounts/<account_id>")
def patch_account(account_id):
    require_roles(ADMIN)
    account = _get_account(account_id)
    data = body_json()
    expected = req_int(data, "expected_contractor_account_version")
    company_name = opt_str(data, "company_name")
    credit_limit = opt_int(data, "credit_limit_cents", minimum=0)
    if expected != account["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_contractor_account_version does not match the account's current version")
    if company_name is not None:
        account["company_name"] = company_name
    if credit_limit is not None:
        account["credit_limit_cents"] = credit_limit
    svc.bump(account)
    return ok_object(ser_account(account))


@bp.post("/contractor-accounts/<account_id>/suspend")
def suspend_account(account_id):
    require_roles(ADMIN)
    account = _get_account(account_id)
    if account["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "account is not ACTIVE")
    account["status"] = "SUSPENDED"
    svc.bump(account)
    return ok_object(ser_account(account))


@bp.post("/contractor-accounts/<account_id>/reinstate")
def reinstate_account(account_id):
    require_roles(ADMIN)
    account = _get_account(account_id)
    if account["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "account is not SUSPENDED")
    account["status"] = "ACTIVE"
    svc.bump(account)
    return ok_object(ser_account(account))


@bp.post("/contractor-accounts/<account_id>/evaluate-tier")
def evaluate_tier(account_id):
    from calc import tier_for_volume

    require_roles(ADMIN)
    account = _get_account(account_id)
    volume = svc.ytd_net_volume(account_id)
    new_tier = tier_for_volume(volume)
    if new_tier != account["tier"]:
        account["tier"] = new_tier
        svc.bump(account)
    return ok_object(ser_account(account))
