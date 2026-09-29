"""Append-only fee ledger reads (PRD 3.6)."""
from flask import Blueprint

from db import db
from middleware import GUILD_ADMINISTRATOR, STUDIO_EXECUTIVE, fetch, require
from response import ok
from routes.common import list_out, match, out
from validation import filter_value

bp = Blueprint("ledger", __name__)

READ_ROLES = (STUDIO_EXECUTIVE, GUILD_ADMINISTRATOR)


@bp.get("/fee-ledger-entries/<entry_id>")
def get_entry(entry_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.ledger, entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")))


@bp.get("/fee-ledger-entries")
def list_entries():
    require(*READ_ROLES)
    rows = list(db.ledger.values())
    rows = match(rows, "season_id", filter_value("season_id"))
    rows = match(rows, "assignment_id", filter_value("assignment_id"))
    rows = match(rows, "writer_id", filter_value("writer_id"))
    rows = match(rows, "entry_type", filter_value("entry_type"))
    return list_out(rows)
