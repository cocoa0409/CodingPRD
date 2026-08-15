"""ComplianceCalendarEntry routes: read APIs and manual waiver."""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from envelope import list_response, serialize, success
from errors import err, ERR_INVALID_STATE
from fields import CALENDAR_ENTRY
from store import db, now, touch
from validate import apply_filters, paginate
from workflows import get_or_404

bp = Blueprint("calendar", __name__)


@bp.route("/calendar-entries/<entryId>", methods=["GET"])
def get_entry(entryId):
    authenticate(ALL_ROLES)
    entry = get_or_404(db.compliance_calendar_entries, entryId)
    return success(serialize(entry, CALENDAR_ENTRY), code=200)


@bp.route("/calendar-entries", methods=["GET"])
def list_entries():
    authenticate(ALL_ROLES)
    filters = {
        "filing_id": request.args.get("filing_id"),
        "wave_id": request.args.get("wave_id"),
        "objection_id": request.args.get("objection_id"),
        "entry_type": request.args.get("entry_type"),
        "status": request.args.get("status"),
    }
    items = apply_filters(list(db.compliance_calendar_entries.values()), filters)
    page, total, limit, offset = paginate(items)
    return list_response([serialize(e, CALENDAR_ENTRY) for e in page], total, limit, offset)


@bp.route("/calendar-entries/<entryId>/waive", methods=["POST"])
def waive_entry(entryId):
    authenticate({"ComplianceOfficer"})
    with db.lock:
        entry = get_or_404(db.compliance_calendar_entries, entryId)
        if entry["status"] != "PENDING":
            raise err(ERR_INVALID_STATE)
        entry["status"] = "WAIVED"
        entry["resolved_at"] = now()
        touch(entry)
    return success(serialize(entry, CALENDAR_ENTRY), code=200)
