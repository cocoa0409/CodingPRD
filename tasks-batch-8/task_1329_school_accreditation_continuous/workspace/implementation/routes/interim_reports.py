"""InterimReport endpoints."""
from flask import Blueprint, request

from db import DB, clock_now, fmt_iso, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    LATE_REPORT_PENALTY_CENTS,
    get_or_404,
    interim_due_date,
)
from util import (
    as_int,
    as_str,
    body,
    paginate,
    pagination,
    required,
    stamp_new,
    touch,
)

bp = Blueprint("interim_reports", __name__)


def report_view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@bp.post("/accreditation/terms/<id>/interim-reports")
def create_interim_report(id):
    auth(["SchoolLeader"])
    term = get_or_404("terms", id, "AccreditationTerm")
    data = body()
    report_year = as_int(required(data, "report_year"), "report_year")
    narrative = as_str(required(data, "narrative"), "narrative")
    if report_year < 1 or report_year > term["term_length_years"] - 1:
        raise ApiError(
            "ERR_VALIDATION",
            400,
            f"report_year must be in 1..{term['term_length_years'] - 1}",
        )
    # Uniqueness: one report per (term, report_year).
    for r in DB["interim_reports"].values():
        if r["term_id"] == id and r["report_year"] == report_year:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                409,
                "An interim report already exists for this (term, report_year)",
            )
    due_dt = interim_due_date(term, report_year)
    record = {
        "id": new_id(),
        "term_id": id,
        "report_year": report_year,
        "due_date": fmt_iso(due_dt),
        "narrative": narrative,
        "submitted_at": None,
        "status": "DRAFT",
        "_due_date_dt": due_dt,
    }
    stamp_new(record, with_version=True)
    DB["interim_reports"][record["id"]] = record
    return ok(report_view(record), status=201)


@bp.get("/accreditation/terms/<id>/interim-reports")
def list_interim_reports(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("terms", id, "AccreditationTerm")
    limit, offset = pagination()
    rows = [r for r in DB["interim_reports"].values() if r["term_id"] == id]
    rows.sort(key=lambda r: r["created_at"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([report_view(r) for r in page], total, limit, offset)


def _submit_report(report):
    term = DB["terms"].get(report["term_id"])
    if term is None or term["status"] not in ("TERM_ACTIVE", "INTERIM_MONITORING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Owning term must be TERM_ACTIVE or INTERIM_MONITORING",
        )
    now = clock_now()
    report["submitted_at"] = fmt_iso(now)
    report["status"] = "LATE" if now > report["_due_date_dt"] else "SUBMITTED"
    touch(report)


@bp.post("/accreditation/interim-reports/<id>/submit")
def submit_interim_report(id):
    auth(["SchoolLeader"])
    report = get_or_404("interim_reports", id, "InterimReport")
    if report["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Report must be DRAFT or RETURNED to submit",
        )
    _submit_report(report)
    return ok(report_view(report))


@bp.post("/accreditation/interim-reports/<id>/accept")
def accept_interim_report(id):
    auth(["AccreditationOfficer"])
    report = get_or_404("interim_reports", id, "InterimReport")
    if report["status"] not in ("SUBMITTED", "LATE"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Report must be SUBMITTED or LATE to accept"
        )
    was_late = report["status"] == "LATE"
    report["status"] = "ACCEPTED"
    touch(report)
    if was_late:
        term = DB["terms"].get(report["term_id"])
        if term is not None:
            system = DB["systems"].get(term["system_id"])
            if system is not None:
                system["fee_credit_cents"] -= LATE_REPORT_PENALTY_CENTS
                touch(system)
    return ok(report_view(report))


@bp.post("/accreditation/interim-reports/<id>/return")
def return_interim_report(id):
    auth(["AccreditationOfficer"])
    report = get_or_404("interim_reports", id, "InterimReport")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report must be SUBMITTED to return")
    report["status"] = "RETURNED"
    touch(report)
    return ok(report_view(report))
