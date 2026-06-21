"""Fine endpoints (PRD §3.10)."""

from flask import Blueprint, request

import clock
import db
import errors
import response
from middleware import authenticate, require_roles, ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER
from services import serialize, derive
from routes import helpers

bp = Blueprint("fines", __name__)

SETTLEMENT_STATUSES = {"UNPAID", "PAID", "WAIVED"}


@bp.get("/library/fines/<fid>")
def get_fine(fid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.fines, fid)
    return response.object_response(serialize.fine(record))


@bp.get("/library/fines")
def list_fines():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    patron_id = request.args.get("patron_id")
    loan_id = request.args.get("loan_id")
    settlement_status = helpers.enum_filter("settlement_status", SETTLEMENT_STATUSES)
    records = [
        f for f in db.fines.values()
        if (patron_id is None or f["patron_id"] == patron_id)
        and (loan_id is None or f.get("loan_id") == loan_id)
        and (settlement_status is None or f["settlement_status"] == settlement_status)
    ]
    return helpers.list_response(records, serialize.fine)


def _settle(record, new_status):
    record["settlement_status"] = new_status
    record["settled_at"] = clock.now()
    db.touch(record)
    # cascade: recompute patron balance and possibly lift the block
    derive.reconcile_patron_by_id(record["patron_id"])


@bp.post("/library/fines/<fid>/pay")
def pay_fine(fid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.fines, fid)
    if record["settlement_status"] != "UNPAID":
        raise errors.invalid_state("Fine is not UNPAID.")
    _settle(record, "PAID")
    return response.object_response(serialize.fine(record))


@bp.post("/library/fines/<fid>/waive")
def waive_fine(fid):
    caller = authenticate()
    require_roles(caller, {ROLE_MANAGER})
    record = helpers.find_or_404(db.fines, fid)
    if record["settlement_status"] != "UNPAID":
        raise errors.invalid_state("Fine is not UNPAID.")
    _settle(record, "WAIVED")
    return response.object_response(serialize.fine(record))
