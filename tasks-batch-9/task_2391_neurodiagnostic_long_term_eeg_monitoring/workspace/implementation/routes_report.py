"""Interpretation reports, turnaround governance and export packaging."""
from datetime import timedelta
from decimal import Decimal

import cascade
import clock
import config
import derive
import response
import validation
from db import base_record, db, insert
from errors import ApiError
from web import (ListResult, ObjectResult, bp, endpoint, get_export, get_report,
                 get_study)

REPORT_READ_ROLES = ("UnitCoordinator", "Technologist", "Epileptologist")
EXPORT_READ_ROLES = ("UnitCoordinator", "Epileptologist")


# --- review reports -------------------------------------------------------

@bp.route("/neurodiagnostics/studies/<study_id>/reports", methods=["GET"])
@endpoint(roles=REPORT_READ_ROLES)
def list_study_reports(user_id, role, study_id):
    from flask import request
    get_study(study_id)
    limit, offset = response.read_pagination(request.args)
    return ListResult(derive.ordered(derive.reports_of_study(study_id)), limit, offset)


@bp.route("/neurodiagnostics/reports/<report_id>", methods=["GET"])
@endpoint(roles=REPORT_READ_ROLES)
def read_report(user_id, role, report_id):
    return ObjectResult(get_report(report_id))


@bp.route("/neurodiagnostics/reports/<report_id>/issue-prelim", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def issue_prelim(user_id, role, report_id):
    data = validation.body()
    localization = validation.req_string(data, "localization")
    report = get_report(report_id)
    # rung 6 — the report's own dimension, then the study's acquisition
    if report["status"] not in ("PRELIM_DRAFT", "ADDENDUM_OPEN"):
        raise ApiError("ERR_INVALID_REPORT_STATE",
                       "Only a PRELIM_DRAFT or ADDENDUM_OPEN report may be issued as "
                       "preliminary.")
    study = db.studies.get(report["study_id"])
    if study is None or study["acquisition_state"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STUDY_STATE",
                       "The study's acquisition must be COMPLETED.")

    first_issue = report.get("prelim_issued_at") is None
    report["status"] = "PRELIM_ISSUED"
    report["localization"] = localization
    if first_issue:
        issued_at = clock.now()
        report["prelim_issued_at"] = issued_at
        report["prelim_author_user_id"] = user_id
        calendar, coverage, breached = derive.turnaround_figures(
            study["completed_at"], issued_at)
        report["turnaround_calendar_hours"] = calendar
        report["turnaround_coverage_hours"] = coverage
        report["sla_breached"] = breached
    return ObjectResult(report)


@bp.route("/neurodiagnostics/reports/<report_id>/open-addendum", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def open_addendum(user_id, role, report_id):
    data = validation.body()
    addendum_reason = validation.req_string(data, "addendum_reason")
    report = get_report(report_id)
    # rung 6
    if report["status"] != "PRELIM_ISSUED":
        raise ApiError("ERR_INVALID_REPORT_STATE",
                       "Only a PRELIM_ISSUED report may open an addendum.")
    # rung 23
    if report["addendum_count"] >= config.MAX_ADDENDA:
        raise ApiError("ERR_ADDENDUM_LIMIT", "The addendum limit for this report is reached.")
    report["status"] = "ADDENDUM_OPEN"
    report["addendum_count"] += 1
    report["addendum_reason"] = addendum_reason
    return ObjectResult(report)


@bp.route("/neurodiagnostics/reports/<report_id>/issue-final", methods=["POST"])
@endpoint(roles=("Epileptologist",), mutating=True)
def issue_final(user_id, role, report_id):
    data = validation.body()
    localization = validation.req_string(data, "localization")
    report = get_report(report_id)
    # rung 6
    if report["status"] != "PRELIM_ISSUED":
        raise ApiError("ERR_INVALID_REPORT_STATE",
                       "Only a PRELIM_ISSUED report may be issued as final.")
    # rung 8 — segregation of duties
    if user_id == report.get("prelim_author_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The final interpretation must come from a second epileptologist.")
    # rung 17 — every finding adjudicated
    for marking in derive.markings_of_study(report["study_id"]):
        if marking["status"] == "PROPOSED":
            raise ApiError("ERR_MARKING_NOT_ADJUDICATED",
                           "An event marking of this study is still PROPOSED.")
    report["status"] = "FINAL_ISSUED"
    report["localization"] = localization
    report["final_issued_at"] = clock.now()
    report["final_author_user_id"] = user_id
    return ObjectResult(report)


# --- export packages ------------------------------------------------------

@bp.route("/neurodiagnostics/exports", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def create_export(user_id, role):
    data = validation.body()
    study_id = validation.req_id(data, "study_id")
    include_video = validation.req_bool(data, "include_video")
    expected_version = validation.req_int(data, "expected_study_version")
    supersedes_export_id = validation.opt_id(data, "supersedes_export_id")
    # rung 5 — body foreign keys in declared field order
    study = get_study(study_id)
    if supersedes_export_id is not None:
        get_export(supersedes_export_id)
    # rung 7 — optimistic concurrency
    if expected_version != study["version"]:
        raise ApiError("ERR_STALE_STUDY_VERSION",
                       "expected_study_version does not match the study version.")
    # rung 16 — the interpretation must be final
    if not any(r["status"] == "FINAL_ISSUED" for r in derive.reports_of_study(study["id"])):
        raise ApiError("ERR_REPORT_NOT_FINAL",
                       "The study has no review report in FINAL_ISSUED.")

    package = base_record("export")
    package.update({
        "study_id": study["id"],
        "include_video": include_video,
        "supersedes_export_id": supersedes_export_id,
        "status": "QUEUED",
        "package_gb": Decimal("0"),
        "built_at": None,
        "delivered_at": None,
        "recipient_center": None,
        "retention_expires_at": None,
        "blocked_reason": None,
        "revocation_reason": None,
    })
    insert("exports", package)
    cascade.force_bump(study)
    return ObjectResult(package, 201)


@bp.route("/neurodiagnostics/exports", methods=["GET"])
@endpoint(roles=EXPORT_READ_ROLES)
def list_exports(user_id, role):
    from flask import request
    args = request.args
    limit, offset = response.read_pagination(args)
    study_id = validation.query_string(args, "study_id")
    supersedes_export_id = validation.query_string(args, "supersedes_export_id")
    status = validation.query_enum(args, "status", config.EXPORT_STATUSES)
    records = []
    for package in db.exports.values():
        if study_id and package["study_id"] != study_id:
            continue
        if supersedes_export_id and package.get("supersedes_export_id") != supersedes_export_id:
            continue
        if status and package["status"] != status:
            continue
        records.append(package)
    return ListResult(derive.ordered(records), limit, offset)


@bp.route("/neurodiagnostics/exports/<export_id>", methods=["GET"])
@endpoint(roles=EXPORT_READ_ROLES)
def read_export(user_id, role, export_id):
    return ObjectResult(get_export(export_id))


@bp.route("/neurodiagnostics/exports/<export_id>/build", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def build_export(user_id, role, export_id):
    package = get_export(export_id)
    # rung 6 — the package's own dimension, then the study's data residency
    if package["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_EXPORT_STATE", "Only a QUEUED package may be built.")
    study = db.studies.get(package["study_id"])
    if study is None or study["data_state"] != "ONLINE":
        raise ApiError("ERR_INVALID_DATA_STATE",
                       "The study's data must be ONLINE to build a package.")
    unit = derive.unit_of_study(study)
    # rung 21 — storage lock
    if unit is not None and derive.unit_posture(unit) == "STORAGE_LOCKED":
        raise ApiError("ERR_UNIT_STORAGE_LOCKED", "The unit is storage locked.")
    volume = derive.export_package_gb(package, study)
    # rung 22 — quota headroom
    if unit is not None:
        used = derive.unit_storage_used_gb(unit)
        if used + volume > derive.dec(unit["storage_quota_gb"]):
            raise ApiError("ERR_STORAGE_QUOTA_EXCEEDED",
                           "The package would exceed the unit's storage quota.")
    built_at = clock.now()
    package["status"] = "BUILT"
    package["package_gb"] = volume
    package["built_at"] = built_at
    package["retention_expires_at"] = built_at + timedelta(days=config.RETENTION_DAYS)
    return ObjectResult(package)


@bp.route("/neurodiagnostics/exports/<export_id>/deliver", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def deliver_export(user_id, role, export_id):
    data = validation.body()
    recipient_center = validation.req_string(data, "recipient_center")
    package = get_export(export_id)
    if package["status"] != "BUILT":
        raise ApiError("ERR_INVALID_EXPORT_STATE", "Only a BUILT package may be delivered.")
    package["status"] = "DELIVERED"
    package["delivered_at"] = clock.now()
    package["recipient_center"] = recipient_center
    return ObjectResult(package)


@bp.route("/neurodiagnostics/exports/<export_id>/revoke", methods=["POST"])
@endpoint(roles=("UnitCoordinator",), mutating=True)
def revoke_export(user_id, role, export_id):
    data = validation.body()
    revocation_reason = validation.req_string(data, "revocation_reason")
    package = get_export(export_id)
    # rung 6
    if package["status"] not in ("BUILT", "DELIVERED"):
        raise ApiError("ERR_INVALID_EXPORT_STATE",
                       "Only a BUILT or DELIVERED package may be revoked.")
    # rung 31 — a decided conference case protects its evidence
    for case in derive.cases_of_export(package["id"]):
        if case["status"] in ("CANDIDATE", "NON_CANDIDATE"):
            raise ApiError("ERR_EXPORT_IN_DECIDED_CASE",
                           "A decided conference case references this package.")
    package["status"] = "REVOKED"
    package["revocation_reason"] = revocation_reason
    return ObjectResult(package)
