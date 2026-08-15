from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success
from services import posture
from services.common import quarter_of, stamp_new, touch
from services.pagination import get_pagination, paginate
from services.serialize import watchlist_entry as ser_entry
from services.validate import body_json, require_fields

bp = Blueprint("watchlist", __name__)


@bp.get("/loans/<lid>/watchlist-entries")
def list_entries(lid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer", "Borrower"])
    loan = db.loans.get(lid)
    if not mw.read_scope_allows(actor, "loan", loan):
        raise errors.not_found("Loan not found")
    limit, offset = get_pagination()
    items = [e for e in db.watchlist_entries.values() if e["loan_id"] == lid]
    status = request.args.get("status")
    criterion = request.args.get("criterion")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if criterion is not None:
        items = [e for e in items if e["criterion"] == criterion]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, pg = paginate([ser_entry(e) for e in items], limit, offset)
    return success(page, pagination=pg, is_array=True)


def _resolution_gate(entry):
    """REPORTING_DELINQUENCY entries need an ACCEPTED statement for period+type."""
    if entry["criterion"] != "REPORTING_DELINQUENCY":
        return
    ref = entry.get("source_ref") or ""
    # source_ref format: "period 2026Q2 OPERATING_STATEMENT"
    parts = ref.split(" ")
    if len(parts) != 3 or parts[0] != "period":
        return
    label = parts[1]
    stmt_type = parts[2]
    for s in db.financial_statements.values():
        if (
            s["loan_id"] == entry["loan_id"]
            and s["statement_type"] == stmt_type
            and s["status"] == "ACCEPTED"
        ):
            from services.common import quarter_label
            if quarter_label(s["period_start_dt"]) == label:
                return
    raise errors.ApiError(
        errors.ERR_RESOLUTION_BLOCKED,
        "An ACCEPTED statement for the entry's period and type is required", 409)


@bp.post("/watchlist-entries/<eid>/resolve")
def resolve_entry(eid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer", "SpecialServicer"])
    e = db.watchlist_entries.get(eid)
    if e is None:
        raise errors.not_found("WatchlistEntry not found")
    if e["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE entry can be resolved")
    _resolution_gate(e)
    e["status"] = "RESOLVED"
    e["resolved_at"] = db.fmt_ts(db.get_clock())
    touch(e)
    loan = db.loans.get(e["loan_id"])
    posture.reevaluate_servicing(loan)
    return success(ser_entry(e))


@bp.post("/watchlist-entries/<eid>/escalate")
def escalate_entry(eid):
    actor = mw.authenticate()
    mw.authorize(actor, ["MasterServicer"])
    e = db.watchlist_entries.get(eid)
    if e is None:
        raise errors.not_found("WatchlistEntry not found")
    if e["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE entry can be escalated")
    loan = db.loans.get(e["loan_id"])
    if loan["servicing_status"] != "WATCHLIST":
        raise errors.invalid_state("Loan must be in WATCHLIST to escalate")
    posture.escalate_to_special_servicing(loan, e)
    return success(ser_entry(e))
