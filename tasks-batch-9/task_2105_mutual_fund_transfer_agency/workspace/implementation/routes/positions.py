"""Positions and the append-only share ledger."""
from flask import Blueprint, request

import db
import response
import serializers
import validation
from constants import LEDGER_REASONS
from middleware import ALL_ROLES, ROLE_CO, ROLE_DEALER, ROLE_FA, ROLE_TAO, authenticate
from routes import helpers

bp = Blueprint("positions", __name__)


@bp.route("/positions/<position_id>", methods=["GET"])
def read_position(position_id):
    authenticate(ALL_ROLES)
    position = helpers.get_position(position_id)
    return response.ok(serializers.position(position))


@bp.route("/positions", methods=["GET"])
def list_positions():
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO, ROLE_DEALER))
    limit, offset = validation.pagination()
    records = db.values(db.store.positions)
    records = helpers.filter_equals(records, "account_id", request.args.get("account_id"))
    records = helpers.filter_equals(records, "share_class_id", request.args.get("share_class_id"))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.position(r) for r in items], total, limit, offset)


@bp.route("/share-ledger-entries/<entry_id>", methods=["GET"])
def read_ledger_entry(entry_id):
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO))
    entry = helpers.get_ledger_entry(entry_id)
    return response.ok(serializers.ledger_entry(entry))


@bp.route("/share-ledger-entries", methods=["GET"])
def list_ledger_entries():
    authenticate((ROLE_TAO, ROLE_FA, ROLE_CO))
    limit, offset = validation.pagination()
    records = db.values(db.store.ledger_entries)
    records = helpers.filter_equals(records, "position_id", request.args.get("position_id"))
    records = helpers.filter_equals(records, "trade_id", request.args.get("trade_id"))
    records = helpers.filter_equals(records, "entry_reason",
                                    validation.query_enum("entry_reason", LEDGER_REASONS))
    records = helpers.filter_equals(records, "effective_date",
                                    validation.query_date("effective_date"))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.ledger_entry(r) for r in items], total, limit, offset)
