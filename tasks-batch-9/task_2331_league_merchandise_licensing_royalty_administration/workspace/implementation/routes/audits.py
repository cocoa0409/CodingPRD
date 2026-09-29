"""Audit engagements: scope, fieldwork, findings, settlement and closure (PRD 3.8)."""

from flask import Blueprint

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, touch
from errors import ApiError
from middleware import (ROLE_AUDITOR, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_LICENSEE,
                        ROLE_MANAGER, guard, paginate, pagination)
from routes import reports as reports_routes
from services import calc, domain

bp = Blueprint("audits", __name__)

READ_ROLES = [ROLE_MANAGER, ROLE_COMPLIANCE, ROLE_FINANCE, ROLE_AUDITOR, ROLE_LICENSEE]


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def _find(engagement_id):
    row = S.engagements.get(engagement_id)
    if row is None:
        raise ApiError("ERR_ENGAGEMENT_NOT_FOUND")
    return row


def _reports_by_quarter(agreement_id):
    """Latest non-returned report per quarter, keyed by quarter label."""
    table = {}
    for report in domain.reports_of(agreement_id):
        if report["status"] == "RETURNED":
            continue
        current = table.get(report["period_quarter"])
        if current is None or report["created_at"] > current["created_at"]:
            table[report["period_quarter"]] = report
    return table


def _in_scope_reports(engagement):
    return [r for r in domain.reports_of(engagement["agreement_id"])
            if r["audit_engagement_id"] == engagement["id"]]


# --------------------------------------------------------------------------- #
# creation and reads                                                          #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/audit-engagements")
def create_engagement():
    ctx = guard([ROLE_AUDITOR])
    body = ctx.body

    agreement_id = body.get("agreement_id")
    if agreement_id is not None and agreement_id not in S.agreements:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    if agreement_id is None:
        _bad("agreement_id is required.")
    agreement = S.agreements[agreement_id]

    V.req_string(body, "agreement_id")
    scope_quarters = V.quarter_sequence(body, "scope_quarters", 1, 8)

    for report in domain.reports_of(agreement_id):
        if report["period_quarter"] in scope_quarters and \
                report["accepted_by_user_id"] is not None and \
                report["accepted_by_user_id"] == ctx.uid:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The controller who accepted a report may not audit it.")

    current = db.current_quarter()
    for quarter in scope_quarters:
        elapsed = db.elapsed_quarters(quarter, current)
        if elapsed < 0 or elapsed > K.AUDIT_LOOKBACK_QUARTERS:
            raise ApiError("ERR_AUDIT_WINDOW_EXPIRED")

    row = db.base_row()
    row.update({
        "agreement_id": agreement_id,
        "scope_quarters": scope_quarters,
        "status": "OPENED",
        "opened_by_user_id": ctx.uid,
        "opened_quarter": current,
        "audited_quarters": [],
        "recomputed_royalty_cents": 0,
        "reported_royalty_cents": 0,
        "underreported_royalty_cents": 0,
        "underreport_rate_bps": 0,
        "cost_shift_applied": False,
        "audit_cost_recovery_cents": 0,
        "interest_cents": 0,
        "recovery_assessed_cents": 0,
        "findings_issued_by_user_id": None,
        "findings_quarter": None,
        "findings_round": 0,
        "dispute_note": None,
        "settlement_basis": None,
        "settled_amount_cents": None,
        "settled_by_user_id": None,
    })
    S.engagements[row["id"]] = row
    return response.created(serializers.dump("AuditEngagement", row))


@bp.get("/licensing/audit-engagements")
def list_engagements():
    ctx = guard(READ_ROLES)
    limit, offset = pagination()
    agreement_id = mw.filter_str("agreement_id")
    status = mw.filter_enum("status", K.ENGAGEMENT_STATUSES)
    cost_shift = mw.filter_bool("cost_shift_applied")

    rows = list(S.engagements.values())
    if ctx.role == ROLE_LICENSEE:
        own = {a["id"] for a in domain.agreements_of(ctx.uid)}
        rows = [r for r in rows if r["agreement_id"] in own]
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if cost_shift is not None:
        rows = [r for r in rows if r["cost_shift_applied"] == cost_shift]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("AuditEngagement", page),
                            limit, offset, total)


@bp.get("/licensing/audit-engagements/<engagement_id>")
def get_engagement(engagement_id):
    ctx = guard(READ_ROLES)
    engagement = _find(engagement_id)
    mw.scope_agreement(ctx, S.agreements[engagement["agreement_id"]])
    return response.ok(serializers.dump("AuditEngagement", engagement))


# --------------------------------------------------------------------------- #
# fieldwork                                                                   #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/audit-engagements/<engagement_id>/begin-fieldwork")
def begin_fieldwork(engagement_id):
    guard([ROLE_AUDITOR])
    engagement = _find(engagement_id)
    if engagement["status"] != "OPENED":
        raise ApiError("ERR_INVALID_STATE")

    table = _reports_by_quarter(engagement["agreement_id"])
    pulled = []
    for quarter in engagement["scope_quarters"]:
        report = table.get(quarter)
        if report is None or report["status"] != "ACCEPTED":
            raise ApiError("ERR_AUDIT_SCOPE_NOT_ACCEPTED")
        pulled.append(report)

    for report in pulled:
        report["status"] = "UNDER_AUDIT"
        report["audit_engagement_id"] = engagement["id"]
        touch(report)

    engagement["status"] = "FIELDWORK"
    touch(engagement)
    return response.ok(serializers.dump("AuditEngagement", engagement))


# --------------------------------------------------------------------------- #
# findings                                                                    #
# --------------------------------------------------------------------------- #

def _validate_audited_quarters(body):
    raw = V.req_list(body, "audited_quarters", 1, 8)
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            _bad("audited_quarters entries must be objects.")
        quarter = V.req_quarter(item, "period_quarter")
        gross = V.req_cents(item, "audited_gross_sales_cents")
        closeout = V.req_cents(item, "audited_closeout_cents")
        deductions = V.req_cents(item, "audited_deductions_cents")
        entries.append({
            "period_quarter": quarter,
            "audited_gross_sales_cents": gross,
            "audited_closeout_cents": closeout,
            "audited_deductions_cents": deductions,
        })
    labels = [e["period_quarter"] for e in entries]
    if len(set(labels)) != len(labels):
        _bad("audited_quarters entries must name distinct quarters.")
    for index in range(1, len(labels)):
        if db.elapsed_quarters(labels[index - 1], labels[index]) != 1:
            _bad("audited_quarters must be consecutive quarters in ascending order.")
    return entries


@bp.post("/licensing/audit-engagements/<engagement_id>/issue-findings")
def issue_findings(engagement_id):
    ctx = guard([ROLE_AUDITOR])
    engagement = _find(engagement_id)
    entries = _validate_audited_quarters(ctx.body)

    if engagement["status"] not in ("FIELDWORK", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE")

    labels = [e["period_quarter"] for e in entries]
    if labels != engagement["scope_quarters"]:
        raise ApiError("ERR_AUDIT_SCOPE_NOT_ACCEPTED")

    agreement = S.agreements[engagement["agreement_id"]]
    category = domain.category_of(agreement)
    table = _reports_by_quarter(engagement["agreement_id"])

    for quarter in labels:
        report = table.get(quarter)
        if report is None or report["status"] not in ("UNDER_AUDIT", "ADJUSTED"):
            raise ApiError("ERR_AUDIT_SCOPE_NOT_ACCEPTED")

    enriched = []
    total_recomputed = 0
    total_reported = 0
    total_underreported = 0
    total_interest = 0
    for entry in entries:
        report = table[entry["period_quarter"]]
        recomputed = calc.restate_entry(entry, category)
        reported = reports_routes.effective_royalty(report)
        underreported = recomputed - reported
        if underreported < 0:
            underreported = 0
        elapsed = db.elapsed_quarters(entry["period_quarter"], engagement["opened_quarter"])
        if elapsed < 0:
            elapsed = 0
        interest = calc.audit_interest(underreported, elapsed)

        row = dict(entry)
        row["recomputed_royalty_cents"] = recomputed
        row["reported_royalty_cents"] = reported
        row["underreported_cents"] = underreported
        enriched.append(row)

        total_recomputed += recomputed
        total_reported += reported
        total_underreported += underreported
        total_interest += interest

    rate = calc.underreport_rate(total_underreported, total_reported)
    cost_shift = rate >= calc.COST_SHIFT_THRESHOLD_BPS
    cost_recovery = calc.AUDIT_COST_FLAT_CENTS if cost_shift else 0

    engagement.update({
        "status": "FINDINGS_ISSUED",
        "audited_quarters": enriched,
        "recomputed_royalty_cents": total_recomputed,
        "reported_royalty_cents": total_reported,
        "underreported_royalty_cents": total_underreported,
        "underreport_rate_bps": rate,
        "cost_shift_applied": cost_shift,
        "audit_cost_recovery_cents": cost_recovery,
        "interest_cents": total_interest,
        "recovery_assessed_cents": total_underreported + total_interest + cost_recovery,
        "findings_issued_by_user_id": ctx.uid,
        "findings_quarter": db.current_quarter(),
        "findings_round": engagement["findings_round"] + 1,
    })
    touch(engagement)
    domain.refresh_outstanding_recovery(domain.licensee_of(agreement))
    return response.ok(serializers.dump("AuditEngagement", engagement))


@bp.post("/licensing/audit-engagements/<engagement_id>/dispute")
def dispute_findings(engagement_id):
    ctx = guard([ROLE_LICENSEE])
    engagement = _find(engagement_id)
    agreement = S.agreements[engagement["agreement_id"]]
    mw.scope_agreement(ctx, agreement)
    note = V.req_string(ctx.body, "dispute_note", 1)

    if engagement["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    engagement["status"] = "DISPUTED"
    engagement["dispute_note"] = note
    touch(engagement)
    return response.ok(serializers.dump("AuditEngagement", engagement))


# --------------------------------------------------------------------------- #
# settlement                                                                  #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/audit-engagements/<engagement_id>/settle")
def settle(engagement_id):
    ctx = guard([ROLE_FINANCE])
    engagement = _find(engagement_id)
    body = ctx.body
    basis = V.req_enum(body, "settlement_basis", K.SETTLEMENT_BASES)
    negotiated = V.opt_cents(body, "negotiated_cents")

    if engagement["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    if engagement["findings_issued_by_user_id"] == ctx.uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The auditor who issued findings may not settle them.")

    assessed = engagement["recovery_assessed_cents"]
    if basis == "NEGOTIATED":
        if negotiated is None or negotiated < 0 or negotiated > assessed:
            raise ApiError("ERR_SETTLEMENT_OUT_OF_RANGE")
        settled_amount = negotiated
    else:
        if negotiated is not None:
            raise ApiError("ERR_SETTLEMENT_OUT_OF_RANGE")
        settled_amount = assessed

    agreement = S.agreements[engagement["agreement_id"]]
    licensee = domain.licensee_of(agreement)
    posture_at_start = agreement["compliance_posture"]

    engagement["status"] = "SETTLED"
    engagement["settlement_basis"] = basis
    engagement["settled_amount_cents"] = settled_amount
    engagement["settled_by_user_id"] = ctx.uid
    touch(engagement)

    # hops one and two: restate the reports and re-post the ledger
    if engagement["underreported_royalty_cents"] > 0:
        recomputed_by_quarter = {e["period_quarter"]: e["recomputed_royalty_cents"]
                                 for e in engagement["audited_quarters"]}
        for report in _in_scope_reports(engagement):
            if report["status"] != "UNDER_AUDIT":
                continue
            adjusted = recomputed_by_quarter.get(report["period_quarter"])
            if adjusted is None:
                continue
            old_recoup = report["recoupment_applied_cents"]
            old_royalty = report["royalty_due_cents"]
            agreement["unrecouped_advance_cents"] += old_recoup
            agreement["recouped_advance_cents"] -= old_recoup
            agreement["cumulative_royalty_cents"] -= old_royalty

            report["status"] = "ADJUSTED"
            report["adjusted_royalty_due_cents"] = adjusted
            result = reports_routes.apply_waterfall(
                report, agreement, adjusted, posture_at_start, report["late_days"])
            touch(report)

            agreement["unrecouped_advance_cents"] -= result["recoupment_applied_cents"]
            agreement["recouped_advance_cents"] += result["recoupment_applied_cents"]
            agreement["cumulative_royalty_cents"] += adjusted
        touch(agreement)
        domain.assess_interim_shortfall(agreement, db.current_quarter())

    # hop three: the licensee's standing
    as_of = db.current_quarter()
    domain.refresh_risk_index(licensee, as_of)
    domain.refresh_outstanding_recovery(licensee)

    # hops four and five: posture transitions and the review holds they imply
    domain.posture_cascade(licensee["id"], as_of)

    return response.ok(serializers.dump("AuditEngagement", engagement))


@bp.post("/licensing/audit-engagements/<engagement_id>/close")
def close_engagement(engagement_id):
    guard([ROLE_AUDITOR])
    engagement = _find(engagement_id)
    if engagement["status"] not in ("OPENED", "FIELDWORK", "SETTLED"):
        raise ApiError("ERR_INVALID_STATE")

    for report in _in_scope_reports(engagement):
        if report["status"] in ("UNDER_AUDIT", "ADJUSTED"):
            report["status"] = "CLOSED"
            touch(report)

    engagement["status"] = "CLOSED"
    touch(engagement)
    return response.ok(serializers.dump("AuditEngagement", engagement))
