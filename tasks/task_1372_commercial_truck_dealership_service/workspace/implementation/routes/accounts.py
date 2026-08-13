"""CustomerAccount endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import store, stamp_new, touch
from errors import err_not_found, err_invalid, err_stale, ApiError
from helpers import (body, req_str, req_enum, opt_enum, req_int, opt_int,
                     paginate, sort_created, apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import customer_account as ser

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = {"FLEET", "RETAIL"}
FLEET_TIERS = {"STANDARD", "GOLD", "PLATINUM"}
ACCOUNT_STATUSES = {"ACTIVE", "CREDIT_HOLD", "CLOSED"}


@bp.post("/dealership/customer-accounts")
def create_account():
    caller(["SalesManager"])
    data = body()
    name = req_str(data, "account_name")
    atype = req_enum(data, "account_type", ACCOUNT_TYPES)
    tier = opt_enum(data, "fleet_tier", FLEET_TIERS, "STANDARD")
    credit = opt_int(data, "credit_limit_cents", 0, minimum=0)
    account = {
        "account_name": name,
        "account_type": atype,
        "fleet_tier": tier,
        "credit_limit_cents": credit,
        "open_ar_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(account)
    store.customer_accounts[account["id"]] = account
    return success(ser(account), status=201)


@bp.get("/dealership/customer-accounts")
def list_accounts():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.customer_accounts.values()), [
        ("account_type", request.args.get("account_type")),
        ("fleet_tier", request.args.get("fleet_tier")),
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([ser(a) for a in page], meta)


@bp.get("/dealership/customer-accounts/<rid>")
def get_account(rid):
    caller(ALL_ROLES)
    account = store.customer_accounts.get(rid)
    if account is None:
        raise err_not_found("CUSTOMER_ACCOUNT")
    return success(ser(account))


@bp.patch("/dealership/customer-accounts/<rid>")
def patch_account(rid):
    caller(["SalesManager"])
    data = body()
    # Body well-formedness (priority 4) before existence (5) and OCC (6).
    expected = req_int(data, "expected_customer_account_version")
    tier = opt_enum(data, "fleet_tier", FLEET_TIERS)
    credit = opt_int(data, "credit_limit_cents", None, minimum=0)
    status = opt_enum(data, "status", ACCOUNT_STATUSES)

    account = store.customer_accounts.get(rid)
    if account is None:
        raise err_not_found("CUSTOMER_ACCOUNT")
    if expected != account["version"]:
        raise err_stale()
    if status == "CLOSED" and account["open_ar_cents"] != 0:
        raise ApiError("ERR_ACCOUNT_ON_CREDIT_HOLD", 409,
                       "Cannot close an account with an open receivable")

    if tier is not None:
        account["fleet_tier"] = tier
    if credit is not None:
        account["credit_limit_cents"] = credit
    if status is not None:
        account["status"] = status
    touch(account)
    return success(ser(account))
