"""CommissionEntry read endpoints (PRD §3.7). Agent-only ledger."""
from flask import Blueprint, request

from db import db, lock
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import lookup, paginate, public

bp = Blueprint("commission_entries", __name__)


@bp.route("/commission-entries", methods=["GET"])
def list_commission_entries():
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        items = list(db.commission_entries.values())
        for field in ("agency_id", "booking_id", "status"):
            val = request.args.get(field)
            if val is not None:
                items = [e for e in items if e[field] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/commission-entries/<entry_id>", methods=["GET"])
def get_commission_entry(entry_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        record = lookup("CommissionEntry", entry_id)
        return object_response(public(record), status=200)
