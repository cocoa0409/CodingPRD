"""Debit-ledger read routes (PRD §3.8)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import forbid_unless_owner, parse_enum_filter, parse_str_filter
from response import success_obj
from routes.helpers import guard, public, list_response, by_created

bp = Blueprint("ledger", __name__)

ENTRY_TYPES = {"FEE_SHORTFALL_ACCRUAL", "FEE_SHORTFALL_REVERSAL", "DEBIT_RECOVERY",
               "DEBIT_RECOVERY_REVERSAL", "MANUAL_DEBIT", "DEBIT_WRITE_OFF"}


@bp.route("/brokerage/ledger-entries/<entryId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_entry(user_id, role, entryId):
    e = db.ledger_entries.get(entryId)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ledger entry not found")
    forbid_unless_owner(role, user_id, e["agent_id"])
    return success_obj(public(e))


@bp.route("/brokerage/ledger-entries", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_entries(user_id, role):
    agent_id = parse_str_filter("agent_id")
    deal_id = parse_str_filter("deal_id")
    entry_type = parse_enum_filter("entry_type", ENTRY_TYPES)
    items = list(db.ledger_entries.values())
    if role == "Agent":
        items = [e for e in items if e["agent_id"] == user_id]
    if agent_id is not None:
        items = [e for e in items if e["agent_id"] == agent_id]
    if deal_id is not None:
        items = [e for e in items if e.get("deal_id") == deal_id]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    return list_response(by_created(items))
