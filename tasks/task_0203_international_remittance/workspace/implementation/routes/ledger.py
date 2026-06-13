"""LedgerEntry read-only endpoints (PRD §2.9, §3.8 conservation audit)."""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import get_user_context, require_role
from services.common import public, paginate

bp = Blueprint("ledger", __name__)


@bp.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "ComplianceOfficer"})
    entry = db.ledger_entries.get(entry_id)
    if entry is None:
        raise err("ERR_NOT_FOUND", "Ledger entry not found")
    return success(public(entry), 200)


@bp.route("/ledger-entries", methods=["GET"])
def list_entries():
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "ComplianceOfficer", "RemittanceAgent"})
    items = list(db.ledger_entries.values())
    tid = request.args.get("transfer_id")
    etype = request.args.get("entry_type")
    if tid is not None:
        items = [e for e in items if e["transfer_id"] == tid]
    if etype is not None:
        items = [e for e in items if e["entry_type"] == etype]
    page, meta = paginate(items)
    return success([public(e) for e in page], 200, pagination=meta)
