"""The append-only attendance ledger — read and list only (PRD §3.6)."""

from flask import Blueprint

import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import ATTENDANCE_CODES, listing

bp = Blueprint("attendance_entries", __name__)

ROLES = ["ProgramAdministrator", "CaseManager", "NurseReviewer"]

LIST_QUERY = {
    "case_id": {"type": "string"},
    "session_id": {"type": "string"},
    "reversal_of_entry_id": {"type": "string"},
    "attendance_code": {"type": "string", "enum": ATTENDANCE_CODES},
    "service_date": {"type": "date"},
}


@bp.get("/hhi/attendance-entries/<entry_id>")
@endpoint(ROLES)
def read_entry(entry_id):
    row = db.get("ledger_entries", entry_id)
    if row is None:
        raise ApiError("ERR_LEDGER_ENTRY_NOT_FOUND")
    return middleware.obj(row)


@bp.get("/hhi/attendance-entries")
@endpoint(ROLES, query=LIST_QUERY)
def list_entries():
    return listing("ledger_entries", LIST_QUERY)
