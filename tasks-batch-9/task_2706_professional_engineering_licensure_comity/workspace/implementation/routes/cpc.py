"""Continuing professional competency: reports, hours and audit draws (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint

import calc
import db
import guards
import schemas
from errors import ApiError
from middleware import actor, endpoint
from response import created, ok
from validate import (body, opt_bool, opt_num, q_enum, q_str, req_dt, req_enum,
                      req_id, req_int, req_num, req_str)

bp = Blueprint("cpc", __name__)

REPORT_STATUSES = ("SUBMITTED", "SUPERSEDED", "ACCEPTED", "UNDER_AUDIT",
                   "AUDIT_CLEARED", "AUDIT_DEFICIENT")
ACTIVITY_TYPES = ("COURSE", "SEMINAR", "TEACHING", "PUBLICATION", "PATENT",
                  "SELF_STUDY")
DOCUMENTATION_STATUSES = ("NONE", "ACCEPTED", "REJECTED")
AUDIT_STATUSES = ("SAMPLED", "CLOSED")
REPORT_READ_ROLES = ("Licensee", "BoardReviewer", "BoardSecretary",
                     "BoardLicensingOfficer")
PDH_READ_ROLES = ("Licensee", "BoardReviewer", "BoardSecretary")
AUDIT_READ_ROLES = ("BoardReviewer", "BoardSecretary", "BoardLicensingOfficer")


def _fetch_report(cpc_report_id):
    return schemas.fetch("cpc_reports", cpc_report_id, "ERR_CPC_REPORT_NOT_FOUND")


def _fetch_pdh(pdh_record_id):
    return schemas.fetch("pdh_records", pdh_record_id, "ERR_PDH_RECORD_NOT_FOUND")


def _requirement(report):
    license_row = db.get("licenses", report["license_id"])
    return license_row["pdh_requirement"] if license_row else Decimal("0")


def _own_report(report):
    license_row = db.get("licenses", report["license_id"])
    guards.owned_by_caller(license_row["engineer_id"] if license_row else None)


# --------------------------------------------------------------- cpc reports
@bp.post("/cpc-reports")
@endpoint("Licensee")
def create_report():
    data = body()
    license_id = req_id(data, "license_id")
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    self_certified_pdh = req_num(data, "self_certified_pdh", minimum=0, places=1)
    carryover = opt_num(data, "carryover_pdh_claimed", default=Decimal("0"),
                        minimum=0, places=1)
    expected_version = req_int(data, "expected_license_version")
    license_row = schemas.fetch("licenses", license_id, "ERR_LICENSE_NOT_FOUND")
    guards.owned_by_caller(license_row["engineer_id"])
    if expected_version != license_row["version"]:
        raise ApiError("ERR_STALE_LICENSE_VERSION",
                       "the licence has moved on since it was read")
    if license_row["current_period_end"] != period_end:
        raise ApiError("ERR_INVALID_REQUEST",
                       "period_end must equal the licence's current_period_end")
    superseded = None
    for row in db.all_rows("cpc_reports"):
        if row["license_id"] != license_row["id"]:
            continue
        if row["period_end"] != period_end:
            continue
        if row["status"] != "SUBMITTED":
            continue
        superseded = row
    if superseded is not None:
        db.write(superseded, status="SUPERSEDED")
    report = db.insert("cpc_reports", {
        "license_id": license_row["id"],
        "period_start": period_start,
        "period_end": period_end,
        "self_certified_pdh": self_certified_pdh,
        "carryover_pdh_claimed": carryover,
        "self_certified_total_pdh": Decimal("0"),
        "audit_verified_total_pdh": Decimal("0"),
        "shortfall_pdh": Decimal("0"),
        "audit_id": None,
        "supersedes_report_id": superseded["id"] if superseded else None,
        "audit_decided_by_user_id": None,
        "status": "SUBMITTED",
    })
    report["self_certified_total_pdh"] = calc.pdh_total(report, "self_certified")
    report["shortfall_pdh"] = calc.pdh_shortfall(report, "self_certified",
                                                 _requirement(report))
    db.touch(license_row)
    return created(schemas.view(report, schemas.CPC_REPORT))


@bp.get("/cpc-reports/<cpc_report_id>")
@endpoint(*REPORT_READ_ROLES)
def read_report(cpc_report_id):
    report = _fetch_report(cpc_report_id)
    return ok(schemas.view(report, schemas.CPC_REPORT))


@bp.get("/cpc-reports")
@endpoint(*REPORT_READ_ROLES)
def list_reports():
    license_id = q_str("license_id")
    audit_id = q_str("audit_id")
    supersedes_report_id = q_str("supersedes_report_id")
    status = q_enum("status", REPORT_STATUSES)

    def keep(row):
        if license_id is not None and row["license_id"] != license_id:
            return False
        if audit_id is not None and row["audit_id"] != audit_id:
            return False
        if supersedes_report_id is not None and row["supersedes_report_id"] != supersedes_report_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return schemas.listing("cpc_reports", schemas.CPC_REPORT, keep)


@bp.post("/cpc-reports/<cpc_report_id>/accept")
@endpoint("BoardReviewer")
def accept_report(cpc_report_id):
    report = _fetch_report(cpc_report_id)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_CPC_REPORT_STATE_INVALID",
                       "only a SUBMITTED report may be accepted")
    total = calc.pdh_total(report, "self_certified")
    if calc.dec(report["self_certified_pdh"]) != total:
        raise ApiError("ERR_PDH_SELF_CERT_MISMATCH",
                       "the declared total does not reconcile with the line items")
    shortfall = calc.pdh_shortfall(report, "self_certified", _requirement(report))
    db.write(report, status="ACCEPTED", self_certified_total_pdh=total,
             shortfall_pdh=shortfall)
    return ok(schemas.view(report, schemas.CPC_REPORT))


# ----------------------------------------------------------------- pdh records
@bp.post("/cpc-reports/<cpc_report_id>/pdh-records")
@endpoint("Licensee")
def create_pdh_record(cpc_report_id):
    data = body()
    activity_type = req_enum(data, "activity_type", ACTIVITY_TYPES)
    pdh_hours = req_num(data, "pdh_hours", exclusive_min=0, maximum=40, places=1)
    completed_on = req_dt(data, "completed_on")
    ethics_flag = opt_bool(data, "ethics_flag", default=False)
    report = _fetch_report(cpc_report_id)
    if completed_on < report["period_start"] or completed_on > report["period_end"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "completed_on must fall inside the report period")
    _own_report(report)
    record = db.insert("pdh_records", {
        "cpc_report_id": report["id"],
        "activity_type": activity_type,
        "pdh_hours": pdh_hours,
        "completed_on": completed_on,
        "ethics_flag": ethics_flag,
        "documentation_status": "NONE",
    }, versioned=False)
    calc.refresh_report(report)
    return created(schemas.view(record, schemas.PDH_RECORD))


@bp.get("/pdh-records/<pdh_record_id>")
@endpoint(*PDH_READ_ROLES)
def read_pdh_record(pdh_record_id):
    record = _fetch_pdh(pdh_record_id)
    return ok(schemas.view(record, schemas.PDH_RECORD))


@bp.get("/pdh-records")
@endpoint(*PDH_READ_ROLES)
def list_pdh_records():
    cpc_report_id = q_str("cpc_report_id")
    activity_type = q_enum("activity_type", ACTIVITY_TYPES)
    documentation_status = q_enum("documentation_status", DOCUMENTATION_STATUSES)

    def keep(row):
        if cpc_report_id is not None and row["cpc_report_id"] != cpc_report_id:
            return False
        if activity_type is not None and row["activity_type"] != activity_type:
            return False
        if documentation_status is not None and row["documentation_status"] != documentation_status:
            return False
        return True

    return schemas.listing("pdh_records", schemas.PDH_RECORD, keep)


@bp.post("/pdh-records/<pdh_record_id>/documentation-review")
@endpoint("BoardReviewer")
def documentation_review(pdh_record_id):
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "REJECT"))
    record = _fetch_pdh(pdh_record_id)
    db.write(record, documentation_status=("ACCEPTED" if decision == "ACCEPT"
                                           else "REJECTED"))
    report = db.get("cpc_reports", record["cpc_report_id"])
    if report is not None:
        calc.refresh_report(report, force_audit=True)
    return ok(schemas.view(record, schemas.PDH_RECORD))


# ---------------------------------------------------------------- audit draws
def _eligible_pool(as_of_period_end):
    pool = []
    for report in db.all_rows("cpc_reports"):
        if report["status"] != "ACCEPTED":
            continue
        if report["period_end"] != as_of_period_end:
            continue
        if report["audit_id"] is not None:
            continue
        license_row = db.get("licenses", report["license_id"])
        if license_row is None or license_row["status"] not in ("ACTIVE", "EXPIRED"):
            continue
        pool.append((report, license_row))
    return pool


def _ranked(pool):
    """Margin ascending, then created_at ascending, then license_number ascending."""
    def key(pair):
        report, license_row = pair
        margin = (calc.dec(report["self_certified_total_pdh"])
                  - calc.dec(license_row["pdh_requirement"]))
        return (margin, report["created_at"], license_row["license_number"])

    return sorted(pool, key=key)


@bp.post("/cpc-audits")
@endpoint("BoardSecretary", "BoardReviewer")
def create_audit():
    data = body()
    label = req_str(data, "audit_cycle_label", max_len=40)
    sample_pct = req_num(data, "sample_pct", exclusive_min=0, maximum=1)
    as_of_period_end = req_dt(data, "as_of_period_end")
    for row in db.store["cpc_audits"].values():
        if row["audit_cycle_label"] == label:
            raise ApiError("ERR_DUPLICATE_AUDIT_CYCLE",
                           "that audit cycle label has already been drawn")
    for row in db.all_rows("cpc_audits"):
        if row["as_of_period_end"] == as_of_period_end and row["status"] == "CLOSED":
            raise ApiError("ERR_AUDIT_STATE_INVALID",
                           "the audit cycle for that period has already closed")
    pool = _eligible_pool(as_of_period_end)
    if not pool:
        raise ApiError("ERR_AUDIT_POOL_EMPTY",
                       "no report qualifies for the requested period")
    drawn = calc.sampled_count(len(pool), sample_pct)
    audit = db.insert("cpc_audits", {
        "audit_cycle_label": label,
        "sample_pct": sample_pct,
        "as_of_period_end": as_of_period_end,
        "pool_size": len(pool),
        "sampled_count": drawn,
        "created_by_user_id": actor(),
        "status": "SAMPLED",
    })
    for report, _license in _ranked(pool)[:drawn]:
        audit_total = calc.pdh_total(report, "audit_verified")
        shortfall = calc.pdh_shortfall(report, "audit_verified", _requirement(report))
        db.write(report, status="UNDER_AUDIT", audit_id=audit["id"],
                 audit_verified_total_pdh=audit_total, shortfall_pdh=shortfall)
    return created(schemas.view(audit, schemas.CPC_AUDIT))


@bp.get("/cpc-audits/<cpc_audit_id>")
@endpoint(*AUDIT_READ_ROLES)
def read_audit(cpc_audit_id):
    audit = schemas.fetch("cpc_audits", cpc_audit_id, "ERR_CPC_AUDIT_NOT_FOUND")
    return ok(schemas.view(audit, schemas.CPC_AUDIT))


@bp.get("/cpc-audits")
@endpoint(*AUDIT_READ_ROLES)
def list_audits():
    status = q_enum("status", AUDIT_STATUSES)

    def keep(row):
        return status is None or row["status"] == status

    return schemas.listing("cpc_audits", schemas.CPC_AUDIT, keep)


@bp.post("/cpc-reports/<cpc_report_id>/audit-decision")
@endpoint("BoardReviewer")
def audit_decision(cpc_report_id):
    data = body()
    decision = req_enum(data, "decision", ("CLEAR", "DEFICIENT"))
    report = _fetch_report(cpc_report_id)
    audit = db.get("cpc_audits", report["audit_id"])
    guards.segregation(audit["created_by_user_id"] if audit else None)
    if report["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_REPORT_NOT_UNDER_AUDIT",
                       "the report does not stand under audit")
    audit_total = calc.pdh_total(report, "audit_verified")
    shortfall = calc.pdh_shortfall(report, "audit_verified", _requirement(report))
    if decision == "CLEAR" and shortfall != 0:
        raise ApiError("ERR_CPC_REPORT_STATE_INVALID",
                       "the audited shortfall does not support a clearance")
    if decision == "DEFICIENT" and shortfall == 0:
        raise ApiError("ERR_CPC_REPORT_STATE_INVALID",
                       "the audited shortfall does not support a deficiency")
    terminal = "AUDIT_CLEARED" if decision == "CLEAR" else "AUDIT_DEFICIENT"
    db.write(report, status=terminal, audit_verified_total_pdh=audit_total,
             shortfall_pdh=shortfall, audit_decided_by_user_id=actor())
    if terminal == "AUDIT_DEFICIENT":
        license_row = db.get("licenses", report["license_id"])
        if license_row is not None:
            db.write(license_row, discipline_flag=True)
    if audit is not None:
        remaining = any(r["audit_id"] == audit["id"] and r["status"] == "UNDER_AUDIT"
                        for r in db.all_rows("cpc_reports"))
        if not remaining and audit["status"] == "SAMPLED":
            db.write(audit, status="CLOSED")
    return ok(schemas.view(report, schemas.CPC_REPORT))
