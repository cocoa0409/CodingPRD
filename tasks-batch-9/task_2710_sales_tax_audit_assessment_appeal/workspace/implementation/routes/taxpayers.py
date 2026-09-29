"""Taxpayer and InformationReturn endpoints (PRD 3.1)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import (
    body,
    guard,
    opt_enum,
    opt_int,
    req_date,
    req_enum,
    req_id,
    req_int,
    req_str,
    bad,
)
from routes.common import (
    COMPLIANCE_STATUSES,
    FILING_FREQUENCIES,
    MATCH_STATUSES,
    SOURCE_TYPES,
    apply_filter,
    body_fk,
    by_created,
    listing,
    naics,
    one,
    path_get,
    require_owner,
)
from services import derive

bp = Blueprint("taxpayers", __name__)


@bp.post("/taxpayers")
@guard("SelectionAnalyst", "AuditSupervisor")
def create_taxpayer():
    data = body()
    legal_name = req_str(data, "legal_name", 1, 160)
    permit_number = req_str(data, "permit_number", 1, None)
    industry_naics_code = naics(data, "industry_naics_code")
    filing_frequency = req_enum(data, "filing_frequency", FILING_FREQUENCIES)
    gross = req_int(data, "gross_receipts_annual_cents", 0)
    delinquent = opt_int(data, "delinquent_period_count", 0, 40, 0)
    prior_rate = opt_int(data, "prior_audit_error_rate_bp", 0, 10000, None)
    compliance = opt_enum(data, "compliance_status", COMPLIANCE_STATUSES, "COMPLIANT")

    # tier 14 — uniqueness
    for existing in db.all_of("taxpayers"):
        if existing["permit_number"] == permit_number:
            raise ApiError("ERR_DUPLICATE_PERMIT_NUMBER")

    rec = db.new_record(
        {
            "legal_name": legal_name,
            "permit_number": permit_number,
            "industry_naics_code": industry_naics_code,
            "filing_frequency": filing_frequency,
            "gross_receipts_annual_cents": gross,
            "delinquent_period_count": delinquent,
            "prior_audit_error_rate_bp": prior_rate,
            "compliance_status": compliance,
            "reported_total_cents": 0,
            "matched_total_cents": 0,
            "info_variance_bp": 0,
            "delinquency_bp": 0,
            "magnitude_bp": 0,
            "prior_audit_bp": 3500,
            "screening_score": 0,
            "open_audit_count": 0,
        }
    )
    db.insert("taxpayers", rec)
    derive.refresh_taxpayer(rec)
    return one("taxpayers", rec, 201)


@bp.get("/taxpayers")
@guard("SelectionAnalyst", "AuditSupervisor", "FieldAuditor", "CollectionsAgent")
def list_taxpayers():
    rows = by_created(db.all_of("taxpayers"))
    rows = apply_filter(rows, "compliance_status", COMPLIANCE_STATUSES)
    naics_filter = None
    from middleware import filter_arg

    naics_filter = filter_arg("industry_naics_code")
    if naics_filter is not None:
        rows = [r for r in rows if r["industry_naics_code"] == naics_filter]
    return listing("taxpayers", rows)


@bp.get("/taxpayers/<tid>")
@guard("SelectionAnalyst", "AuditSupervisor", "FieldAuditor", "CollectionsAgent", "Taxpayer")
def read_taxpayer(tid):
    rec = path_get("taxpayers", tid)
    require_owner(rec["id"])
    return one("taxpayers", rec)


@bp.post("/taxpayers/<tid>/rescore-screening")
@guard("SelectionAnalyst")
def rescore_screening(tid):
    rec = path_get("taxpayers", tid)
    derive.refresh_taxpayer(rec)
    db.touch(rec)
    return one("taxpayers", rec)


@bp.get("/taxpayers/<tid>/information-returns")
@guard("SelectionAnalyst", "AuditSupervisor", "FieldAuditor", "Taxpayer")
def list_information_returns(tid):
    holder = path_get("taxpayers", tid)
    rows = by_created(db.where("information_returns", taxpayer_id=holder["id"]))
    rows = apply_filter(rows, "source_type", SOURCE_TYPES)
    rows = apply_filter(rows, "match_status", MATCH_STATUSES)
    return listing("information_returns", rows)


@bp.post("/information-returns")
@guard("SelectionAnalyst")
def create_information_return():
    data = body()
    taxpayer_id = req_id(data, "taxpayer_id")
    source_type = req_enum(data, "source_type", SOURCE_TYPES)
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    reported = req_int(data, "reported_amount_cents", 0)
    matched = req_int(data, "matched_return_amount_cents", 0)
    if period_start > period_end:
        bad("period_start must not be after period_end.")

    holder = body_fk("taxpayers", taxpayer_id)

    variance = reported - matched
    if variance == 0:
        match_status = "MATCHED"
    elif variance > 0:
        match_status = "UNDER_REPORTED"
    else:
        match_status = "OVER_REPORTED"

    rec = db.new_record(
        {
            "taxpayer_id": holder["id"],
            "source_type": source_type,
            "period_start": db.format_date(period_start),
            "period_end": db.format_date(period_end),
            "reported_amount_cents": reported,
            "matched_return_amount_cents": matched,
            "variance_cents": variance,
            "match_status": match_status,
            "in_scoring_window": False,
        },
        common=False,
    )
    db.insert("information_returns", rec)
    derive.refresh_info_return(rec)
    derive.refresh_taxpayer(holder)
    db.touch(holder)
    return one("information_returns", rec, 201)


@bp.get("/information-returns/<rid>")
@guard("SelectionAnalyst", "AuditSupervisor", "FieldAuditor")
def read_information_return(rid):
    rec = path_get("information_returns", rid)
    return one("information_returns", rec)
