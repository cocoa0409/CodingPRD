"""LedgerEntry read endpoints (PRD §4)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_principal, require_role
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("ledger", __name__)


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    return list_filtered(
        db.ledger_entries,
        [
            ("member_id", "member_id", "str"),
            ("visit_id", "visit_id", "str"),
            ("day_pass_id", "day_pass_id", "str"),
            ("kind", "kind", "str"),
            ("status", "status", "str"),
        ],
    )


@bp.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_ledger(entry_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    le = db.ledger_entries.items.get(entry_id)
    if not le:
        raise errors.not_found("Ledger entry not found")
    return success(serialize(le))
