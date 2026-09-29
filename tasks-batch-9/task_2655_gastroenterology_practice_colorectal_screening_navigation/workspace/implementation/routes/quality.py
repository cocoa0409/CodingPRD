"""Adenoma detection rate measurement windows."""
from flask import Blueprint

from core import by_seq, db, dec, fail, new_record, today_str, touch
from core import respond_list, respond_object
from calcs import MIN_SCREENING_VOLUME, adenoma_detection_rate
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    opt_enum,
    pagination,
    req_date,
    req_id,
    req_string,
)
from services import get_clinician, get_period

bp = Blueprint("quality", __name__)

PERIOD_STATUSES = ("OPEN", "LOCKED", "ATTESTED")
BENCHMARK_RESULTS = ("MET", "MISSED", "INSUFFICIENT_VOLUME")
ATTRIBUTION_BASES = ("PROCEDURE_DATE", "PATHOLOGY_FINALIZATION_DATE")


@bp.post("/quality-periods")
def create_period():
    auth("QualityOfficer")
    data = body()
    endoscopist_id = req_id(data, "endoscopist_id")
    period_start_date = req_date(data, "period_start_date")
    period_end_date = req_date(data, "period_end_date")
    attribution_basis = opt_enum(data, "attribution_basis", ATTRIBUTION_BASES, "PROCEDURE_DATE")

    clinician = get_clinician(endoscopist_id)
    if clinician["clinician_type"] != "ENDOSCOPIST":
        fail("ERR_CLINICIAN_TYPE_MISMATCH",
             "A measurement window may only measure an ENDOSCOPIST.")

    for row in db.periods.values():
        if row["endoscopist_id"] != endoscopist_id:
            continue
        if row["attribution_basis"] != attribution_basis:
            continue
        if period_start_date <= row["period_end_date"] and \
                row["period_start_date"] <= period_end_date:
            fail("ERR_QUALITY_PERIOD_OVERLAP",
                 "The window intersects an existing window for this endoscopist and basis.")

    period = new_record({
        "endoscopist_id": endoscopist_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "attribution_basis": attribution_basis,
        "screening_colonoscopy_count": 0,
        "adenoma_positive_count": 0,
        "adr_pct": None,
        "benchmark_pct": None,
        "benchmark_result": None,
        "remediation_required": False,
        "remediation_plan": None,
        "attesting_user_id": None,
        "status": "OPEN",
    })
    db.periods[period["id"]] = period
    return respond_object(period, 201)


@bp.get("/quality-periods/<period_id>")
def read_period(period_id):
    auth("QualityOfficer", "PracticeAdmin")
    return respond_object(get_period(period_id))


@bp.get("/quality-periods")
def list_periods():
    auth("QualityOfficer", "PracticeAdmin")
    limit, offset = pagination()
    endoscopist_id = filter_value("endoscopist_id")
    status = filter_enum("status", PERIOD_STATUSES)
    benchmark_result = filter_enum("benchmark_result", BENCHMARK_RESULTS)
    rows = by_seq(list(db.periods.values()))
    if endoscopist_id is not None:
        rows = [r for r in rows if r["endoscopist_id"] == endoscopist_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if benchmark_result is not None:
        rows = [r for r in rows if r["benchmark_result"] == benchmark_result]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


@bp.post("/quality-periods/<period_id>/lock")
def lock_period(period_id):
    auth("QualityOfficer")
    period = get_period(period_id)
    if period["status"] != "OPEN":
        fail("ERR_INVALID_QUALITY_PERIOD_STATE",
             "Locking is not admitted from %s." % period["status"])
    if today_str() < period["period_end_date"]:
        fail("ERR_QUALITY_PERIOD_NOT_ENDED",
             "The window ends on %s and cannot be measured yet." % period["period_end_date"])

    denominator, numerator, adr_pct = adenoma_detection_rate(period)
    clinician = db.clinicians[period["endoscopist_id"]]
    benchmark_pct = clinician["adr_benchmark_pct"]

    if denominator < MIN_SCREENING_VOLUME:
        benchmark_result = "INSUFFICIENT_VOLUME"
    elif dec(adr_pct) >= dec(benchmark_pct):
        benchmark_result = "MET"
    else:
        benchmark_result = "MISSED"

    period["screening_colonoscopy_count"] = denominator
    period["adenoma_positive_count"] = numerator
    period["adr_pct"] = adr_pct
    period["benchmark_pct"] = benchmark_pct
    period["benchmark_result"] = benchmark_result
    period["remediation_required"] = benchmark_result == "MISSED"
    period["status"] = "LOCKED"
    touch(period)
    return respond_object(period)


@bp.post("/quality-periods/<period_id>/attest")
def attest_period(period_id):
    user_id, _role = auth("QualityOfficer")
    data = body()
    remediation_plan = req_string(data, "remediation_plan")
    period = get_period(period_id)
    if period["status"] != "LOCKED":
        fail("ERR_INVALID_QUALITY_PERIOD_STATE",
             "Attestation is not admitted from %s." % period["status"])
    period["remediation_plan"] = remediation_plan
    period["attesting_user_id"] = user_id
    period["status"] = "ATTESTED"
    touch(period)
    return respond_object(period)
