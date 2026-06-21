"""Event log reads, actuals corrections, and finalize (PRD §3.5)."""
from flask import Blueprint

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success
import helpers
from services import calculations as calc
from services import booking_logic as bl
from services.serialize import plain_out

bp = Blueprint("event_logs", __name__)

_ACTUAL_TS_FIELDS = (
    "actual_setup_start", "actual_coverage_start",
    "actual_coverage_end", "actual_teardown_end",
)


@bp.route("/event-logs/<elog_id>", methods=["GET"])
def get_event_log(elog_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager", "FinanceClerk", "PlatformAdmin"})
    rec = db.event_logs.get(elog_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Event log not found.")
    return success(plain_out(rec), 200)


@bp.route("/event-logs/<elog_id>", methods=["PATCH"])
def patch_event_log(elog_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = db.event_logs.get(elog_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Event log not found.")
    if rec.get("finalized"):
        raise err(errors.ERR_INVALID_STATE, "Cannot correct a finalized event log.")
    body = helpers.get_json()

    # Apply only the supplied fields. Each parses against its expected type.
    for f in _ACTUAL_TS_FIELDS:
        dt = helpers.parse_optional_datetime(body, f)
        if dt is not None:
            rec[f] = _iso(dt)
            rec["_" + f + "_dt"] = dt
    if "actual_print_count" in body and body.get("actual_print_count") is not None:
        rec["actual_print_count"] = helpers.optional_int(
            body, "actual_print_count", rec.get("actual_print_count"), minimum=0)

    db.touch(rec)
    return success(plain_out(rec), 200)


@bp.route("/event-logs/<elog_id>/finalize", methods=["POST"])
def finalize_event_log(elog_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager"})
    rec = db.event_logs.get(elog_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Event log not found.")
    body = helpers.get_json()

    # Well-formedness (priority 20): all actuals + OCC field present & typed.
    setup_start = helpers.parse_datetime(body, "actual_setup_start")
    coverage_start = helpers.parse_datetime(body, "actual_coverage_start")
    coverage_end = helpers.parse_datetime(body, "actual_coverage_end")
    teardown_end = helpers.parse_datetime(body, "actual_teardown_end")
    print_count = helpers.require_int(body, "actual_print_count", minimum=0)
    expected_version = helpers.require_int(body, "expected_eventlog_version")

    booking = db.bookings.get(rec["booking_id"])

    # State (priority 30): not yet finalized + parent IN_SERVICE + ordered ts.
    if rec.get("finalized"):
        raise err(errors.ERR_INVALID_STATE, "Event log already finalized.")
    if not booking or booking["schedule_status"] != "IN_SERVICE":
        raise err(errors.ERR_INVALID_STATE, "Finalize requires the parent booking IN_SERVICE.")
    if not (setup_start <= coverage_start < coverage_end <= teardown_end):
        raise err(errors.ERR_INVALID_STATE, "Actual timestamps are not consistently ordered.")

    # OCC (priority 40).
    if expected_version != rec["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_eventlog_version does not match event log.")

    # Commit actuals.
    rec["actual_setup_start"] = _iso(setup_start)
    rec["actual_coverage_start"] = _iso(coverage_start)
    rec["actual_coverage_end"] = _iso(coverage_end)
    rec["actual_teardown_end"] = _iso(teardown_end)
    rec["actual_print_count"] = print_count
    rec["_actual_setup_start_dt"] = setup_start
    rec["_actual_coverage_start_dt"] = coverage_start
    rec["_actual_coverage_end_dt"] = coverage_end
    rec["_actual_teardown_end_dt"] = teardown_end
    rec["finalized"] = True
    db.touch(rec)

    # Final settlement -> booking.final_subtotal, balance_due.
    package = db.packages[booking["package_id"]]
    lines = bl.addon_lines_for(booking["id"])
    final_subtotal = calc.final_settlement(booking, package, rec, lines)
    booking["final_subtotal"] = final_subtotal
    booking["balance_due"] = final_subtotal - booking["amount_paid"]
    db.touch(booking)

    return success(plain_out(rec), 200)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
