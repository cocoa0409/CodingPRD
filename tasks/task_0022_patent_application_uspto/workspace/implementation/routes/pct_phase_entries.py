"""PCT national phase entries."""

from flask import Blueprint, request

from db import db, new_id, parse_iso
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.body import get_json_body, require_string
from services.dateutil import add_months
from services.pagination import parse_pagination, slice_sorted
from services.serialize import pct_phase_entry_to_wire


bp = Blueprint("pct_phase_entries", __name__)


@bp.route("/pct-phase-entries", methods=["POST"])
@require_roles("Applicant")
def create_pct_phase_entry(_user_id, _role):
    body = get_json_body()
    application_id = require_string(body, "application_id")
    intl_filing_raw = require_string(body, "pct_international_filing_date")

    # Parse date
    try:
        intl_dt = parse_iso(intl_filing_raw)
    except ValueError:
        raise_api("ERR_INVALID_REQUEST", "pct_international_filing_date is not a valid ISO 8601 datetime")

    # Priority 5: FK existence
    app = db.applications.get(application_id)
    if app is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND",
            f"Application {application_id} not found",
        )

    # Application type must be PCT_NATIONAL
    if app["application_type"] != "PCT_NATIONAL":
        raise_api(
            "ERR_INVALID_STATE",
            "PCTPhaseEntry can only be created for application_type=PCT_NATIONAL",
        )

    # Priority 21: VAL-PCT-SINGLE-ENTRY (singleton)
    for existing in db.pct_phase_entries.values():
        if existing["application_id"] == application_id:
            raise_api(
                "ERR_PCT_PHASE_ENTRY_DUPLICATE",
                "A PCTPhaseEntry already exists for this application",
            )

    now = db.current_utc_dt()

    # The pct_international_filing_date must be strictly before now
    if intl_dt >= now:
        raise_api(
            "ERR_INVALID_REQUEST",
            "pct_international_filing_date must be strictly before now",
        )

    national_phase_due = add_months(intl_dt, 30)

    # Priority 11: VAL-PCT-LATE — created_at <= national_phase_due_date
    if now > national_phase_due:
        raise_api(
            "ERR_PCT_NATIONAL_PHASE_LATE",
            "PCTPhaseEntry created more than 30 months after pct_international_filing_date",
        )

    pid = new_id()
    entry = {
        "id": pid,
        "application_id": application_id,
        "pct_international_filing_date": intl_dt,
        "national_phase_due_date": national_phase_due,
        "phase_status": "ENTERED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.pct_phase_entries[pid] = entry
    return success(pct_phase_entry_to_wire(entry), http_status=201)


@bp.route("/pct-phase-entries/<pid>", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin")
def get_pct(pid, **_):
    e = db.pct_phase_entries.get(pid)
    if e is None:
        raise_api(
            "ERR_APPLICATION_NOT_FOUND", f"PCTPhaseEntry {pid} not found"
        )
    return success(pct_phase_entry_to_wire(e))


@bp.route("/pct-phase-entries", methods=["GET"])
@require_roles("Applicant", "USPTOAdmin")
def list_pct(**_):
    limit, offset = parse_pagination()
    app_filter = request.args.get("application_id")
    items = []
    for e in db.pct_phase_entries.values():
        if app_filter and e["application_id"] != app_filter:
            continue
        items.append(e)
    page, total = slice_sorted(items, limit, offset)
    return list_success(
        [pct_phase_entry_to_wire(x) for x in page], limit, offset, total
    )
