"""ReserveAccount reads, matured-funds release, and the append-only ledger (PRD 3.3)."""

from flask import Blueprint, g, request

from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import touch
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, list_response
from serializers import serialize_ledger_entry, serialize_reserve_account
from services.reserve import compute_release_amount, has_program_reserve_lock, post_entry

bp = Blueprint("reserves", __name__)


@bp.get("/acquirer/reserve-accounts")
def list_reserve_accounts():
    authenticate(ALL_ROLES)
    merchant_id = request.args.get("merchant_id")
    records = list(db.reserve_accounts.values())
    if is_merchant_user():
        records = [a for a in records if a["merchant_id"] == g.uid]
    elif merchant_id is not None:
        records = [a for a in records if a["merchant_id"] == merchant_id]
    return list_response(records, serialize_reserve_account)


@bp.get("/acquirer/reserve-accounts/<aid>")
def get_reserve_account(aid):
    authenticate(ALL_ROLES)
    acct = get_or_404(db.reserve_accounts, aid, "ReserveAccount")
    hide_if_cross_merchant(acct["merchant_id"])
    return ok_object(serialize_reserve_account(acct))


@bp.post("/acquirer/reserve-accounts/<aid>/release")
def release_reserve(aid):
    authenticate(("RiskOfficer",))
    acct = get_or_404(db.reserve_accounts, aid, "ReserveAccount")
    # Priority 6: compliance lock outranks funds availability.
    if has_program_reserve_lock(acct["merchant_id"]):
        raise ApiError(409, "ERR_PROGRAM_RESERVE_LOCK",
                       "Reserve release is blocked while a program enrollment is ACTIVE or REMEDIATION")
    # Priority 10: the waterfall must produce a positive release amount.
    release_amount = compute_release_amount(acct)
    if release_amount <= 0:
        raise ApiError(409, "ERR_NO_RELEASABLE_FUNDS", "No matured releasable funds above the reserve target")
    post_entry(acct, "RELEASE", release_amount, "SCHEDULED_RELEASE", None, None)
    merchant = db.merchants[acct["merchant_id"]]
    merchant["clearing_balance_cents"] += release_amount
    touch(merchant)
    touch(acct)
    return ok_object(serialize_reserve_account(acct))


@bp.get("/acquirer/reserve-accounts/<aid>/ledger-entries")
def list_ledger_entries(aid):
    authenticate(ALL_ROLES)
    acct = get_or_404(db.reserve_accounts, aid, "ReserveAccount")
    hide_if_cross_merchant(acct["merchant_id"])
    records = [e for e in db.ledger_entries.values() if e["reserve_account_id"] == acct["id"]]
    return list_response(records, serialize_ledger_entry)
