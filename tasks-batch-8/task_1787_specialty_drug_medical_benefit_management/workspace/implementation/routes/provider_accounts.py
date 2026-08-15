"""Provider account endpoints (PRD 2.10, 3.3)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_PROVIDER_NOT_ON_HOLD
from middleware import authorized
from response import success_object
from routes.helpers import (
    apply_filters, check_single_scope, get_body, get_or_404, list_response,
    public, read_all, req_str, stamp_new,
)
from services.pricing import touch
from util import new_id

bp = Blueprint("provider_accounts", __name__)

ACCOUNT_LIST_ROLES = ["PlanAdmin", "MedicalPolicyOfficer", "CaseManager", "PharmacyAnalyst"]


@bp.post("/api/provider-accounts")
def create_account():
    authorized(["PlanAdmin"])
    body = get_body()
    name = req_str(body, "name")
    rec = {
        "id": new_id(),
        "name": name,
        "status": "ACTIVE",
        "cumulative_paid_cents": 0,
        "recoupment_balance_cents": 0,
    }
    stamp_new(rec)
    db["provider_accounts"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.get("/api/provider-accounts")
def list_accounts():
    # the account collection is not exposed to provider representatives
    authorized(ACCOUNT_LIST_ROLES)
    items = list(db["provider_accounts"].values())
    items = apply_filters(items, ["status"])
    return list_response(items)


@bp.get("/api/provider-accounts/<accountId>")
def get_account(accountId):
    caller = read_all()
    rec = get_or_404("provider_accounts", accountId)
    # a ProviderRep may read only its own account
    check_single_scope(caller, rec["id"])
    return success_object(public(rec))


@bp.post("/api/provider-accounts/<accountId>/settle-recoupment")
def settle_recoupment(accountId):
    authorized(["PlanAdmin"])
    rec = get_or_404("provider_accounts", accountId)
    if rec["status"] != "RECOUPMENT_HOLD":
        raise_error(ERR_PROVIDER_NOT_ON_HOLD, "settle-recoupment requires RECOUPMENT_HOLD")
    rec["recoupment_balance_cents"] = 0
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(public(rec))
