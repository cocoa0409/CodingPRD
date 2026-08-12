"""Funding account and ledger entry endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import (err, ERR_FUNDING_ACCOUNT_NOT_FOUND, ERR_EMPLOYER_NOT_FOUND,
                    ERR_CLAIM_NOT_FOUND, ERR_INVALID_AMOUNT, ERR_FUNDING_NOT_ACTIVE)
from middleware import require_roles
from response import success, paginate
from services.core import new_entity, touch, serialize, sort_created, append_funding_entry
from util import body_json, req, as_str, as_int, check_positive

bp = Blueprint("funding", __name__)


def get_account(aid):
    a = STORE.funding_accounts.get(aid)
    if a is None:
        raise err(ERR_FUNDING_ACCOUNT_NOT_FOUND, 404, "funding account id does not resolve")
    return a


@bp.post("/api/funding-accounts")
def create_account():
    require_roles("BenefitsAdmin")
    body = body_json()
    employer_id = as_str(req(body, "employer_id"), "employer_id")
    benefit_year = as_int(req(body, "benefit_year"), "benefit_year")
    initial = as_int(req(body, "initial_deposit_cents"), "initial_deposit_cents")
    if employer_id not in STORE.employers:
        raise err(ERR_EMPLOYER_NOT_FOUND, 404, "employer id does not resolve")
    if initial < 0:
        raise err(ERR_INVALID_AMOUNT, 400, "initial_deposit_cents must be zero or greater")
    a = new_entity()
    a.update({
        "employer_id": employer_id,
        "benefit_year": benefit_year,
        "funded_cents": 0,
        "available_cents": 0,
        "reserved_cents": 0,
        "disbursed_cents": 0,
        "status": "FUNDED",
    })
    STORE.funding_accounts[a["id"]] = a
    if initial > 0:
        append_funding_entry(a, None, "DEPOSIT", initial)
    return success(serialize(a), 201)


@bp.get("/api/funding-accounts/<aid>")
def read_account(aid):
    require_roles("BenefitsAdmin", "Auditor")
    return success(serialize(get_account(aid)))


@bp.get("/api/funding-accounts")
def list_accounts():
    require_roles("BenefitsAdmin", "Auditor")
    items = sort_created(STORE.funding_accounts.values())
    employer_id = request.args.get("employer_id")
    if employer_id is not None:
        items = [a for a in items if a["employer_id"] == employer_id]
    return paginate([serialize(a) for a in items])


@bp.post("/api/funding-accounts/<aid>/deposits")
def deposit(aid):
    require_roles("BenefitsAdmin")
    a = get_account(aid)
    body = body_json()
    amount = check_positive(as_int(req(body, "amount_cents"), "amount_cents"), "amount_cents")
    entry = append_funding_entry(a, None, "DEPOSIT", amount)
    return success(serialize(entry), 201)


@bp.get("/api/funding-accounts/<aid>/entries")
def list_entries(aid):
    require_roles("BenefitsAdmin", "Auditor")
    get_account(aid)
    items = [e for e in sort_created(STORE.funding_entries.values())
             if e["funding_account_id"] == aid]
    return paginate([serialize(e) for e in items])


@bp.post("/api/funding-accounts/<aid>/suspend")
def suspend_account(aid):
    require_roles("BenefitsAdmin")
    a = get_account(aid)
    if a["status"] not in ("FUNDED", "DEPLETED"):
        raise err(ERR_FUNDING_NOT_ACTIVE, 409, "suspend requires FUNDED or DEPLETED")
    a["status"] = "SUSPENDED"
    touch(a)
    return success(serialize(a))


@bp.post("/api/funding-accounts/<aid>/reactivate")
def reactivate_account(aid):
    require_roles("BenefitsAdmin")
    a = get_account(aid)
    if a["status"] != "SUSPENDED":
        raise err(ERR_FUNDING_NOT_ACTIVE, 409, "reactivate requires SUSPENDED")
    # target posture derived from balance, not caller preference
    a["status"] = "FUNDED" if a["available_cents"] > 0 else "DEPLETED"
    touch(a)
    return success(serialize(a))


@bp.get("/api/claims/<cid>/funding-entries")
def claim_entries(cid):
    require_roles("BenefitsAdmin", "Auditor", "ClaimsReviewer")
    if cid not in STORE.claims:
        raise err(ERR_CLAIM_NOT_FOUND, 404, "claim id does not resolve")
    items = [e for e in sort_created(STORE.funding_entries.values())
             if e["claim_id"] == cid]
    return paginate([serialize(e) for e in items])
