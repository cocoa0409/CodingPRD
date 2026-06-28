"""LedgerEntry collection endpoints (PRD §2.6, §4)."""
from flask import Blueprint, request

from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response, member_owns
from services.serialize import ledger_entry_out
from state import store

bp = Blueprint("ledger", __name__)


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    items = list(store.ledger_entries.values())
    member_id = request.args.get("member_id")
    reward_claim_id = request.args.get("reward_claim_id")
    cashout_id = request.args.get("cashout_id")
    referral_id = request.args.get("referral_id")
    entry_type = request.args.get("entry_type")

    if role == "Member":
        # A member may only see their own ledger entries.
        items = [e for e in items if e["member_id"] == user_id]

    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if reward_claim_id is not None:
        items = [e for e in items if e.get("reward_claim_id") == reward_claim_id]
    if cashout_id is not None:
        items = [e for e in items if e.get("cashout_id") == cashout_id]
    if referral_id is not None:
        items = [e for e in items if e.get("referral_id") == referral_id]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    return list_response(items, ledger_entry_out)


@bp.route("/ledger-entries/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    e = store.ledger_entries.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Ledger entry not found.")
    if role == "Member" and not member_owns(user_id, e["member_id"]):
        raise err("ERR_FORBIDDEN", "A member may only read their own ledger entries.")
    return object_response(store.clock, ledger_entry_out(store, e))
