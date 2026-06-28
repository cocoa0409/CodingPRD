"""Invoice and LoyaltyLedger read endpoints."""
from flask import Blueprint, request

import db
import errors
import helpers
import serialize
import validate
from auth import authenticate, require_roles
from response import ok, ok_list

bp = Blueprint("billing_reads", __name__)


# ------------------------------------------------------------------ Invoice ---

@bp.route("/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager", "Contractor"})
    with db.lock:
        inv = helpers.get_or_404(db.invoices, rid)
        if caller.is_contractor and inv["contractor_account_id"] != caller.user_id:
            raise errors.unauthorized()
        return ok(serialize.invoice(inv))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    caller = authenticate()
    require_roles(caller, {"AccountsManager", "Contractor"})
    limit, offset = validate.pagination()
    sales_order_id = request.args.get("sales_order_id")
    status = request.args.get("status")
    with db.lock:
        items = list(db.invoices.values())
        if caller.is_contractor:
            items = [i for i in items if i["contractor_account_id"] == caller.user_id]
        if sales_order_id is not None:
            items = [i for i in items if i["sales_order_id"] == sales_order_id]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.invoice(i) for i in page], limit, offset, total)


# ------------------------------------------------------------ LoyaltyLedger ---

@bp.route("/loyalty-ledger/<rid>", methods=["GET"])
def get_ledger_entry(rid):
    caller = authenticate()
    require_roles(caller, {"AccountsManager", "Contractor"})
    with db.lock:
        entry = helpers.get_or_404(db.loyalty_ledger, rid)
        if caller.is_contractor and entry["contractor_account_id"] != caller.user_id:
            raise errors.unauthorized()
        return ok(serialize.loyalty_ledger(entry))


@bp.route("/loyalty-ledger", methods=["GET"])
def list_ledger():
    caller = authenticate()
    require_roles(caller, {"AccountsManager", "Contractor"})
    limit, offset = validate.pagination()
    account_id = request.args.get("contractor_account_id")
    sales_order_id = request.args.get("sales_order_id")
    with db.lock:
        items = list(db.loyalty_ledger.values())
        if caller.is_contractor:
            items = [e for e in items if e["contractor_account_id"] == caller.user_id]
        if account_id is not None:
            items = [e for e in items if e["contractor_account_id"] == account_id]
        if sales_order_id is not None:
            items = [e for e in items if e["sales_order_id"] == sales_order_id]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.loyalty_ledger(e) for e in page], limit, offset, total)
