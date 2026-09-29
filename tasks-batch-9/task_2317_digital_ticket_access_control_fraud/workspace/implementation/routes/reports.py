"""ReconciliationReport endpoints (PRD 3.9)."""

from flask import Blueprint

from db import base_record, db, public, sort_created_asc, touch
from errors import ApiError
from middleware import auth, f_int, f_str, get_body, q
from response import ok
from services import calc
from services.domain import append_audit, get_or_404, scan_events_of_event
from routes._common import filter_eq, paginated

bp = Blueprint("reports", __name__)

REPORT_READERS = ("SecurityInvestigator", "VenueAdmin")


def _figures(event, reported_attendance):
    scan_derived = calc.reconciled_attendance(scan_events_of_event(event["id"]))
    return calc.reconciliation_variance(
        reported_attendance, scan_derived, event["fire_code_capacity"]
    )


def _write_figures(report, figures):
    report["scan_derived_attendance"] = figures["scan_derived_attendance"]
    report["variance_count"] = figures["variance_count"]
    report["variance_pct"] = figures["variance_pct"]
    report["fire_code_breach"] = figures["fire_code_breach"]


@bp.route("/events/<event_id>/reconciliation-reports", methods=["POST"])
def create_report(event_id):
    auth(("VenueAdmin",))
    body = get_body()
    reported_attendance = f_int(body, "reported_attendance", minimum=0)
    expected_event_version = f_int(body, "expected_event_version")

    event = get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    if expected_event_version != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION")
    # Rule 13 admits RECONCILED on purpose so that rule 17 owns the refusal.
    if event["status"] not in ("CLOSED", "RECONCILED"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")
    if event["status"] == "RECONCILED":
        raise ApiError("ERR_EVENT_ALREADY_RECONCILED")
    for other in db.reports.values():
        if other["event_id"] == event_id and other["status"] == "FINAL":
            raise ApiError("ERR_EVENT_ALREADY_RECONCILED")

    rec = base_record()
    rec["event_id"] = event_id
    rec["reported_attendance"] = reported_attendance
    _write_figures(rec, _figures(event, reported_attendance))
    rec["override_reason"] = None
    rec["status"] = "DRAFT"
    rec["finalized_by_user_id"] = None
    db.reports[rec["id"]] = rec

    touch(event)
    return ok(public(rec), 201)


@bp.route("/reconciliation-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    auth(REPORT_READERS)
    report = get_or_404(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    return ok(public(report))


@bp.route("/reconciliation-reports", methods=["GET"])
def list_reports():
    auth(REPORT_READERS)
    rows = sort_created_asc(list(db.reports.values()))
    rows = filter_eq(rows, "event_id", q("event_id"))
    rows = filter_eq(rows, "status", q("status"))
    return paginated(rows)


@bp.route("/reconciliation-reports/<report_id>/finalize", methods=["POST"])
def finalize_report(report_id):
    user_id, role = auth(("VenueAdmin",))
    body = get_body()
    override_reason = f_str(body, "override_reason", required=False)
    report = get_or_404(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    if report["status"] not in ("DRAFT", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or REOPENED report may be finalized.")

    event = db.events[report["event_id"]]
    # Figures are always recomputed rather than trusted.
    _write_figures(report, _figures(event, report["reported_attendance"]))
    if override_reason:
        report["override_reason"] = override_reason

    if not calc.variance_within_tolerance(report["variance_pct"]) and not override_reason:
        raise ApiError("ERR_ATTENDANCE_VARIANCE_UNRESOLVED")

    report["status"] = "FINAL"
    report["finalized_by_user_id"] = user_id
    touch(report)

    event["status"] = "RECONCILED"
    touch(event)

    append_audit(
        event["id"], "RECONCILIATION_REPORT", report["id"], "RECONCILIATION_FINALIZED",
        role, user_id,
        "Report %s finalized: reported %d, scan-derived %d, variance %d (%s%%), "
        "fire_code_breach %s; event -> RECONCILED.%s"
        % (
            report["id"], report["reported_attendance"], report["scan_derived_attendance"],
            report["variance_count"], report["variance_pct"],
            "true" if report["fire_code_breach"] else "false",
            (" Override: " + override_reason) if override_reason else "",
        ),
    )
    return ok(public(report))


@bp.route("/reconciliation-reports/<report_id>/reopen", methods=["POST"])
def reopen_report(report_id):
    user_id, role = auth(("VenueAdmin",))
    body = get_body()
    reason = f_str(body, "reason", allow_empty=False)
    report = get_or_404(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    if report["status"] != "FINAL":
        raise ApiError("ERR_INVALID_STATE", "Only a FINAL report may be reopened.")

    report["status"] = "REOPENED"
    report["finalized_by_user_id"] = None
    touch(report)

    event = db.events[report["event_id"]]
    event["status"] = "CLOSED"
    touch(event)

    # PRD 8.5 enumerates the verbs this system writes and does not include a
    # reopen verb, and the reopen paragraph names no audit entry among its
    # effects, so reopening writes no audit row.
    return ok(public(report))
