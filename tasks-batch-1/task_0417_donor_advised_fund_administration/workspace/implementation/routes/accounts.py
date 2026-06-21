"""DonorAccount endpoints: open, read, summary, wind-down, execute-succession
(PRD 3.4, 3.8). Includes the PROJECTED grantable variant and the legacy split.
"""
from decimal import Decimal

from flask import Blueprint, request

from db import db, common_create_fields, touch, LOCK
from errors import err
from middleware import get_identity, require_role, get_json_body, get_pagination, paginate
from response import object_response, array_response
from services import calc, serialize
from services.accounts import recompute_account, post_ledger
from services.lookup import get_or_404, require_string, filtered_sorted

bp = Blueprint("accounts", __name__)

OPEN_ROLES = {"SponsorAdmin", "DonorAdvisor"}
GET_ROLES = {"SponsorAdmin", "DonorAdvisor", "GrantOfficer", "ContributionAdmin", "ComplianceOfficer"}
LIST_ROLES = {"SponsorAdmin", "DonorAdvisor", "GrantOfficer"}
SUMMARY_ROLES = {"SponsorAdmin", "DonorAdvisor", "GrantOfficer"}
GRANT_OPEN_STATES = {"SUBMITTED", "APPROVED", "SCHEDULED"}


@bp.post("/daf/accounts")
def open_account():
    _, role = get_identity()
    require_role(role, OPEN_ROLES)
    body = get_json_body()
    sponsor_id = require_string(body, "sponsor_id")
    account_name = require_string(body, "account_name")
    primary_advisor_user_id = require_string(body, "primary_advisor_user_id")

    with LOCK:
        get_or_404(db.sponsors, sponsor_id)  # body FK existence
        account = common_create_fields()
        account.update({
            "sponsor_id": sponsor_id,
            "account_name": account_name,
            "primary_advisor_user_id": primary_advisor_user_id,
            "cash_balance_cents": 0,
            "invested_value_cents": 0,
            "committed_grants_cents": 0,
            "admin_fee_accrued_cents": 0,
            "grantable_balance_cents": 0,
            "last_grant_paid_quarter": None,
            "status": "ACTIVE",
        })
        db.accounts[account["id"]] = account
    return object_response(serialize.account(account), status=201)


@bp.get("/daf/accounts/<account_id>")
def get_account(account_id):
    _, role = get_identity()
    require_role(role, GET_ROLES)
    account = get_or_404(db.accounts, account_id)
    return object_response(serialize.account(account))


@bp.get("/daf/accounts")
def list_accounts():
    _, role = get_identity()
    require_role(role, LIST_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.accounts, {
        "sponsor_id": request.args.get("sponsor_id"),
        "status": request.args.get("status"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.account(a) for a in page], meta)


@bp.get("/daf/accounts/<account_id>/summary")
def account_summary(account_id):
    _, role = get_identity()
    require_role(role, SUMMARY_ROLES)
    account = get_or_404(db.accounts, account_id)
    projection = request.args.get("projection")
    data = serialize.account(account)
    if projection == "PROJECTED":
        # PROJECTED (PRD 3.4): settled grantable + sum of provisional FMV of each
        # PENDING contribution, valued by the same FMV formula on its current inputs.
        provisional = 0
        for c in db.contributions.values():
            if c["donor_account_id"] == account_id and c["status"] == "PENDING":
                provisional += calc.contribution_fmv(c)
        data["grantable_balance_cents"] = account["grantable_balance_cents"] + provisional
    return object_response(data)


@bp.post("/daf/accounts/<account_id>/wind-down")
def wind_down(account_id):
    _, role = get_identity()
    require_role(role, {"SponsorAdmin"})
    with LOCK:
        account = get_or_404(db.accounts, account_id)
        # Wind-down permitted only from ACTIVE or INACTIVE (state precedes business rule).
        if account["status"] not in ("ACTIVE", "INACTIVE"):
            raise err("ERR_INVALID_STATE")
        # Requires a CONFIRMED LEGACY_GRANTS succession plan (PRD 3.8).
        if not _has_confirmed_legacy_plan(account_id):
            raise err("ERR_NO_CONFIRMED_SUCCESSION")
        account["status"] = "WIND_DOWN"
        touch(account)
    return object_response(serialize.account(account))


@bp.post("/daf/accounts/<account_id>/execute-succession")
def execute_succession(account_id):
    _, role = get_identity()
    require_role(role, {"SponsorAdmin"})
    with LOCK:
        account = get_or_404(db.accounts, account_id)
        # PRD 3.8 / 3.10 ordering: WIND_DOWN gate, then pending grants, then
        # beneficiary vetting.
        if account["status"] != "WIND_DOWN":
            raise err("ERR_ACCOUNT_NOT_IN_WIND_DOWN")
        for g in db.grants.values():
            if g["donor_account_id"] == account_id and g["status"] in GRANT_OPEN_STATES:
                raise err("ERR_PENDING_GRANTS_BLOCK_CLOSE")

        plan = _confirmed_legacy_plan(account_id)
        # Defensive: a wind-down account always has a confirmed plan, but guard anyway.
        if plan is None:
            raise err("ERR_NO_CONFIRMED_SUCCESSION")
        beneficiaries = plan["beneficiaries"]
        for b in beneficiaries:
            charity = db.charities.get(b["charity_id"])
            if charity is None or charity["status"] != "VETTED":
                raise err("ERR_SUCCESSION_BENEFICIARY_NOT_VETTED")

        # Liquidate all pool allocations to cash (PRD 3.8).
        _liquidate_all_allocations(account)
        recompute_account(account)
        residual = account["grantable_balance_cents"]

        # Largest-remainder split conserving every cent (PRD 3.8 / legacy_split).
        shares = _legacy_split(residual, beneficiaries)
        for b in beneficiaries:
            share = shares[b["charity_id"]]
            post_ledger(account, "LEGACY_DISBURSEMENT", -share, "Charity", b["charity_id"])
        account["cash_balance_cents"] = 0
        recompute_account(account)

        plan["status"] = "EXECUTED"
        touch(plan)
        account["status"] = "CLOSED"
        touch(account)
    return object_response(serialize.account(account))


def _has_confirmed_legacy_plan(account_id):
    return _confirmed_legacy_plan(account_id) is not None


def _confirmed_legacy_plan(account_id):
    candidates = [p for p in db.succession_plans.values()
                  if p["donor_account_id"] == account_id
                  and p["plan_type"] == "LEGACY_GRANTS"
                  and p["status"] == "CONFIRMED"]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p["_seq"])
    return candidates[0]


def _liquidate_all_allocations(account):
    """Redeem every ACTIVE allocation fully to cash (PRD 3.8). For the redeem leg
    cash credited == invested value debited, so cash+invested is conserved."""
    for a in db.allocations.values():
        if a["donor_account_id"] != account["id"] or a["status"] != "ACTIVE":
            continue
        pool = db.pools[a["investment_pool_id"]]
        value = calc.allocation_value_cents(a["units_micro"], pool["nav_per_unit_cents"])
        account["cash_balance_cents"] += value
        a["units_micro"] = 0
        a["status"] = "LIQUIDATED"
        touch(a)
        post_ledger(account, "POOL_REDEEM", value, "PoolAllocation", a["id"])


def _legacy_split(residual, beneficiaries):
    """Largest-remainder apportionment (PRD 3.8). Returns charity_id -> share_cents.

    Tie-break on fractional part: descending fraction, then beneficiary charity
    row's created_at ascending.
    """
    rows = []
    floor_total = 0
    for b in beneficiaries:
        cid = b["charity_id"]
        share_bps = b["share_bps"]
        exact = Decimal(residual) * Decimal(share_bps) / Decimal(10000)
        floor_share = calc.floor_div(exact)
        frac = exact - Decimal(floor_share)
        charity = db.charities[cid]
        rows.append({
            "charity_id": cid,
            "floor": floor_share,
            "frac": frac,
            "created_seq": charity["_seq"],
        })
        floor_total += floor_share

    remainder = residual - floor_total
    # Distribute leftover cents: fractional part DESC, tie-break created_at ASC.
    ordered = sorted(rows, key=lambda r: (-r["frac"], r["created_seq"]))
    for i in range(remainder):
        ordered[i]["floor"] += 1

    return {r["charity_id"]: r["floor"] for r in rows}
