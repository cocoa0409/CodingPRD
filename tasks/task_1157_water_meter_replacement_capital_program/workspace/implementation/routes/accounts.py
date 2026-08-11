"""Service account endpoints (PRD 3.2)."""
import db
from db import base_resource
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import get_or_404, list_page, ser_account
from flask import Blueprint, request
from validate import body, opt_enum, req_dt, req_enum, req_int, req_number, req_str

bp = Blueprint("accounts", __name__)

METER_LOCATIONS = ("INSIDE", "OUTSIDE")
PRIORITY_TIERS = ("STANDARD", "SENSITIVE", "CRITICAL")


@bp.post("/api/accounts")
@require_roles("Scheduler")
def create_account():
    b = body()
    account_number = req_str(b, "account_number")
    service_address = req_str(b, "service_address")
    meter_location = req_enum(b, "meter_location", METER_LOCATIONS)
    customer_name = req_str(b, "customer_name")
    customer_phone = req_str(b, "customer_phone")
    priority_tier = opt_enum(b, "priority_tier", PRIORITY_TIERS, default="STANDARD")
    avg_daily_usage = req_number(b, "avg_daily_usage_ccf", min=0)
    last_billed_value = req_int(b, "last_billed_read_value", min=0)
    last_billed_at = req_dt(b, "last_billed_read_at")
    # Uniqueness (stage 6).
    for a in db.accounts.values():
        if a["account_number"] == account_number:
            raise_err("ERR_ACCOUNT_NUMBER_CONFLICT",
                      "account_number already registered")
    a = base_resource()
    a.update({
        "account_number": account_number,
        "service_address": service_address,
        "meter_location": meter_location,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "priority_tier": priority_tier,
        "avg_daily_usage_ccf": avg_daily_usage,
        "last_billed_read_value": last_billed_value,
        "last_billed_read_at": last_billed_at,
        "status": "ELIGIBLE",
    })
    db.accounts[a["id"]] = a
    return ok_object(ser_account(a), 201)


@bp.get("/api/accounts")
@require_roles(*ALL_ROLES)
def list_accounts():
    filters = {}
    for k in ("status", "meter_location", "priority_tier"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.accounts.values(), filters, ser_account)


@bp.get("/api/accounts/<accountId>")
@require_roles(*ALL_ROLES)
def get_account(accountId):
    return ok_object(ser_account(get_or_404(db.accounts, accountId, "ServiceAccount")))
