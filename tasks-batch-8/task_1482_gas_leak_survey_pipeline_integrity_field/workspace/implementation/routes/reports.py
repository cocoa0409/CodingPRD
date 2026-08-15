"""ComplianceReport endpoints (PRD §3.11)."""
from datetime import timedelta

from flask import g, request

from db import STORE, make_entity, now, serialize, touch
from errors import err
from middleware import (body, parse_pagination, req_dt, req_enum, req_int,
                        req_str, require_roles)
from response import list_response, success
from services import (FIELDS, build_report_payload, get_or_404, sorted_all)
from . import bp

REGULATORS = ["PHMSA", "STATE_PUC", "LOCAL_FIRE_MARSHAL"]
REPORT_ROLES = ("ComplianceOfficer", "IntegrityAnalyst")


def ser(report):
    return serialize(report, FIELDS["compliance_reports"])


@bp.post("/compliance-reports")
@require_roles("ComplianceOfficer")
def create_report():
    d = body()
    start = req_dt(d, "reporting_period_start")
    end = req_dt(d, "reporting_period_end")
    regulator = req_enum(d, "regulator", REGULATORS)
    report = make_entity()
    report.update({
        "reporting_period_start": start, "reporting_period_end": end,
        "regulator": regulator,
        "report_payload_uri": f"/integrity-program/compliance-reports/"
                              f"{report['id']}/payload",
        "leak_section_snapshot_id": None, "cp_section_snapshot_id": None,
        "submitted_at": None, "status": "DRAFT",
    })
    report["_payload"] = build_report_payload(report)
    STORE["compliance_reports"][report["id"]] = report
    return success(ser(report), code=201)


@bp.get("/compliance-reports")
@require_roles(*REPORT_ROLES)
def list_reports():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    regulator = request.args.get("regulator")
    items = sorted_all("compliance_reports")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if regulator is not None:
        items = [r for r in items if r["regulator"] == regulator]
    return list_response(items, ser, limit, offset)


@bp.get("/compliance-reports/<rid>")
@require_roles(*REPORT_ROLES)
def get_report(rid):
    return success(ser(get_or_404("compliance_reports", rid)))


def _check_report_version(report, expected):
    if expected != report["version"]:
        raise err("ERR_STALE_REPORT_VERSION",
                  "expected_report_version mismatches ComplianceReport.version",
                  412)


@bp.post("/compliance-reports/<rid>/bind-snapshots")
@require_roles("ComplianceOfficer")
def bind_snapshots(rid):
    report = get_or_404("compliance_reports", rid)
    d = body()
    leak_snap_id = req_str(d, "leak_section_snapshot_id")
    cp_snap_id = req_str(d, "cp_section_snapshot_id")
    expected = req_int(d, "expected_report_version")
    leak_snap = get_or_404("risk_model_snapshots", leak_snap_id)
    cp_snap = get_or_404("risk_model_snapshots", cp_snap_id)
    if report["status"] != "DRAFT":
        raise err("ERR_REPORT_NOT_DRAFT", "ComplianceReport.status != DRAFT",
                  409)
    if leak_snap["status"] != "CURRENT" or cp_snap["status"] != "CURRENT":
        raise err("ERR_SNAPSHOT_STALE",
                  "RiskModelSnapshot.status != CURRENT when bound", 422)
    _check_report_version(report, expected)
    report["leak_section_snapshot_id"] = leak_snap_id
    report["cp_section_snapshot_id"] = cp_snap_id
    touch(report)
    return success(ser(report))


@bp.post("/compliance-reports/<rid>/submit-for-review")
@require_roles("ComplianceOfficer")
def submit_for_review(rid):
    report = get_or_404("compliance_reports", rid)
    d = body()
    expected = req_int(d, "expected_report_version")
    if report["status"] != "DRAFT":
        raise err("ERR_REPORT_NOT_DRAFT", "ComplianceReport.status != DRAFT",
                  409)
    leak_snap = (STORE["risk_model_snapshots"]
                 .get(report["leak_section_snapshot_id"])
                 if report["leak_section_snapshot_id"] else None)
    cp_snap = (STORE["risk_model_snapshots"]
               .get(report["cp_section_snapshot_id"])
               if report["cp_section_snapshot_id"] else None)
    if (leak_snap is None or leak_snap["status"] != "CURRENT"
            or cp_snap is None or cp_snap["status"] != "CURRENT"):
        raise err("ERR_SNAPSHOT_STALE",
                  "Both bound RiskModelSnapshots must be CURRENT", 422)
    _check_report_version(report, expected)
    for snap in (leak_snap, cp_snap):
        snap["status"] = "PINNED"
        touch(snap)
    report["status"] = "PENDING_REVIEW"
    touch(report)
    return success(ser(report))


@bp.post("/compliance-reports/<rid>/submit-to-regulator")
@require_roles("ComplianceOfficer")
def submit_to_regulator(rid):
    report = get_or_404("compliance_reports", rid)
    if report["status"] != "PENDING_REVIEW":
        raise err("ERR_REPORT_NOT_PENDING_REVIEW",
                  "ComplianceReport.status != PENDING_REVIEW", 409)
    officer = STORE["compliance_officers"].get(g.user_id)
    if officer is None or report["regulator"] not in officer["jurisdiction_scope"]:
        raise err("ERR_OFFICER_OUT_OF_JURISDICTION",
                  "ComplianceOfficer.jurisdiction_scope missing regulator", 422)
    if now() > report["reporting_period_end"] + timedelta(days=60):
        raise err("ERR_REPORT_PAST_DUE",
                  "Submitting after reporting_period_end + 60 days", 422)
    report["submitted_at"] = now()
    report["status"] = "SUBMITTED"
    report["_payload"] = build_report_payload(report)
    touch(report)
    return success(ser(report))


@bp.post("/compliance-reports/<rid>/record-acceptance")
@require_roles("ComplianceOfficer")
def record_acceptance(rid):
    report = get_or_404("compliance_reports", rid)
    if report["status"] != "SUBMITTED":
        raise err("ERR_REPORT_NOT_SUBMITTED",
                  "ComplianceReport.status != SUBMITTED", 409)
    report["status"] = "ACCEPTED"
    touch(report)
    return success(ser(report))


@bp.post("/compliance-reports/<rid>/record-rejection")
@require_roles("ComplianceOfficer")
def record_rejection(rid):
    report = get_or_404("compliance_reports", rid)
    if report["status"] != "SUBMITTED":
        raise err("ERR_REPORT_NOT_SUBMITTED",
                  "ComplianceReport.status != SUBMITTED", 409)
    report["status"] = "REJECTED_BY_REGULATOR"
    touch(report)
    return success(ser(report))


@bp.post("/compliance-reports/<rid>/request-resubmission")
@require_roles("ComplianceOfficer")
def request_resubmission(rid):
    report = get_or_404("compliance_reports", rid)
    if report["status"] != "REJECTED_BY_REGULATOR":
        raise err("ERR_REPORT_NOT_REJECTED",
                  "ComplianceReport.status != REJECTED_BY_REGULATOR", 409)
    report["status"] = "RESUBMISSION_REQUIRED"
    touch(report)
    return success(ser(report))


@bp.post("/compliance-reports/<rid>/reopen-draft")
@require_roles("ComplianceOfficer")
def reopen_draft(rid):
    report = get_or_404("compliance_reports", rid)
    if report["status"] != "RESUBMISSION_REQUIRED":
        raise err("ERR_REPORT_NOT_RESUBMISSION_REQUIRED",
                  "ComplianceReport.status != RESUBMISSION_REQUIRED", 409)
    for key in ("leak_section_snapshot_id", "cp_section_snapshot_id"):
        snap = (STORE["risk_model_snapshots"].get(report[key])
                if report[key] else None)
        if snap is not None and snap["status"] == "PINNED":
            snap["status"] = "STALE"
            touch(snap)
        report[key] = None
    report["status"] = "DRAFT"
    touch(report)
    return success(ser(report))
