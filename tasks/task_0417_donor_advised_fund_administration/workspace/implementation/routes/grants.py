"""GrantRecommendation endpoints: submit (OCC), approve, reject, schedule,
pay (payout waterfall), cancel (PRD 3.5, 3.6)."""
from flask import Blueprint, request

from db import db, common_create_fields, touch, LOCK
from errors import err
from middleware import get_identity, require_role, get_json_body, get_pagination, paginate
from response import object_response, array_response
from services import calc, serialize
from services.accounts import recompute_account, post_ledger
from services.lookup import (
    get_or_404, require_string, require_positive_int, require_int, optional_bool,
    optional_string, optional_int, optional_enum, filtered_sorted,
)

bp = Blueprint("grants", __name__)

READ_ROLES = {"SponsorAdmin", "DonorAdvisor", "GrantOfficer"}
RECURRENCES = {"ONE_TIME", "RECURRING"}


@bp.post("/daf/grants")
def submit_grant():
    user_id, role = get_identity()
    require_role(role, {"DonorAdvisor"})
    body = get_json_body()
    donor_account_id = require_string(body, "donor_account_id")
    charity_id = require_string(body, "charity_id")
    amount_cents = require_positive_int(body, "amount_cents")
    expected_account_version = require_int(body, "expected_account_version")
    is_anonymous = optional_bool(body, "is_anonymous", False)
    purpose = optional_string(body, "purpose", None)
    recurrence = optional_enum(body, "recurrence", RECURRENCES, "ONE_TIME")
    effective_from_quarter = optional_int(body, "effective_from_quarter", None)
    effective_to_quarter = optional_int(body, "effective_to_quarter", None)

    with LOCK:
        # Body FK existence, left-to-right: account then charity.
        account = get_or_404(db.accounts, donor_account_id)
        get_or_404(db.charities, charity_id)
        # Minimum-grant business rule precedes OCC (PRD 3.10 ordering:
        # ERR_BELOW_MINIMUM_GRANT then the stale-version guard).
        sponsor = db.sponsors[account["sponsor_id"]]
        if amount_cents < sponsor["minimum_grant_cents"]:
            raise err("ERR_BELOW_MINIMUM_GRANT")
        # OCC on account version (PRD 2.9).
        if expected_account_version != account["version"]:
            raise err("ERR_STALE_ACCOUNT_VERSION")

        grant = common_create_fields()
        grant.update({
            "donor_account_id": donor_account_id,
            "charity_id": charity_id,
            "amount_cents": amount_cents,
            "is_anonymous": is_anonymous,
            "purpose": purpose,
            "recurrence": recurrence,
            "effective_from_quarter": effective_from_quarter,
            "effective_to_quarter": effective_to_quarter,
            "recommended_by_user_id": user_id,
            "approved_by_user_id": None,
            "paid_quarter_index": None,
            "status": "SUBMITTED",
        })
        db.grants[grant["id"]] = grant
        # Recompute committed/grantable; increment account version by one (PRD 2.9).
        recompute_account(account)
        touch(account)
    return object_response(serialize.grant(grant), status=201)


@bp.get("/daf/grants/<grant_id>")
def get_grant(grant_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    grant = get_or_404(db.grants, grant_id)
    return object_response(serialize.grant(grant))


@bp.get("/daf/grants")
def list_grants():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    items = filtered_sorted(db.grants, {
        "donor_account_id": request.args.get("donor_account_id"),
        "charity_id": request.args.get("charity_id"),
        "status": request.args.get("status"),
    })
    page, meta = paginate(items, limit, offset)
    return array_response([serialize.grant(g) for g in page], meta)


@bp.post("/daf/grants/<grant_id>/approve")
def approve_grant(grant_id):
    user_id, role = get_identity()
    require_role(role, {"GrantOfficer"})
    with LOCK:
        grant = get_or_404(db.grants, grant_id)
        if grant["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE")
        account = db.accounts[grant["donor_account_id"]]
        # PRD 3.10 fixes the deterministic precedence among business rules:
        # account-active gate, then segregation of duties, then charity-vetted.
        if account["status"] not in ("ACTIVE", "INACTIVE"):
            raise err("ERR_ACCOUNT_NOT_ACTIVE")
        if user_id == grant["recommended_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES")
        charity = db.charities[grant["charity_id"]]
        if charity["status"] != "VETTED":
            raise err("ERR_CHARITY_NOT_VETTED")
        grant["status"] = "APPROVED"
        grant["approved_by_user_id"] = user_id
        touch(grant)
    return object_response(serialize.grant(grant))


@bp.post("/daf/grants/<grant_id>/reject")
def reject_grant(grant_id):
    user_id, role = get_identity()
    require_role(role, {"GrantOfficer"})
    with LOCK:
        grant = get_or_404(db.grants, grant_id)
        if grant["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE")
        if user_id == grant["recommended_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES")
        grant["status"] = "REJECTED"
        touch(grant)
        account = db.accounts[grant["donor_account_id"]]
        recompute_account(account)
        touch(account)
    return object_response(serialize.grant(grant))


@bp.post("/daf/grants/<grant_id>/schedule")
def schedule_grant(grant_id):
    _, role = get_identity()
    require_role(role, {"GrantOfficer"})
    with LOCK:
        grant = get_or_404(db.grants, grant_id)
        if grant["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE")
        charity = db.charities[grant["charity_id"]]
        if charity["status"] != "VETTED":
            raise err("ERR_CHARITY_NOT_VETTED")
        account = db.accounts[grant["donor_account_id"]]
        if account["cash_balance_cents"] + account["invested_value_cents"] < grant["amount_cents"]:
            raise err("ERR_INSUFFICIENT_GRANTABLE_BALANCE")
        # RECURRING closed-window overlap (PRD 3.6).
        if grant["recurrence"] == "RECURRING":
            _check_recurring_overlap(grant)
        grant["status"] = "SCHEDULED"
        touch(grant)
    return object_response(serialize.grant(grant))


@bp.post("/daf/grants/<grant_id>/pay")
def pay_grant(grant_id):
    _, role = get_identity()
    require_role(role, {"GrantOfficer"})
    with LOCK:
        grant = get_or_404(db.grants, grant_id)
        if grant["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE")
        charity = db.charities[grant["charity_id"]]
        # Re-check vetting (PRD 3.6 — a watchlist/revoke may have intervened).
        if charity["status"] != "VETTED":
            raise err("ERR_CHARITY_NOT_VETTED")
        account = db.accounts[grant["donor_account_id"]]
        amount = grant["amount_cents"]
        if account["cash_balance_cents"] + account["invested_value_cents"] < amount:
            raise err("ERR_INSUFFICIENT_GRANTABLE_BALANCE")

        _payout_waterfall(account, grant)

        grant["status"] = "PAID"
        sponsor = db.sponsors[account["sponsor_id"]]
        grant["paid_quarter_index"] = sponsor["current_quarter_index"]
        touch(grant)

        # last_grant_paid_quarter updated; INACTIVE -> ACTIVE (PRD 3.6).
        account["last_grant_paid_quarter"] = sponsor["current_quarter_index"]
        if account["status"] == "INACTIVE":
            account["status"] = "ACTIVE"
        recompute_account(account)
        touch(account)
    return object_response(serialize.grant(grant))


@bp.post("/daf/grants/<grant_id>/cancel")
def cancel_grant(grant_id):
    user_id, role = get_identity()
    require_role(role, {"DonorAdvisor"})
    with LOCK:
        grant = get_or_404(db.grants, grant_id)
        account = db.accounts[grant["donor_account_id"]]
        # Owner-scope precedes state (PRD 3.10).
        if user_id != account["primary_advisor_user_id"]:
            raise err("ERR_NOT_ACCOUNT_OWNER")
        if grant["status"] not in ("SUBMITTED", "APPROVED", "SCHEDULED"):
            raise err("ERR_INVALID_STATE")
        grant["status"] = "CANCELLED"
        touch(grant)
        recompute_account(account)
        touch(account)
    return object_response(serialize.grant(grant))


def _check_recurring_overlap(grant):
    """Closed-interval overlap (PRD 3.6): [f,t] collides with existing SCHEDULED
    RECURRING grant [f1,t1] to same charity from same account iff f1 <= t2 AND f2 <= t1."""
    f2 = grant["effective_from_quarter"]
    t2 = grant["effective_to_quarter"]
    if f2 is None or t2 is None:
        return
    for other in db.grants.values():
        if other["id"] == grant["id"]:
            continue
        if other["status"] != "SCHEDULED" or other["recurrence"] != "RECURRING":
            continue
        if other["donor_account_id"] != grant["donor_account_id"]:
            continue
        if other["charity_id"] != grant["charity_id"]:
            continue
        f1 = other["effective_from_quarter"]
        t1 = other["effective_to_quarter"]
        if f1 is None or t1 is None:
            continue
        if f1 <= t2 and f2 <= t1:
            raise err("ERR_RECURRING_GRANT_OVERLAP")


def _payout_waterfall(account, grant):
    """PRD 3.6 grant_payout_redemption: redeem the shortfall across ACTIVE pool
    allocations ordered by target_pct_bps DESC then created_at ASC, then debit the
    grant amount from cash."""
    amount = grant["amount_cents"]
    need = amount - account["cash_balance_cents"]
    if need > 0:
        allocs = [a for a in db.allocations.values()
                  if a["donor_account_id"] == account["id"]
                  and a["status"] == "ACTIVE"
                  and a["units_micro"] > 0]
        # Order: target_pct_bps DESC, then created_at ASC (never by id).
        allocs.sort(key=lambda a: (-a["target_pct_bps"], a["_seq"]))
        for alloc in allocs:
            if need <= 0:
                break
            pool = db.pools[alloc["investment_pool_id"]]
            alloc_value = calc.allocation_value_cents(alloc["units_micro"], pool["nav_per_unit_cents"])
            if alloc_value <= 0:
                continue
            take = min(alloc_value, need)
            redeem_units = calc.units_redeemed_micro(take, pool["nav_per_unit_cents"])
            alloc["units_micro"] -= redeem_units
            if alloc["units_micro"] < 0:
                alloc["units_micro"] = 0
            if alloc["units_micro"] == 0:
                alloc["status"] = "LIQUIDATED"
            touch(alloc)
            account["cash_balance_cents"] += take
            need -= take
            post_ledger(account, "POOL_REDEEM", take, "GrantRecommendation", grant["id"])

    # Debit the grant amount and append GRANT_PAID (PRD 3.6).
    account["cash_balance_cents"] -= amount
    post_ledger(account, "GRANT_PAID", -amount, "GrantRecommendation", grant["id"])
