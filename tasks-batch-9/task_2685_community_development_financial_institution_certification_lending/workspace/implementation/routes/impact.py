"""Borrower-supplied impact data and the institution impact ledger."""
import services as svc
import shape
from auth import authenticate, borrower_scope, scope
from envelope import created, ok, page, pagination, qs
from errors import fail
from flask import Blueprint
from store import base_row, db, fmt_dt, now, ordered, parse_dt, touch

bp = Blueprint("impact", __name__)

FILE_ROLES = ("Borrower", "InstitutionOfficer")
REPORT_READ_ROLES = ("Borrower", "InstitutionOfficer", "ComplianceAnalyst",
                     "AwardAdministrator")
REPORT_LIST_ROLES = ("InstitutionOfficer", "ComplianceAnalyst", "AwardAdministrator")
COUNT_FIELDS = ("jobs_created", "jobs_retained", "housing_units",
                "businesses_financed")
SUPERSEDABLE = ("SUBMITTED", "VERIFIED", "DISPUTED")


def _report_owner_institution(report_id):
    report = db.impact_reports.get(report_id)
    if report is None:
        return None
    loan = db.loans.get(report["loan_id"])
    return loan["institution_id"] if loan else None


@bp.post("/loans/<loan_id>/impact-reports")
def file_report(loan_id):
    caller = authenticate(FILE_ROLES)
    loan_row = db.loans.get(loan_id)
    scope(caller, loan_row["institution_id"] if loan_row else None)
    borrower_scope(caller, loan_row["borrower_id"] if loan_row else None)
    loan = svc.get_loan(loan_id)
    data = shape.body()
    expected = shape.req_int(data, "expected_loan_version")
    period_raw, period_end = shape.req_dt(data, "reporting_period_end")
    counts = {}
    for field in COUNT_FIELDS:
        counts[field] = shape.req_int(data, field, minimum=0)
    if expected != loan["version"]:
        fail("ERR_STALE_LOAN_VERSION")
    inst = svc.get_institution(loan["institution_id"])
    ledger_moved = False
    for prior in ordered([r for r in db.impact_reports.values()
                          if r["loan_id"] == loan["id"]
                          and r["state"] in SUPERSEDABLE]):
        if parse_dt(prior["reporting_period_end"]) != period_end:
            continue
        was_verified = prior["state"] == "VERIFIED"
        prior["state"] = "SUPERSEDED"
        touch(prior)
        if was_verified:
            # Only a VERIFIED row had ever entered the counters.
            svc.apply_impact_counts(inst, prior, -1)
            ledger_moved = True
    row = base_row()
    row.update({
        "loan_id": loan["id"],
        "borrower_id": loan["borrower_id"],
        "reporting_period_end": period_raw,
        "state": "SUBMITTED",
        "dispute_reason": None,
        "verified_at": None,
        "revision_count": 0,
    })
    row.update(counts)
    db.impact_reports[row["id"]] = row
    touch(loan)
    if ledger_moved:
        touch(inst)
    return created(row)


@bp.get("/impact-reports/<impact_report_id>")
def read_report(impact_report_id):
    caller = authenticate(REPORT_READ_ROLES)
    scope(caller, _report_owner_institution(impact_report_id))
    return ok(svc.get_report(impact_report_id))


@bp.get("/impact-reports")
def list_reports():
    authenticate(REPORT_LIST_ROLES)
    limit, offset = pagination()
    rows = ordered(db.impact_reports.values())
    for name in ("loan_id", "borrower_id", "state"):
        value = qs(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return page(rows, limit, offset)


@bp.post("/impact-reports/<impact_report_id>/verify")
def verify_report(impact_report_id):
    authenticate(("ComplianceAnalyst",))
    report = svc.get_report(impact_report_id)
    if report["state"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    report["state"] = "VERIFIED"
    report["verified_at"] = fmt_dt(now())
    touch(report)
    inst = svc.report_institution(report)
    if inst is not None:
        svc.apply_impact_counts(inst, report, 1)
        touch(inst)
    return ok(report)


@bp.post("/impact-reports/<impact_report_id>/dispute")
def dispute_report(impact_report_id):
    authenticate(("ComplianceAnalyst",))
    report = svc.get_report(impact_report_id)
    data = shape.body()
    reason = shape.req_str(data, "dispute_reason", 1)
    if report["state"] not in ("SUBMITTED", "VERIFIED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    was_verified = report["state"] == "VERIFIED"
    report["state"] = "DISPUTED"
    report["dispute_reason"] = reason
    report["verified_at"] = None
    touch(report)
    inst = svc.report_institution(report)
    if inst is not None:
        if was_verified:
            # A dispute from VERIFIED reverses the entry exactly.
            svc.apply_impact_counts(inst, report, -1)
        touch(inst)
    return ok(report)


@bp.post("/impact-reports/<impact_report_id>/resubmit")
def resubmit_report(impact_report_id):
    caller = authenticate(FILE_ROLES)
    scope(caller, _report_owner_institution(impact_report_id))
    existing = db.impact_reports.get(impact_report_id)
    borrower_scope(caller, existing["borrower_id"] if existing else None)
    report = svc.get_report(impact_report_id)
    data = shape.body()
    counts = {}
    for field in COUNT_FIELDS:
        counts[field] = shape.req_int(data, field, minimum=0)
    if report["state"] != "DISPUTED":
        fail("ERR_REPORT_NOT_DISPUTED")
    report.update(counts)
    report["state"] = "SUBMITTED"
    report["revision_count"] = report["revision_count"] + 1
    report["dispute_reason"] = None
    touch(report)
    return ok(report)
