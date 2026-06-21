"""LedgerEntry read endpoints (§3.12). Append-only; lean entity."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common

bp = Blueprint("ledger_entries", __name__)

READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.ledger_entries.values())
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)


@bp.route("/ledger-entries/<ledger_entry_id>", methods=["GET"])
def get_ledger(ledger_entry_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    rec = db.ledger_entries.get(ledger_entry_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "LedgerEntry not found")
    return success(public(rec))
