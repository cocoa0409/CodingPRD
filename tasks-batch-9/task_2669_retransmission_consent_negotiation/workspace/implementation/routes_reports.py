"""Subscriber reports, audit findings and their cascades (PRD 3.4)."""
from flask import Blueprint

import derive
from common import (
    authenticate,
    body_json,
    pagination,
    paginate,
    query_enum,
    query_str,
    take_dt,
    take_enum,
    take_int,
    take_str,
)
from envelope import array_response, object_response
from errors import ApiError
from store import (
    ALL_ROLES,
    AUDIT_RIGHTS_WINDOW_DAYS,
    NO_NETWORK_ROLES,
    add_days,
    base_row,
    clock,
    db,
    fmt_dt,
    now_iso,
    parse_iso,
    touch,
)

bp = Blueprint("reports", __name__)

REPORT_STATUSES = ["REPORTED", "UNDER_AUDIT", "ADJUSTED", "ACCEPTED"]
FINDING_STATUSES = ["OPEN", "SUBSTANTIATED", "DISMISSED"]
SETTLEMENT_STATUSES = ["ISSUED", "TRUED_UP", "VOIDED"]
PRICEABLE_STATUSES = ["REPORTED", "UNDER_AUDIT", "ADJUSTED", "ACCEPTED"]


@bp.post("/retrans/subscriber-reports")
def create_report():
    user_id, _role = authenticate(["DistributorRep"])
    body = body_json()
    station_id = take_str(body, "station_id")
    period_label = take_str(body, "period_label", min_len=1, max_len=20)
    period_start = take_dt(body, "period_start_utc")
    period_end = take_dt(body, "period_end_utc")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'period_end_utc' must be strictly after 'period_start_utc'.")
    reported = take_int(body, "reported_subscriber_count", minimum=0)
    excluded = take_int(body, "excluded_free_trial_count", minimum=0, required=False, default=0)
    if excluded > reported:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'excluded_free_trial_count' may not exceed 'reported_subscriber_count'.")

    derive.get_station(station_id)
    distributor = derive.get_distributor(user_id)

    for existing in derive.rows_of(db.reports, station_id=station_id,
                                  distributor_id=user_id, period_label=period_label):
        raise ApiError("ERR_REPORT_PERIOD_DUPLICATE")

    row = base_row()
    row.update({
        "station_id": station_id,
        "distributor_id": user_id,
        "period_label": period_label,
        "period_start_utc": fmt_dt(period_start),
        "period_end_utc": fmt_dt(period_end),
        "reported_subscriber_count": reported,
        "excluded_free_trial_count": excluded,
        "measurement_method_snapshot": distributor["subscriber_measurement_method"],
        "status": "REPORTED",
    })
    db.reports[row["id"]] = row
    return object_response(derive.report_json(row), 201)


@bp.get("/retrans/subscriber-reports")
def list_reports():
    authenticate(NO_NETWORK_ROLES)
    limit, offset = pagination()
    station_id = query_str("station_id")
    distributor_id = query_str("distributor_id")
    period_label = query_str("period_label")
    status = query_enum("status", REPORT_STATUSES)
    rows = derive.rows_of(db.reports)
    if station_id is not None:
        rows = [r for r in rows if r["station_id"] == station_id]
    if distributor_id is not None:
        rows = [r for r in rows if r["distributor_id"] == distributor_id]
    if period_label is not None:
        rows = [r for r in rows if r["period_label"] == period_label]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset, derive.report_json)
    return array_response(items, limit, offset, total)


@bp.get("/retrans/subscriber-reports/<report_id>")
def read_report(report_id):
    authenticate(NO_NETWORK_ROLES)
    report = derive.get_report(report_id)
    return object_response(derive.report_json(report))


@bp.post("/retrans/subscriber-reports/<report_id>/audit-findings")
def create_finding(report_id):
    user_id, _role = authenticate(["StationGroupNegotiator"])
    body = body_json()
    adjustment = take_int(body, "adjustment_subscribers")
    if adjustment == 0 or abs(adjustment) > 500000:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'adjustment_subscribers' must be non-zero and at most 500000 in magnitude.")
    basis_note = take_str(body, "basis_note", min_len=1, max_len=500)
    report = derive.get_report(report_id)
    # Priority 6 -- the negotiator must be the station named on the report.
    if user_id != report["station_id"]:
        raise ApiError("ERR_NOT_COUNTERPARTY")
    # Priority 13 -- an ACCEPTED report is closed to audit.
    if report["status"] not in ("REPORTED", "UNDER_AUDIT", "ADJUSTED"):
        raise ApiError("ERR_REPORT_NOT_AUDITABLE")
    # Priority 21 -- the 180-day audit-rights window is inclusive of its boundary.
    period_end = parse_iso(report["period_end_utc"])
    if period_end is None or clock() > add_days(period_end, AUDIT_RIGHTS_WINDOW_DAYS):
        raise ApiError("ERR_AUDIT_WINDOW_EXPIRED")

    row = base_row()
    row.update({
        "subscriber_report_id": report_id,
        "adjustment_subscribers": adjustment,
        "basis_note": basis_note,
        "status": "OPEN",
        "resolution_note": None,
        "opened_at_utc": now_iso(),
    })
    db.findings[row["id"]] = row
    if report["status"] in ("REPORTED", "ADJUSTED"):
        report["status"] = "UNDER_AUDIT"
        touch(report)
    return object_response(derive.finding_json(row), 201)


@bp.get("/retrans/subscriber-reports/<report_id>/audit-findings")
def list_findings(report_id):
    authenticate(NO_NETWORK_ROLES)
    limit, offset = pagination()
    status = query_enum("status", FINDING_STATUSES)
    derive.get_report(report_id)
    rows = derive.findings_of(report_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset, derive.finding_json)
    return array_response(items, limit, offset, total)


@bp.get("/retrans/subscriber-reports/<report_id>/fee-settlements")
def list_report_settlements(report_id):
    authenticate(NO_NETWORK_ROLES)
    limit, offset = pagination()
    status = query_enum("status", SETTLEMENT_STATUSES)
    derive.get_report(report_id)
    rows = derive.rows_of(db.settlements, subscriber_report_id=report_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset, derive.settlement_json)
    return array_response(items, limit, offset, total)


@bp.post("/retrans/audit-findings/<finding_id>/resolve")
def resolve_finding(finding_id):
    authenticate(["ComplianceOfficer"])
    body = body_json()
    resolution = take_enum(body, "resolution", ["SUBSTANTIATED", "DISMISSED"])
    note = take_str(body, "resolution_note", min_len=1)
    finding = derive.get_finding(finding_id)
    # Priority 14 -- the finding must still be OPEN.
    if finding["status"] != "OPEN":
        raise ApiError("ERR_AUDIT_FINDING_NOT_OPEN")
    report = db.reports.get(finding["subscriber_report_id"])
    if report is None or report["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_REPORT_NOT_AUDITABLE")

    finding["resolution_note"] = note
    if resolution == "SUBSTANTIATED":
        finding["status"] = "SUBSTANTIATED"
        touch(finding)
        # Level 2 -- the report advances and re-derives its audited basis.
        report["status"] = "ADJUSTED"
        touch(report)
        # Level 3 -- ISSUED settlements drawing on this report are flagged only.
        for settlement in derive.rows_of(db.settlements, subscriber_report_id=report["id"]):
            if settlement["status"] == "ISSUED":
                settlement["true_up_required"] = True
                touch(settlement)
        distributor = db.distributors.get(report["distributor_id"])
        if distributor is not None:
            touch(distributor)
    else:
        finding["status"] = "DISMISSED"
        touch(finding)
        siblings = derive.findings_of(report["id"])
        if not any(f["status"] in ("OPEN", "SUBSTANTIATED") for f in siblings):
            report["status"] = "REPORTED"
            touch(report)
    return object_response(derive.finding_json(finding))
