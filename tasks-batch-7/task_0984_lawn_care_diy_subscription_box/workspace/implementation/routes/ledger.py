from flask import Blueprint, request

from db import store
from errors import ApiError, raise_err, ERR_CUSTOMER_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_ledger_entry
from services import post_ledger
from util import req_str, req_int

bp = Blueprint("ledger", __name__)

READ_ROLES = ["Customer", "PlatformAdmin"]


@bp.route("/api/credit-ledger/<eid>", methods=["GET"])
def get_entry(eid):
    uid, role = authenticate(READ_ROLES)
    rec = store.ledger.get(eid)
    if rec is None:
        # the PRD error catalog defines no ledger-specific 404 identifier
        raise ApiError("ERR_NOT_FOUND", 404, "Ledger entry not found")
    check_ownership(uid, role, rec.customer_id)
    return ok(ser_ledger_entry(rec))


@bp.route("/api/credit-ledger", methods=["GET"])
def list_entries():
    uid, role = authenticate(READ_ROLES)
    items = list(store.ledger.values())
    if role == "Customer":
        items = [e for e in items if e.customer_id == uid]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [e for e in items if e.customer_id == customer_id]
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        items = [e for e in items if e.entry_type == entry_type]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_ledger_entry(e) for e in page], total, limit, offset)


@bp.route("/api/credit-ledger/adjustments", methods=["POST"])
def create_adjustment():
    body = get_body()
    customer_id = req_str(body, "customer_id")
    amount_cents = req_int(body, "amount_cents")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise_err(ERR_INVALID_REQUEST, "Field 'note' must be a string")

    authenticate(["PlatformAdmin"])
    if customer_id not in store.customers:
        raise_err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    rec = post_ledger(customer_id, "ADJUSTMENT", amount_cents, reference_id=None, note=note)
    return ok(ser_ledger_entry(rec), 201)
