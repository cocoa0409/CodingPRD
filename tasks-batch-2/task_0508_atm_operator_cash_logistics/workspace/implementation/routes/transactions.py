"""Top-level transaction read/list routes."""
from flask import Blueprint, request

import lookups
import serialize
import validate
from db import store
from middleware import authenticate, authorize
from response import ok_array, ok_object

bp = Blueprint("transactions", __name__)

READ = {"PlatformAdmin", "FieldTech", "SettlementOfficer"}


@bp.route("/transactions/<tid>", methods=["GET"])
def get_transaction(tid):
    _, role = authenticate()
    authorize(role, READ)
    txn = lookups.transaction(store, tid)
    return ok_object(store.clock, serialize.transaction(txn))


@bp.route("/transactions", methods=["GET"])
def list_transactions():
    _, role = authenticate()
    authorize(role, READ)
    limit, offset = validate.parse_pagination(request.args)
    atm_id = request.args.get("atm_id")
    cassette_id = request.args.get("cassette_id")
    settlement_run_id = request.args.get("settlement_run_id")
    kind = request.args.get("kind")
    items = store.sorted_values(store.transactions)
    if atm_id is not None:
        items = [t for t in items if t["atm_id"] == atm_id]
    if cassette_id is not None:
        items = [t for t in items if t["cassette_id"] == cassette_id]
    if settlement_run_id is not None:
        items = [t for t in items if t["settlement_run_id"] == settlement_run_id]
    if kind is not None:
        items = [t for t in items if t["kind"] == kind]
    page, total = validate.paginate([serialize.transaction(t) for t in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)
