"""Account + Policy + PolicyYear + MedicalCondition routes (PRD §3.1–3.4)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_FK_INVALID,
    ERR_WELLNESS_RIDER_REQUIRED,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import (
    get_or_404,
    require_str,
    require_int,
    optional_int,
    optional_bool,
    require_enum,
    require_iso_date,
    sorted_by_creation,
)
from services import calculations

bp = Blueprint("accounts", __name__)

ALL_ROLES = ["PolicyHolder", "Underwriter", "ClaimsAdjuster"]


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@bp.post("/accounts")
def create_account():
    require_auth(["PolicyHolder", "Underwriter"])()
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")

    for other in db.accounts.values():
        if other.get("email") == email:
            raise APIError(ERR_INVALID_REQUEST, 400, "email must be unique")

    acct = db.stamp_common(
        {
            "email": email,
            "full_name": full_name,
            "active_policy_count": 0,
            "monthly_premium_cents": 0,
            "multi_pet_discount_applied": False,
        }
    )
    db.accounts[acct["id"]] = acct
    return ok_object(acct, 201)


@bp.get("/accounts/<aid>")
def get_account(aid):
    require_auth(ALL_ROLES)()
    acct = get_or_404(db.accounts, aid, "Account")
    return ok_object(acct, 200)


@bp.get("/accounts")
def list_accounts():
    require_auth(["Underwriter", "ClaimsAdjuster"])()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.accounts.values()))
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Policies (nested under account)
# ---------------------------------------------------------------------------
@bp.post("/accounts/<aid>/policies")
def create_policy(aid):
    require_auth(["Underwriter"])()
    acct = get_or_404(db.accounts, aid, "Account")
    body = get_json_body()

    pet_name = require_str(body, "pet_name")
    species = require_enum(body, "species", {"DOG", "CAT"})
    base_premium = require_int(body, "base_premium_cents")
    annual_deductible = require_int(body, "annual_deductible_cents")
    reimbursement_rate = require_int(body, "reimbursement_rate_bps")
    annual_cap = require_int(body, "annual_cap_cents")
    effective_date = require_iso_date(body, "effective_date")
    waiting_period = optional_int(body, "waiting_period_days", 14)
    wellness_rider = optional_bool(body, "wellness_rider", False)

    if base_premium < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "base_premium_cents must be >= 0")
    if annual_deductible < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "annual_deductible_cents must be >= 0")
    if not (0 <= reimbursement_rate <= 10000):
        raise APIError(ERR_INVALID_REQUEST, 400, "reimbursement_rate_bps must be in [0,10000]")
    if annual_cap < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "annual_cap_cents must be >= 0")
    if waiting_period < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "waiting_period_days must be >= 0")

    pol = db.stamp_common(
        {
            "account_id": acct["id"],
            "pet_name": pet_name,
            "species": species,
            "base_premium_cents": base_premium,
            "annual_deductible_cents": annual_deductible,
            "reimbursement_rate_bps": reimbursement_rate,
            "annual_cap_cents": annual_cap,
            "waiting_period_days": waiting_period,
            "wellness_rider": wellness_rider,
            "effective_date": effective_date,
            "status": "PENDING_PAYMENT",
        }
    )
    db.policies[pol["id"]] = pol
    return ok_object(pol, 201)


def _resolve_policy_under_account(aid, pid):
    acct = get_or_404(db.accounts, aid, "Account")
    pol = get_or_404(db.policies, pid, "Policy")
    if pol.get("account_id") != acct["id"]:
        raise APIError(ERR_NOT_FOUND, 404, "Policy not found under account")
    return acct, pol


@bp.get("/accounts/<aid>/policies")
def list_account_policies(aid):
    require_auth(ALL_ROLES)()
    acct = get_or_404(db.accounts, aid, "Account")
    limit, offset = paginate_params(request.args)
    status = request.args.get("status")
    items = [p for p in db.policies.values() if p.get("account_id") == acct["id"]]
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.get("/accounts/<aid>/policies/<pid>")
def get_account_policy(aid, pid):
    require_auth(ALL_ROLES)()
    _, pol = _resolve_policy_under_account(aid, pid)
    return ok_object(pol, 200)


@bp.post("/accounts/<aid>/policies/<pid>/activate")
def activate_policy(aid, pid):
    require_auth(["Underwriter"])()
    acct, pol = _resolve_policy_under_account(aid, pid)
    body = get_json_body()

    if pol["status"] != "PENDING_PAYMENT":
        raise APIError(ERR_INVALID_STATE, 409, "Activate only valid from PENDING_PAYMENT")

    # optional effective_date override
    if "effective_date" in body and body["effective_date"] is not None:
        pol["effective_date"] = require_iso_date(body, "effective_date")

    pol["status"] = "ACTIVE"

    eff = db.parse_iso_dt(pol["effective_date"])
    period_end = db.add_days(eff, 365)
    py = db.stamp_common(
        {
            "policy_id": pol["id"],
            "year_index": 0,
            "period_start": pol["effective_date"],
            "period_end": period_end.strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{period_end.microsecond // 1000:03d}Z",
            "deductible_met_cents": 0,
            "reimbursed_cents": 0,
            "wellness_used_cents": 0,
            "status": "OPEN",
        }
    )
    # close it immediately if the clock is already past period_end
    if db.now_dt() >= db.parse_iso_dt(py["period_end"]):
        py["status"] = "CLOSED"
    db.policy_years[py["id"]] = py

    calculations.recompute_account(acct)
    db.bump(acct)
    db.bump(pol)
    return ok_object(pol, 200)


@bp.post("/accounts/<aid>/policies/<pid>/lapse")
def lapse_policy(aid, pid):
    require_auth(["Underwriter"])()
    acct, pol = _resolve_policy_under_account(aid, pid)
    if pol["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Lapse only valid from ACTIVE")
    pol["status"] = "LAPSED"
    calculations.recompute_account(acct)
    db.bump(acct)
    db.bump(pol)
    return ok_object(pol, 200)


@bp.post("/accounts/<aid>/policies/<pid>/cancel")
def cancel_policy(aid, pid):
    require_auth(["Underwriter"])()
    acct, pol = _resolve_policy_under_account(aid, pid)
    was_active = pol["status"] == "ACTIVE"
    if pol["status"] not in ("ACTIVE", "PENDING_PAYMENT"):
        raise APIError(ERR_INVALID_STATE, 409, "Cancel only valid from ACTIVE or PENDING_PAYMENT")
    pol["status"] = "CANCELLED"
    if was_active:
        calculations.recompute_account(acct)
        db.bump(acct)
    db.bump(pol)
    return ok_object(pol, 200)


@bp.get("/accounts/<aid>/policies/<pid>/policy-years")
def list_policy_years_nested(aid, pid):
    require_auth(ALL_ROLES)()
    _, pol = _resolve_policy_under_account(aid, pid)
    limit, offset = paginate_params(request.args)
    items = [y for y in db.policy_years.values() if y.get("policy_id") == pol["id"]]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Medical conditions (nested under policy)
# ---------------------------------------------------------------------------
@bp.post("/accounts/<aid>/policies/<pid>/conditions")
def create_condition(aid, pid):
    require_auth(ALL_ROLES)()
    _, pol = _resolve_policy_under_account(aid, pid)
    body = get_json_body()
    name = require_str(body, "name")
    first_diagnosed = require_iso_date(body, "first_diagnosed_date")

    cond = db.stamp_common(
        {
            "policy_id": pol["id"],
            "name": name,
            "first_diagnosed_date": first_diagnosed,
            "exclusion_status": "COVERED",
        }
    )
    cond["exclusion_status"] = calculations.compute_exclusion_status(cond, pol)
    db.conditions[cond["id"]] = cond
    return ok_object(cond, 201)


@bp.get("/accounts/<aid>/policies/<pid>/conditions")
def list_conditions_nested(aid, pid):
    require_auth(ALL_ROLES)()
    _, pol = _resolve_policy_under_account(aid, pid)
    limit, offset = paginate_params(request.args)
    items = [c for c in db.conditions.values() if c.get("policy_id") == pol["id"]]
    # re-evaluate exclusion on read
    for c in items:
        c["exclusion_status"] = calculations.compute_exclusion_status(c, pol)
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Open a claim (nested under policy) — PolicyHolder only
# ---------------------------------------------------------------------------
@bp.post("/accounts/<aid>/policies/<pid>/claims")
def create_claim(aid, pid):
    require_auth(["PolicyHolder"])()
    acct, pol = _resolve_policy_under_account(aid, pid)

    # ownership: PolicyHolder must own the account chain (priority 6)
    if g.user_id != acct["id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the owner of this account")

    body = get_json_body()
    claim_type = require_enum(body, "claim_type", {"ILLNESS", "ACCIDENT", "WELLNESS"})
    incident_date = require_iso_date(body, "incident_date")
    condition_id = body.get("condition_id")

    # FK resolution (priority 4): if condition_id supplied, must belong to this policy
    if condition_id is not None:
        if not isinstance(condition_id, str):
            raise APIError(ERR_INVALID_REQUEST, 400, "condition_id must be a string")
        cond = db.conditions.get(condition_id)
        if cond is None or cond.get("policy_id") != pol["id"]:
            raise APIError(ERR_FK_INVALID, 422, "condition_id does not belong to this policy")

    # claim-type referencing rule (priority 11)
    if claim_type == "WELLNESS":
        if not pol.get("wellness_rider"):
            raise APIError(
                ERR_WELLNESS_RIDER_REQUIRED, 422, "WELLNESS claim requires the wellness rider"
            )
    else:
        if condition_id is None:
            raise APIError(
                ERR_WELLNESS_RIDER_REQUIRED, 422, "Non-WELLNESS claim requires condition_id"
            )

    claim = db.stamp_common(
        {
            "policy_id": pol["id"],
            "condition_id": condition_id,
            "claim_type": claim_type,
            "incident_date": incident_date,
            "submitted_amount_cents": 0,
            "eligible_amount_cents": 0,
            "deductible_applied_cents": 0,
            "reimbursed_cents": 0,
            "wellness_paid_cents": 0,
            "status": "DRAFT",
            "denial_reason": None,
        }
    )
    db.claims[claim["id"]] = claim
    return ok_object(claim, 201)
