"""Reserve ledger reads.  Ledger rows are immutable and ordered by sequence_no."""
from flask import Blueprint, request

import derive
import store
import validate
from envelope import ok
from routes.common import begin, listing

bp = Blueprint("reserve_entries", __name__)


@bp.get("/reserve-entries")
def list_entries():
    begin()
    rows = list(store.reserve_entries.values())
    for param, field in (("event_id", "event_id"), ("claim_id", "claim_id"),
                         ("reverses_entry_id", "reverses_entry_id"),
                         ("entry_type", "entry_type")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.reserve_entry_out, sort_key="sequence_no")


@bp.get("/reserve-entries/<reserve_entry_id>")
def read_entry(reserve_entry_id):
    begin()
    return ok(derive.reserve_entry_out(validate.reserve_entry(reserve_entry_id)))
