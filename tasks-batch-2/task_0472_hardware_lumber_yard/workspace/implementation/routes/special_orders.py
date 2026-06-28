"""SpecialOrder endpoints — quote/revision loop, confirm, receive (PRD 3.9).

Cyclic state machine: DRAFT -> QUOTED <-> REVISION_REQUESTED -> CONFIRMED ->
RECEIVED, with cancellation allowed from DRAFT/QUOTED/REVISION_REQUESTED.
"""
from flask import Blueprint, request

import calc
import db
import errors
import helpers
import serialize
import validate
from auth import authenticate, require_roles
from response import ok, created, ok_list

bp = Blueprint("special_orders", __name__)

CANCELLABLE = {"DRAFT", "QUOTED", "REVISION_REQUESTED"}


def _contractor_owns(caller, order):
    if caller.is_contractor and order["contractor_account_id"] != caller.user_id:
        raise errors.unauthorized()


@bp.route("/special-orders", methods=["POST"])
def create_special_order():
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "Contractor"})
    data = validate.body()
    vendor_id = validate.require_str(data, "vendor_id")
    account_id = validate.require_str(data, "contractor_account_id")
    description = validate.require_str(data, "description")
    qty = validate.require_int(data, "qty", exclusive_min=0)
    with db.lock:
        helpers.get_or_404(db.vendors, vendor_id)
        helpers.get_or_404(db.contractor_accounts, account_id)
        # A Contractor may only open a special order on their own account.
        if caller.is_contractor and account_id != caller.user_id:
            raise errors.unauthorized()
        rec = db.new_record({
            "vendor_id": vendor_id,
            "contractor_account_id": account_id,
            "description": description,
            "quoted_unit_cents": 0,
            "qty": qty,
            "revision_count": 0,
            "confirmed_total_cents": 0,
            "status": "DRAFT",
        })
        db.special_orders[rec["id"]] = rec
        return created(serialize.special_order(rec))


@bp.route("/special-orders/<rid>", methods=["GET"])
def get_special_order(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "Contractor", "InventoryManager"})
    with db.lock:
        rec = helpers.get_or_404(db.special_orders, rid)
        _contractor_owns(caller, rec)
        return ok(serialize.special_order(rec))


@bp.route("/special-orders", methods=["GET"])
def list_special_orders():
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "Contractor", "InventoryManager"})
    limit, offset = validate.pagination()
    vendor_id = request.args.get("vendor_id")
    account_id = request.args.get("contractor_account_id")
    with db.lock:
        items = list(db.special_orders.values())
        if caller.is_contractor:
            items = [s for s in items if s["contractor_account_id"] == caller.user_id]
        if vendor_id is not None:
            items = [s for s in items if s["vendor_id"] == vendor_id]
        if account_id is not None:
            items = [s for s in items if s["contractor_account_id"] == account_id]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.special_order(s) for s in page], limit, offset, total)


@bp.route("/special-orders/<rid>/quote", methods=["POST"])
def quote(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    data = validate.body()
    with db.lock:
        # path existence (priority 3) before body request-validity (priority 4)
        order = helpers.get_or_404(db.special_orders, rid)
        quoted_unit_cents = validate.require_int(data, "quoted_unit_cents", minimum=0)
        if order["status"] not in ("DRAFT", "REVISION_REQUESTED"):
            raise errors.invalid_state("quote is only defined from DRAFT or REVISION_REQUESTED")
        vendor = db.vendors.get(order["vendor_id"])
        if vendor is None or vendor["status"] != "ACTIVE" or not vendor["drop_ship_capable"]:
            raise errors.ApiError(errors.ERR_VENDOR_NOT_DROP_SHIP, 409,
                                  "vendor is inactive or not drop-ship capable")
        from_revision = order["status"] == "REVISION_REQUESTED"
        order["quoted_unit_cents"] = quoted_unit_cents
        if from_revision:
            order["revision_count"] = order["revision_count"] + 1
        order["status"] = "QUOTED"
        db.touch(order)
        return ok(serialize.special_order(order))


@bp.route("/special-orders/<rid>/request-revision", methods=["POST"])
def request_revision(rid):
    caller = authenticate()
    require_roles(caller, {"Contractor"})
    with db.lock:
        order = helpers.get_or_404(db.special_orders, rid)
        _contractor_owns(caller, order)
        if order["status"] != "QUOTED":
            raise errors.invalid_state("request-revision is only defined from QUOTED")
        order["status"] = "REVISION_REQUESTED"
        db.touch(order)
        return ok(serialize.special_order(order))


@bp.route("/special-orders/<rid>/confirm", methods=["POST"])
def confirm(rid):
    caller = authenticate()
    require_roles(caller, {"Contractor"})
    with db.lock:
        order = helpers.get_or_404(db.special_orders, rid)
        _contractor_owns(caller, order)
        if order["status"] != "QUOTED":
            raise errors.invalid_state("confirm is only defined from QUOTED")
        account = db.contractor_accounts.get(order["contractor_account_id"])
        # priority 14: account suspended
        if account is None or account["status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_ACCOUNT_SUSPENDED, 409,
                                  "account is suspended")
        confirmed_total = calc.special_order_total(order["quoted_unit_cents"], order["qty"])
        # priority 18: credit limit (settled balance + projected total)
        balance = serialize.account_balance_cents(account["id"])
        if balance + confirmed_total > account["credit_limit_cents"]:
            raise errors.ApiError(errors.ERR_CREDIT_LIMIT_EXCEEDED, 409,
                                  "confirmation would exceed credit limit")
        order["confirmed_total_cents"] = confirmed_total
        order["status"] = "CONFIRMED"
        db.touch(order)
        # cascade depth-2: create ISSUED Invoice; balance recomputed
        inv = db.new_record({
            "sales_order_id": None,
            "contractor_account_id": account["id"],
            "amount_cents": confirmed_total,
            "due_at": _due_at(account),
            "status": "ISSUED",
        })
        db.invoices[inv["id"]] = inv
        db.touch(account)
        return ok(serialize.special_order(order))


@bp.route("/special-orders/<rid>/receive", methods=["POST"])
def receive(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    with db.lock:
        order = helpers.get_or_404(db.special_orders, rid)
        if order["status"] != "CONFIRMED":
            raise errors.invalid_state("receive is only defined from CONFIRMED")
        order["status"] = "RECEIVED"
        db.touch(order)
        return ok(serialize.special_order(order))


@bp.route("/special-orders/<rid>/cancel", methods=["POST"])
def cancel(rid):
    caller = authenticate()
    require_roles(caller, {"Contractor"})
    with db.lock:
        order = helpers.get_or_404(db.special_orders, rid)
        _contractor_owns(caller, order)
        if order["status"] not in CANCELLABLE:
            raise errors.invalid_state("a CONFIRMED/RECEIVED special order cannot be cancelled")
        order["status"] = "CANCELLED"
        db.touch(order)
        return ok(serialize.special_order(order))


def _due_at(account):
    import clock
    from datetime import timedelta
    return clock.now() + timedelta(days=account["net_terms_days"])
