"""MemberAccount endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_DUPLICATE_EMAIL, ERR_REFERENCE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
)
from middleware import authenticate, require_role
from response import success, list_success
from common import (
    parse_pagination, paginate, sort_by_created, get_json, stamp_new, public,
    require_str,
)
from lookup import get_or_404

bp = Blueprint("accounts", __name__)


@bp.post("/wellness/member-accounts")
def create_account():
    _, role = authenticate()
    require_role(role, {"Member"})
    body = get_json()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    home_clinic_id = require_str(body, "home_clinic_id")
    # Body FK: home_clinic_id must exist (ERR_REFERENCE_NOT_FOUND).
    if home_clinic_id not in db.clinics:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced clinic does not exist")
    # Email uniqueness, case-insensitive (PRD §3.2).
    lowered = email.lower()
    for acct in db.member_accounts.values():
        if acct["email"].lower() == lowered:
            raise err(ERR_DUPLICATE_EMAIL, "Email already registered")
    account = {
        "email": email,
        "full_name": full_name,
        "home_clinic_id": home_clinic_id,
        "wallet_credit_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(account)
    db.member_accounts[account["id"]] = account
    return success(public(account), 201)


@bp.get("/wellness/member-accounts")
def list_accounts():
    user_id, role = authenticate()
    require_role(role, {"PlanAdmin", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    rows = list(db.member_accounts.values())
    # A Member may list accounts filtered to their own (PRD §3.2); they only
    # see their own account.
    if role == "Member":
        rows = [r for r in rows if r["id"] == user_id]
    email = request.args.get("email")
    if email is not None:
        rows = [r for r in rows if r["email"].lower() == email.lower()]
    home_clinic_id = request.args.get("home_clinic_id")
    if home_clinic_id is not None:
        rows = [r for r in rows if r["home_clinic_id"] == home_clinic_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/member-accounts/<aid>")
def get_account(aid):
    user_id, role = authenticate()
    require_role(role, {"Member", "PlanAdmin", "BillingAdmin"})
    account = get_or_404(db.member_accounts, aid)
    # Member must own the account (PRD §2.1, §2.9 priority 3).
    if role == "Member" and account["id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    return success(public(account))
