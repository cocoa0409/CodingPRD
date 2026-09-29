"""The immutable wear ledger (PRD 2.4, 2.9). Entries are appended by side effects
only, so these two reads are their sole discovery channel."""

import middleware
import response
from db import db
from routes.blueprint import bp
from routes.common import listing

FILTERS = {
    "field_id": "field_id",
    "booking_id": "booking_id",
    "maintenance_task_id": "maintenance_task_id",
    "entry_type": "entry_type",
}


@bp.get("/usage-ledger-entries")
def list_ledger_entries():
    middleware.authenticate(middleware.ALL_ROLES)
    return listing(db.ledger_entries, FILTERS)


@bp.get("/usage-ledger-entries/<entry_id>")
def read_ledger_entry(entry_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.ledger_or_404(entry_id))
