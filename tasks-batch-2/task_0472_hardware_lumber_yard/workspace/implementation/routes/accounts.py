"""ContractorAccount endpoints (PRD 2.9, 3.x).

Contractor ownership: when the caller is a Contractor, X-User-ID is the id of
the acting ContractorAccount; ownership checks compare a resource's
contractor_account_id to X-User-ID (PRD 2.1).
"""
from flask import Blueprint, request

import db
import errors
import helpers
import serialize
import validate
from auth import authenticate, require_roles
from response import ok, created, ok_list

bp = Blueprint("accounts", __name__)

NET_TERMS_ALLOWED = {0, 15, 30, 45, 60}


def _check_contractor_owns(caller, account_id):
    """For Contractor callers, the account they read must be their own."""
    if caller.is_contractor and caller.user_id != account_id:
        raise errors.unauthorized()


@bp.route("/contractor-accounts", methods=["POST"])
def create_account():
    caller = authenticate()
    require_roles(caller, {"AccountsManager"})
    data = validate.body()
    business_name = validate.require_str(data, "business_name")
    credit_limit = validate.require_int(data, "credit_limit_cents", minimum=0)
    net_terms = validate.require_int(data, "net_terms_days")
    if net_terms not in NET_TERMS_ALLOWED:
        raise errors.invalid_request("net_terms_days must be one of 0,15,30,45,60")
    with db.lock:
        rec = db.new_record({
            "business_name": business_name,
            "credit_limit_cents": credit_limit,
            "net_terms_days": net_terms,
            "status": "ACTIVE",
        })
        db.contractor_accounts[rec["id"]] = rec
        return created(serialize.contractor_account(rec))


@bp.route("/contractor-accounts/<rid>", methods=["GET"])
def get_account(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager", "SalesAssociate", "Contractor"})
    with db.lock:
        rec = helpers.get_or_404(db.contractor_accounts, rid)
        _check_contractor_owns(caller, rid)
        return ok(serialize.contractor_account(rec))


@bp.route("/contractor-accounts/<rid>/suspend", methods=["POST"])
def suspend_account(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager"})
    with db.lock:
        rec = helpers.get_or_404(db.contractor_accounts, rid)
        rec["status"] = "SUSPENDED"
        db.touch(rec)
        return ok(serialize.contractor_account(rec))


@bp.route("/contractor-accounts/<rid>/loyalty-ledger", methods=["GET"])
def account_loyalty_ledger(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager", "Contractor"})
    limit, offset = validate.pagination()
    with db.lock:
        helpers.get_or_404(db.contractor_accounts, rid)
        _check_contractor_owns(caller, rid)
        items = [e for e in db.loyalty_ledger.values() if e["contractor_account_id"] == rid]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.loyalty_ledger(e) for e in page], limit, offset, total)


@bp.route("/contractor-accounts/<rid>/invoices", methods=["GET"])
def account_invoices(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager", "Contractor"})
    limit, offset = validate.pagination()
    status = request.args.get("status")
    with db.lock:
        helpers.get_or_404(db.contractor_accounts, rid)
        _check_contractor_owns(caller, rid)
        items = [i for i in db.invoices.values() if i["contractor_account_id"] == rid]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.invoice(i) for i in page], limit, offset, total)
