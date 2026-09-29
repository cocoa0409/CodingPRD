"""The append-only compliance ledger and the logical-clock control endpoint."""

import calc
import db as dbmod
import repo
import validation as v
from errors import ApiError
from middleware import ANY_ROLE
from response import object_response
from routing import route


@route("/pip/compliance-ledger-entries/<row_id>", ["GET"], ANY_ROLE)
def get_ledger_entry(row_id):
    return repo.single(repo.must_find("ledger", row_id))


@route("/pip/compliance-ledger-entries", ["GET"], ANY_ROLE)
def list_ledger_entries():
    limit, offset = v.pagination()
    rows = repo.rows("ledger")
    for field in ("plan_id", "item_id", "entry_type"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/_clock/set_current_utc", ["POST"], ANY_ROLE)
def set_current_utc():
    body = v.body_json()
    v.require(body, "current_utc")
    raw = v.get_str(body, "current_utc", min_len=1)
    instant = calc.parse_datetime(raw)
    if instant is None:
        raise ApiError("ERR_VALIDATION", "current_utc must be an ISO 8601 instant")
    dbmod.db.clock = instant
    return object_response({"current_utc": raw})
