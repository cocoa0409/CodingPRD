"""The append-only budget ledger of record."""

from flask import Blueprint

import db
import response
import validation as V
from middleware import require
from services import calc, serialize

bp = Blueprint("ledger", __name__)

READ_ROLES = ("BrandProgramLead", "MediaBuyer", "RecruitingOps")


@bp.route("/budget-ledger-entries/<entry_id>", methods=["GET"])
@require(*READ_ROLES)
def get_entry(entry_id):
    row = calc.must_get(db.ledger, entry_id, "ERR_RECORD_NOT_FOUND")
    return response.ok(serialize.ledger_entry(row))


@bp.route("/budget-ledger-entries", methods=["GET"])
@require(*READ_ROLES)
def list_entries():
    limit, offset = V.pagination()
    rows = sorted(db.ledger.values(), key=lambda r: (r["sequence_no"], r["created_at"]))
    for name in ("program_id", "job_family_id", "bucket", "entry_type",
                 "source_type", "source_id"):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.ledger_entry(r) for r in page], meta)
