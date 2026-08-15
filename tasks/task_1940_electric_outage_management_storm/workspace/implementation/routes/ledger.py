"""CostLedgerEntry read endpoints (append-only; ordered posted_at ASC with
created_at ASC tie-break)."""
from flask import Blueprint, request

from db import db, parse_iso
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import (
    paginate, get_ledger_entry, serialize_ledger_entry,
)

bp = Blueprint("ledger", __name__)


@bp.route("/om/cost-ledger-entries/<eid>", methods=["GET"])
def get_one(eid):
    require_roles(ALL_ROLES)
    e = get_ledger_entry(eid)
    return success_object(serialize_ledger_entry(e))


@bp.route("/om/cost-ledger-entries", methods=["GET"])
def list_entries():
    require_roles(ALL_ROLES)
    items = list(db.cost_ledger_entries.values())
    for param in ("storm_event_id", "work_order_id", "entry_type",
                  "county_code", "reversed_entry_id"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    items.sort(key=lambda e: (parse_iso(e["posted_at"]), parse_iso(e["created_at"]), e["_mono"]))
    page, limit, offset, total = paginate(items)
    return success_list([serialize_ledger_entry(e) for e in page], limit, offset, total)
