"""AidYear endpoints (PRD 3.1, 3.9)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FIELD_CONSTRAINT
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.calc import validate_pell_schedule_shape
from services.core import new_record, public, touch
from validate import (
    get_body, req_str, req_int, req_datetime, req_number,
    require_path_resource,
)

bp = Blueprint("aid_years", __name__)

DIRECTOR = ["AidDirector"]
DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]


def _validate_pell_rows(rows):
    """Rung 9 shape of pell_schedule rows (contiguity is checked at OPEN)."""
    if not isinstance(rows, list):
        raise_error(ERR_INVALID_REQUEST, "pell_schedule must be an array")
    for row in rows:
        if not isinstance(row, dict):
            raise_error(ERR_INVALID_REQUEST, "pell_schedule rows must be objects")
        for field in ("efc_min", "efc_max", "award_cents"):
            v = row.get(field)
            if not isinstance(v, int) or isinstance(v, bool):
                raise_error(ERR_INVALID_REQUEST,
                            f"pell_schedule row field {field} must be an integer")


@bp.post("/aid-years")
def create_aid_year():
    authorized(DIRECTOR)
    body = get_body()
    year_code = req_str(body, "year_code")
    coa_in = req_int(body, "coa_in_state_cents")
    coa_out = req_int(body, "coa_out_of_state_cents")
    priority_deadline = req_datetime(body, "priority_deadline")
    if "pell_schedule" not in body:
        raise_error(ERR_INVALID_REQUEST, "missing field: pell_schedule")
    pell_schedule = body["pell_schedule"]
    _validate_pell_rows(pell_schedule)
    rate = req_number(body, "verification_tracking_flag_rate")
    if not (rate > 0 and rate <= 1):
        raise_error(ERR_INVALID_REQUEST,
                    "verification_tracking_flag_rate must be greater than 0 and at most 1")
    # Rung 10: field-level domain constraints.
    if coa_in <= 0:
        raise_error(ERR_FIELD_CONSTRAINT, "coa_in_state_cents must be strictly positive")
    if coa_out <= coa_in:
        raise_error(ERR_FIELD_CONSTRAINT,
                    "coa_out_of_state_cents must be strictly greater than coa_in_state_cents")
    rec = new_record("aid_years", {
        "year_code": year_code,
        "coa_in_state_cents": coa_in,
        "coa_out_of_state_cents": coa_out,
        "priority_deadline": priority_deadline,
        "pell_schedule": [dict(r) for r in pell_schedule],
        "verification_tracking_flag_rate": rate,
        "status": "DRAFT",
        "total_packaged_cents": 0,
        "total_disbursed_cents": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/aid-years")
def list_aid_years():
    authorized(["AidDirector", "AidOfficer", "Student"])
    return list_response("aid_years", {"status": request.args.get("status")})


@bp.get("/aid-years/<rid>")
def get_aid_year(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("aid_years", rid)
    return success_object(public(rec))


@bp.post("/aid-years/<rid>/open")
def open_aid_year(rid):
    authorized(DIRECTOR)
    ay = require_path_resource("aid_years", rid)
    if ay["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"aid year is {ay['status']}, expected DRAFT")
    if not validate_pell_schedule_shape(ay["pell_schedule"]):
        raise_error(ERR_INVALID_STATE,
                    "pell_schedule must be non-empty, contiguous, and cover [0, 999999]")
    has_active = any(f["aid_year_id"] == ay["id"] and f["status"] == "ACTIVE"
                     for f in db.fund_types.values())
    if not has_active:
        raise_error(ERR_INVALID_STATE,
                    "at least one ACTIVE fund is required to open the aid year")
    ay["status"] = "OPEN"
    touch(ay)
    return success_object(public(ay))


@bp.post("/aid-years/<rid>/lock-packaging")
def lock_packaging(rid):
    authorized(DIRECTOR)
    ay = require_path_resource("aid_years", rid)
    if ay["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    f"aid year is {ay['status']}, expected OPEN")
    for pkg in db.award_packages.values():
        if pkg["aid_year_id"] == ay["id"] and pkg["status"] in (
                "DRAFT", "PACKAGED", "REVISION_REQUESTED"):
            raise_error(ERR_INVALID_STATE,
                        "in-flight award packages remain under this aid year")
    ay["status"] = "PACKAGING_LOCKED"
    touch(ay)
    return success_object(public(ay))


@bp.post("/aid-years/<rid>/begin-reconciliation")
def begin_reconciliation(rid):
    authorized(DIRECTOR)
    ay = require_path_resource("aid_years", rid)
    if ay["status"] != "PACKAGING_LOCKED":
        raise_error(ERR_INVALID_STATE,
                    f"aid year is {ay['status']}, expected PACKAGING_LOCKED")
    max_seq = 0
    for run in db.reconciliation_runs.values():
        if run["aid_year_id"] == ay["id"]:
            max_seq = max(max_seq, run["run_seq"])
    new_record("reconciliation_runs", {
        "aid_year_id": ay["id"],
        "run_seq": max_seq + 1,
        "status": "DRAFT",
        "federal_reported_cents": None,
        "internal_posted_cents": 0,
        "variance_cents": None,
    })
    ay["status"] = "RECONCILING"
    touch(ay)
    return success_object(public(ay))


@bp.post("/aid-years/<rid>/close")
def close_aid_year(rid):
    authorized(DIRECTOR)
    ay = require_path_resource("aid_years", rid)
    if ay["status"] != "RECONCILING":
        raise_error(ERR_INVALID_STATE,
                    f"aid year is {ay['status']}, expected RECONCILING")
    runs = [r for r in db.reconciliation_runs.values() if r["aid_year_id"] == ay["id"]]
    latest = max(runs, key=lambda r: r["run_seq"], default=None)
    if latest is None or latest["status"] != "BALANCED":
        raise_error(ERR_INVALID_STATE,
                    "the latest reconciliation run is not BALANCED")
    # Cascade: every FundType under the aid year, whether ACTIVE or EXHAUSTED,
    # moves to CLOSED (PRD 3.9).
    for fund in db.fund_types.values():
        if fund["aid_year_id"] == ay["id"] and fund["status"] in ("ACTIVE", "EXHAUSTED"):
            fund["status"] = "CLOSED"
            touch(fund)
    ay["status"] = "CLOSED"
    touch(ay)
    return success_object(public(ay))


@bp.get("/aid-years/<rid>/fund-types")
def list_aid_year_fund_types(rid):
    authorized(DIRECTOR_OFFICER)
    require_path_resource("aid_years", rid)
    return list_response("fund_types", {"aid_year_id": rid})


@bp.get("/aid-years/<rid>/reconciliation-runs")
def list_aid_year_reconciliation_runs(rid):
    authorized(DIRECTOR)
    require_path_resource("aid_years", rid)
    return list_response("reconciliation_runs", {"aid_year_id": rid})
