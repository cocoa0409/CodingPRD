"""Product-child read endpoints (PRD §3.6 / §2.5 reverse-reachability).
Each lists the 0-or-1 child instrument tied to a transaction by transaction_id."""
from flask import Blueprint

from auth import require_auth, BOTH
from db import db, serialize
from helpers import parse_pagination, paginate, sort_by_creation
import lookups
from response import listed

bp = Blueprint("product_children", __name__)


def _list_children(tid, collection):
    require_auth(BOTH)
    lookups.get_transaction(tid)
    limit, offset = parse_pagination()
    items = [c for c in collection.values() if c["transaction_id"] == tid]
    items = sort_by_creation(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return listed([serialize(c) for c in page], limit, offset, total)


@bp.route("/transactions/<tid>/money-order", methods=["GET"])
def list_money_order(tid):
    return _list_children(tid, db.money_orders)


@bp.route("/transactions/<tid>/wire-transfer", methods=["GET"])
def list_wire_transfer(tid):
    return _list_children(tid, db.wire_transfers)


@bp.route("/transactions/<tid>/bill-payment", methods=["GET"])
def list_bill_payment(tid):
    return _list_children(tid, db.bill_payments)


@bp.route("/transactions/<tid>/prepaid-card-load", methods=["GET"])
def list_prepaid_card_load(tid):
    return _list_children(tid, db.prepaid_card_loads)
