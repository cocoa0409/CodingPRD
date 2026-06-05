from flask import Blueprint, request

from db import db
from models import serialize
from middleware import get_identity
from helpers import (lookup, parse_pagination, paginate, sort_by_created,
                     require_tenant_owns_lease)
from response import success, list_response

bp = Blueprint("ledger", __name__)


@bp.get("/ledger-entries/<ledger_entry_id>")
def get_ledger_entry(ledger_entry_id):
    user_id, role = get_identity()
    entry = lookup(db.ledger_entries, ledger_entry_id, "ledger entry")
    lease = db.leases.get(entry["lease_id"])
    if lease is not None:
        require_tenant_owns_lease(user_id, role, lease)
    return success(serialize(entry), 200)


@bp.get("/ledger-entries")
def list_ledger_entries():
    user_id, role = get_identity()
    limit, offset = parse_pagination()
    items = list(db.ledger_entries.values())
    lease_id = request.args.get("lease_id")
    if lease_id is not None:
        items = [e for e in items if e["lease_id"] == lease_id]
    if role == "Tenant":
        owned = {l["id"] for l in db.leases.values() if l["tenant_id"] == user_id}
        items = [e for e in items if e["lease_id"] in owned]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize(e) for e in page], total, limit, offset)
