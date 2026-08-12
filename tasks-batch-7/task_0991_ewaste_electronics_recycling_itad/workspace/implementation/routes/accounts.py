"""BusinessAccount endpoints (PRD §3.1, §3.9)."""

from decimal import Decimal

from flask import Blueprint

import db
import serialize
import utils
from errors import (ApiError, ERR_ACCOUNT_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_VALIDATION)
from middleware import require_roles, check_owns_account
from response import ok_object, paginate, sort_created
from services import calculations as calc

bp = Blueprint("accounts", __name__)

MANIFEST_STATUSES = {"DRAFT", "SCHEDULED", "RECEIVED", "RECONCILED", "CLOSED", "CANCELLED"}


def get_account_or_404(account_id):
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 404, "no BusinessAccount with the given id")
    return account


@bp.post("/itad/accounts")
def create_account():
    uid, role = require_roles("PlatformAdmin")
    data = utils.body_json()
    company_name = utils.req_str(data, "company_name")
    contact_email = utils.req_str(data, "contact_email")
    tier = utils.req_enum(data, "tier", calc.TIERS) if utils.has_field(data, "tier") else "STANDARD"
    account = {
        "id": utils.new_id(),
        "company_name": company_name,
        "contact_email": contact_email,
        "tier": tier,
        "status": "ACTIVE",
        "credit_balance_cents": 0,
        "lifetime_diverted_kg": Decimal("0"),
    }
    utils.stamp_new(account)
    db.accounts[account["id"]] = account
    return ok_object(serialize.account(account), code=201)


@bp.get("/itad/accounts/<account_id>")
def read_account(account_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "ComplianceOfficer")
    account = get_account_or_404(account_id)
    check_owns_account(uid, role, account["id"])
    return ok_object(serialize.account(account))


@bp.patch("/itad/accounts/<account_id>")
def update_account(account_id):
    uid, role = require_roles("PlatformAdmin")
    account = get_account_or_404(account_id)
    data = utils.body_json()
    tier = utils.req_enum(data, "tier", calc.TIERS) if utils.has_field(data, "tier") else None
    status = None
    if utils.has_field(data, "status"):
        status = utils.req_enum(data, "status", {"ACTIVE", "SUSPENDED", "CLOSED"})
    if tier is None and status is None:
        raise ApiError(ERR_VALIDATION, 400, "nothing to update: supply tier and/or status")

    if status is not None:
        current = account["status"]
        allowed = {("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"), ("ACTIVE", "CLOSED")}
        if (current, status) not in allowed:
            raise ApiError(ERR_INVALID_STATE, 409,
                           f"account status transition {current} -> {status} is not allowed")
        if status == "CLOSED":
            open_manifest = any(
                m["status"] not in ("CLOSED", "CANCELLED")
                for m in db.manifests.values() if m["account_id"] == account["id"]
            )
            if open_manifest:
                raise ApiError(ERR_INVALID_STATE, 409,
                               "account has manifests outside CLOSED/CANCELLED")
            if account["credit_balance_cents"] != 0:
                raise ApiError(ERR_INVALID_STATE, 409,
                               "account credit balance must be zero to close")
        account["status"] = status
    if tier is not None:
        account["tier"] = tier
    utils.touch(account)
    return ok_object(serialize.account(account))


@bp.get("/itad/accounts/<account_id>/manifests")
def list_account_manifests(account_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager")
    account = get_account_or_404(account_id)
    check_owns_account(uid, role, account["id"])
    records = [m for m in db.manifests.values() if m["account_id"] == account["id"]]
    from flask import request
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in MANIFEST_STATUSES:
            raise ApiError(ERR_VALIDATION, 400, "invalid status filter")
        records = [m for m in records if m["status"] == status_filter]
    records = sort_created(records)
    return paginate([serialize.manifest(m) for m in records])


@bp.get("/itad/accounts/<account_id>/ledger-entries")
def list_account_ledger(account_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager")
    account = get_account_or_404(account_id)
    check_owns_account(uid, role, account["id"])
    records = sort_created(
        [e for e in db.ledger_entries.values() if e["account_id"] == account["id"]]
    )
    return paginate([serialize.ledger_entry(e) for e in records])


@bp.get("/itad/accounts/<account_id>/sustainability-report")
def sustainability_report(account_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "ComplianceOfficer")
    account = get_account_or_404(account_id)
    check_owns_account(uid, role, account["id"])
    return ok_object(calc.sustainability_report(account["id"]))
