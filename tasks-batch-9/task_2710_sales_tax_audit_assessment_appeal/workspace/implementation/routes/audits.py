"""Audit endpoints (PRD 3.2 - 3.4)."""
from flask import Blueprint, g

import db
from errors import ApiError
from middleware import (
    body,
    filter_arg,
    guard,
    opt_bool,
    opt_str,
    req_date,
    req_enum,
    bad,
)
from response import object_response
from routes.common import (
    ASSET_CLASSES,
    AUDIT_STATUSES,
    AUDIT_TYPES,
    STATUTE_STATUSES,
    WAIVER_STATUSES,
    apply_filter,
    by_created,
    listing,
    one,
    path_get,
)
from services import calc, derive, rollup

bp = Blueprint("audits", __name__)


@bp.get("/audits")
@guard("AuditSupervisor", "FieldAuditor", "SelectionAnalyst", "AppealsOfficer")
def list_audits():
    rows = by_created(db.all_of("audits"))
    for field in ("taxpayer_id", "audit_lead_id", "agreed_agreement_id"):
        value = filter_arg(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows = apply_filter(rows, "status", AUDIT_STATUSES)
    statute = filter_arg("statute_status", STATUTE_STATUSES)
    if statute is not None:
        rows = [r for r in rows if derive.audit_statute_status(r) == statute]
    return listing("audits", rows)


@bp.get("/audits/<aid>")
@guard("AuditSupervisor", "FieldAuditor", "AppealsOfficer", "TaxTribunalJudge", "Taxpayer")
def read_audit(aid):
    return one("audits", path_get("audits", aid))


@bp.post("/audits/<aid>/scope")
@guard("FieldAuditor", "AuditSupervisor")
def scope_audit(aid):
    audit = path_get("audits", aid)
    data = body()
    audit_type = req_enum(data, "audit_type", AUDIT_TYPES)
    start = req_date(data, "scope_period_start")
    end = req_date(data, "scope_period_end")
    if start > end:
        bad("scope_period_start must not be after scope_period_end.")

    if audit["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")

    # tier 11 — closed-interval overlap against every non-abandoned sibling audit
    for other in derive.audits_of_taxpayer(audit["taxpayer_id"]):
        if other["id"] == audit["id"] or other["status"] == "ABANDONED":
            continue
        o_start = db.parse_date(other.get("scope_period_start"))
        o_end = db.parse_date(other.get("scope_period_end"))
        if o_start is None or o_end is None:
            continue
        if start <= o_end and o_start <= end:
            raise ApiError("ERR_AUDIT_SCOPE_OVERLAP")

    audit["audit_type"] = audit_type
    audit["scope_period_start"] = db.format_date(start)
    audit["scope_period_end"] = db.format_date(end)
    audit["status"] = "SCOPED"
    derive.rewrite_statute(audit)
    db.touch(audit)
    return one("audits", audit)


@bp.post("/audits/<aid>/project-sample")
@guard("FieldAuditor")
def project_sample(aid):
    audit = path_get("audits", aid)
    body()
    if audit["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE")
    agreement_id = audit.get("agreed_agreement_id")
    agreement = db.get("sampling_agreements", agreement_id) if agreement_id else None
    if agreement is None or agreement["status"] != "AGREED":
        raise ApiError("ERR_AGREEMENT_NOT_AGREED")
    if derive.audit_statute_status(audit) == "EXPIRED":
        raise ApiError("ERR_STATUTE_EXPIRED")

    units = [u for u in derive.units_of_agreement(agreement["id"]) if u["error_class"] != "PENDING"]
    if not units:
        raise ApiError("ERR_SAMPLE_SET_EMPTY")
    if len(units) < int(agreement["minimum_sample_size"]):
        raise ApiError("ERR_SAMPLE_SIZE_NOT_MET")

    sum_err = sum(int(u["error_amount_cents"] or 0) for u in units)
    sum_base = sum(int(u["invoice_amount_cents"]) for u in units)
    derive.refresh_agreement(agreement)
    rate, projected = calc.project(
        agreement["methodology"],
        sum_err,
        sum_base,
        len(units),
        agreement["population_base_amount_cents"],
        agreement["population_unit_count"],
    )
    audit["sample_error_rate_bp"] = rate
    audit["projected_deficiency_cents"] = projected
    audit["examined_unit_count"] = len(units)
    audit["projection_method"] = agreement["methodology"]
    derive.recompute_certificate_deficiency(audit)
    derive.recompute_use_tax_deficiency(audit)
    audit["projection_status"] = "CURRENT"
    db.touch(audit)
    return one("audits", audit)


@bp.post("/audits/<aid>/close-fieldwork")
@guard("AuditSupervisor")
def close_fieldwork(aid):
    audit = path_get("audits", aid)
    data = body()
    fraud = opt_bool(data, "fraud_indicator", None)

    if audit["status"] != "FIELDWORK":
        raise ApiError("ERR_INVALID_STATE")
    # tier 8 — segregation of duties
    if g.user_id == audit["lead_auditor_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if derive.audit_statute_status(audit) == "EXPIRED":
        raise ApiError("ERR_STATUTE_EXPIRED")
    if audit["projection_status"] != "CURRENT":
        raise ApiError("ERR_PROJECTION_STALE")
    # tier 14 — the examined count must reach the agreed minimum
    agreement = db.get("sampling_agreements", audit.get("agreed_agreement_id"))
    if agreement is not None:
        if int(audit.get("examined_unit_count") or 0) < int(agreement["minimum_sample_size"]):
            raise ApiError("ERR_SAMPLE_SIZE_NOT_MET")

    if fraud is not None:
        audit["fraud_indicator"] = fraud
    audit["status"] = "REVIEW_COMPLETE"
    db.touch(audit)
    return one("audits", audit)


@bp.post("/audits/<aid>/reopen-fieldwork")
@guard("AuditSupervisor")
def reopen_fieldwork(aid):
    audit = path_get("audits", aid)
    data = body()
    opt_str(data, "reopen_reason", 1, None, None)
    if audit["status"] != "REVIEW_COMPLETE":
        raise ApiError("ERR_INVALID_STATE")
    for asmt in derive.assessments_of_audit(audit["id"]):
        if asmt["status"] in ("ISSUED", "FINAL"):
            raise ApiError("ERR_INVALID_STATE")
    if derive.audit_statute_status(audit) == "EXPIRED":
        raise ApiError("ERR_STATUTE_EXPIRED")
    audit["status"] = "FIELDWORK"
    audit["reopen_count"] = int(audit["reopen_count"]) + 1
    db.touch(audit)
    return one("audits", audit)


@bp.post("/audits/<aid>/abandon")
@guard("AuditSupervisor")
def abandon_audit(aid):
    audit = path_get("audits", aid)
    data = body()
    opt_str(data, "abandon_reason", 1, None, None)
    if audit["status"] in ("CLOSED", "ABANDONED"):
        raise ApiError("ERR_INVALID_STATE")
    if derive.audit_statute_status(audit) != "EXPIRED":
        raise ApiError("ERR_STATUTE_NOT_EXPIRED")

    audit["status"] = "ABANDONED"
    db.touch(audit)
    for agreement in db.where("sampling_agreements", audit_id=audit["id"]):
        if agreement["status"] in ("PROPOSED", "COUNTERED"):
            agreement["status"] = "SUPERSEDED"
            db.touch(agreement)
    holder = derive.taxpayer_of_audit(audit)
    if holder is not None:
        derive.refresh_taxpayer(holder)
        db.touch(holder)
    return one("audits", audit)


@bp.get("/audits/<aid>/liability-preview")
@guard("AuditSupervisor", "FieldAuditor")
def liability_preview(aid):
    audit = path_get("audits", aid)
    figures = rollup.compute(audit)
    figures["projection_status"] = audit["projection_status"]
    return object_response(figures)


@bp.get("/audits/<aid>/statute-waivers")
@guard("AuditSupervisor", "FieldAuditor", "Taxpayer")
def list_audit_waivers(aid):
    audit = path_get("audits", aid)
    rows = db.where("statute_waivers", audit_id=audit["id"])
    rows = sorted(rows, key=lambda w: (w.get("signed_date") or "", w["created_at"], w["_seq"]))
    rows = apply_filter(rows, "status", WAIVER_STATUSES)
    return listing("statute_waivers", rows)


@bp.get("/audits/<aid>/use-tax-purchases")
@guard("AuditSupervisor", "FieldAuditor", "Taxpayer")
def list_audit_purchases(aid):
    audit = path_get("audits", aid)
    rows = by_created(db.where("use_tax_purchases", audit_id=audit["id"]))
    rows = apply_filter(rows, "asset_class", ASSET_CLASSES)
    return listing("use_tax_purchases", rows)
