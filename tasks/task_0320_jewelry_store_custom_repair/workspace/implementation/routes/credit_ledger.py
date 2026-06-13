"""The credit ledger as a direct operation (PRD §3.10)."""
from flask import Blueprint, request

import db
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.common import (
    get_body, require_str, require_int, require_enum, resolve_fk, resolve_path,
    post_ledger_entry,
)

bp = Blueprint("credit_ledger", __name__)

DIRECTIONS = {"CREDIT", "DEBIT"}
REASONS = {"TRADE_IN", "LAYAWAY_REFUND", "PURCHASE", "MANUAL_ADJUSTMENT"}


@bp.route("/credit-ledger", methods=["POST"])
def create_ledger_entry():
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    resolve_fk(db.customers, customer_id)
    direction = require_enum(body, "direction", DIRECTIONS)
    amount = require_int(body, "amount_cents", gt=0)
    reason = require_enum(body, "reason", REASONS)
    rec = post_ledger_entry(customer_id, direction, amount, reason)
    return success(serialize.credit_ledger_entry(rec), status=201)


@bp.route("/credit-ledger", methods=["GET"])
def list_ledger_entries():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    f_customer = request.args.get("customer_id")
    records = [e for e in db.credit_ledger.values()
               if f_customer is None or e["customer_id"] == f_customer]
    page, meta = paginate(records, limit, offset)
    return success([serialize.credit_ledger_entry(r) for r in page], status=200, pagination=meta)


@bp.route("/credit-ledger/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = resolve_path(db.credit_ledger, eid)
    return success(serialize.credit_ledger_entry(rec), status=200)
