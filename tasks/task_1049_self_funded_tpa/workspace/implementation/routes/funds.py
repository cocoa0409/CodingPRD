from flask import Blueprint, request

import errors
import serializers
from errors import fail
from auth import require_auth, ANY_ROLE
from store import db, new_id, stamp_new, touch, now_iso
from envelope import ok, created, list_response
from validation import (
    get_body, require_str, require_int_nonneg, require_id_list, parse_pagination,
)

bp = Blueprint("funds", __name__)


# ------------------------------------------------------------------ FundAccount
@bp.post("/fund-accounts")
def create_fund():
    require_auth({"FundManager"})
    body = get_body()
    plan_id = require_str(body, "plan_id")
    if plan_id not in db.plans:
        fail(errors.ERR_PLAN_NOT_FOUND, "Plan not found")
    f = {
        "id": new_id(),
        "plan_id": plan_id,
        "balance_cents": 0,
        "total_deposited_cents": 0,
        "total_disbursed_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(f)
    db.funds[f["id"]] = f
    return created(serializers.fund(f))


@bp.get("/fund-accounts/<fid>")
def get_fund(fid):
    require_auth(ANY_ROLE)
    f = db.funds.get(fid)
    if not f:
        fail(errors.ERR_FUND_ACCOUNT_NOT_FOUND, "Fund account not found")
    return ok(serializers.fund(f))


@bp.get("/fund-accounts")
def list_funds():
    require_auth(ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(db.funds.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [f for f in items if f["plan_id"] == plan_id]
    return list_response(items, serializers.fund, limit, offset)


@bp.post("/fund-accounts/<fid>/deposit")
def deposit_fund(fid):
    require_auth({"FundManager"})
    f = db.funds.get(fid)
    if not f:
        fail(errors.ERR_FUND_ACCOUNT_NOT_FOUND, "Fund account not found")
    body = get_body()
    amount = require_int_nonneg(body, "amount_cents")
    f["balance_cents"] += amount
    f["total_deposited_cents"] += amount
    touch(f)
    return ok(serializers.fund(f))


@bp.get("/fund-accounts/<fid>/check-runs")
def list_fund_checkruns(fid):
    require_auth(ANY_ROLE)
    f = db.funds.get(fid)
    if not f:
        fail(errors.ERR_FUND_ACCOUNT_NOT_FOUND, "Fund account not found")
    limit, offset = parse_pagination()
    items = [cr for cr in db.checkruns.values() if cr["fund_account_id"] == fid]
    return list_response(items, serializers.checkrun, limit, offset)


# --------------------------------------------------------------------- CheckRun
@bp.post("/check-runs")
def create_checkrun():
    require_auth({"FundManager"})
    body = get_body()
    fund_account_id = require_str(body, "fund_account_id")
    if fund_account_id not in db.funds:
        fail(errors.ERR_FUND_ACCOUNT_NOT_FOUND, "Fund account not found")
    claim_ids = require_id_list(body, "claim_ids")
    for cid in claim_ids:
        if cid not in db.claims:
            fail(errors.ERR_CLAIM_NOT_FOUND, "Claim not found")
    # no claim already held by a live (DRAFT/RELEASED) check-run
    held = set()
    for cr in db.checkruns.values():
        if cr["status"] in ("DRAFT", "RELEASED"):
            held.update(cr["claim_ids"])
    for cid in claim_ids:
        if cid in held:
            fail(errors.ERR_CLAIM_ALREADY_IN_CHECK_RUN, "Claim already in a live check-run")

    total = sum((db.claims[cid]["plan_paid_cents"] or 0) for cid in claim_ids)
    cr = {
        "id": new_id(),
        "fund_account_id": fund_account_id,
        "claim_ids": list(claim_ids),
        "total_amount_cents": total,
        "released_at": None,
        "status": "DRAFT",
    }
    stamp_new(cr)
    db.checkruns[cr["id"]] = cr
    return created(serializers.checkrun(cr))


@bp.get("/check-runs/<crid>")
def get_checkrun(crid):
    require_auth(ANY_ROLE)
    cr = db.checkruns.get(crid)
    if not cr:
        fail(errors.ERR_CHECK_RUN_NOT_FOUND, "Check-run not found")
    return ok(serializers.checkrun(cr))


@bp.post("/check-runs/<crid>/release")
def release_checkrun(crid):
    require_auth({"FundManager"})
    cr = db.checkruns.get(crid)
    if not cr:
        fail(errors.ERR_CHECK_RUN_NOT_FOUND, "Check-run not found")
    body = get_body()
    expected_version = require_int_nonneg(body, "expected_fund_account_version")
    f = db.funds[cr["fund_account_id"]]

    # (4) state: check-run DRAFT
    if cr["status"] != "DRAFT":
        fail(errors.ERR_INVALID_STATE, "Check-run is not DRAFT")
    # (4) state: every claim ADJUDICATED
    claims = [db.claims[cid] for cid in cr["claim_ids"]]
    for c in claims:
        if c["status"] != "ADJUDICATED":
            fail(errors.ERR_CLAIM_NOT_ADJUDICATED, "A check-run claim is not ADJUDICATED")
    # (5) concurrency: OCC on fund version
    if expected_version != f["version"]:
        fail(errors.ERR_STALE_VERSION, "Fund account version is stale")
    # (10) fiscal: sufficient balance
    if f["balance_cents"] < cr["total_amount_cents"]:
        fail(errors.ERR_INSUFFICIENT_FUNDS, "Insufficient fund balance for check-run")

    stamp = now_iso()
    cr["released_at"] = stamp
    cr["status"] = "RELEASED"
    for c in claims:
        c["status"] = "PAID"
        c["paid_at"] = stamp
        provider = db.providers[c["provider_id"]]
        provider["ytd_paid_cents"] += c["plan_paid_cents"]
        touch(provider)
        touch(c)
    f["balance_cents"] -= cr["total_amount_cents"]
    f["total_disbursed_cents"] += cr["total_amount_cents"]
    touch(f)  # increments fund version
    touch(cr)
    return ok(serializers.checkrun(cr))


@bp.post("/check-runs/<crid>/void")
def void_checkrun(crid):
    require_auth({"FundManager"})
    cr = db.checkruns.get(crid)
    if not cr:
        fail(errors.ERR_CHECK_RUN_NOT_FOUND, "Check-run not found")
    if cr["status"] not in ("DRAFT", "RELEASED"):
        fail(errors.ERR_INVALID_STATE, "Check-run cannot be voided")

    if cr["status"] == "RELEASED":
        f = db.funds[cr["fund_account_id"]]
        for cid in cr["claim_ids"]:
            c = db.claims[cid]
            c["status"] = "ADJUDICATED"
            c["paid_at"] = None
            provider = db.providers[c["provider_id"]]
            provider["ytd_paid_cents"] -= c["plan_paid_cents"]
            touch(provider)
            touch(c)
        f["balance_cents"] += cr["total_amount_cents"]
        f["total_disbursed_cents"] -= cr["total_amount_cents"]
        touch(f)  # increments fund version

    cr["status"] = "VOIDED"
    touch(cr)
    return ok(serializers.checkrun(cr))
