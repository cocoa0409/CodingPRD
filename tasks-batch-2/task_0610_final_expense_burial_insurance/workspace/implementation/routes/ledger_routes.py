"""LedgerEntry read endpoints (PRD §2.5)."""
from flask import Blueprint, request

import db
from errors import err
from helpers import serialize, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success

bp = Blueprint("ledger", __name__)


@bp.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "ClaimsExaminer", "Policyholder"})
    entry = db.ledger_entries.get(entry_id)
    if entry is None:
        raise err("ERR_NOT_FOUND", "LedgerEntry not found")
    return success(serialize(entry), status=200, response_type="object")


@bp.route("/ledger-entries", methods=["GET"])
def list_entries():
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "ClaimsExaminer", "Policyholder"})
    items = list(db.ledger_entries.values())
    policy_id = request.args.get("policy_id")
    entry_type = request.args.get("entry_type")
    if policy_id:
        items = [e for e in items if e["policy_id"] == policy_id]
    if entry_type:
        items = [e for e in items if e["entry_type"] == entry_type]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], status=200, response_type="array", pagination=meta)
