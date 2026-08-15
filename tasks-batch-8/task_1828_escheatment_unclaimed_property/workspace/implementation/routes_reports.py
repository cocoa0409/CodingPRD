"""Holder report and report line-item endpoints (PRD 3.4)."""

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, get_property_or_404, get_report_or_404,
    rule_cutoff_date, rule_due_date, recompute_report_totals,
    securities_provisional_value, terminal_letter_exists,
    find_applicable_rule,
)

bp = Blueprint("reports", __name__)


def report_view(r):
    return {
        "id": r["id"],
        "state_code": r["state_code"],
        "report_year": r["report_year"],
        "status": r["status"],
        "supersedes_report_id": r["supersedes_report_id"],
        "cutoff_date": r["cutoff_date"].isoformat(),
        "due_date": r["due_date"].isoformat(),
        "submitted_date": r["submitted_date"].isoformat() if r["submitted_date"] else None,
        "submitted_by_user_id": r["submitted_by_user_id"],
        "accepted_date": r["accepted_date"].isoformat() if r["accepted_date"] else None,
        "rejection_reason": r["rejection_reason"],
        "total_provisional_cents": r["total_provisional_cents"],
        "total_final_cents": r["total_final_cents"],
        "confirmed_remittance_cents": r["confirmed_remittance_cents"],
        "line_count": r["line_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def line_item_view(l):
    return {
        "id": l["id"],
        "report_id": l["report_id"],
        "property_id": l["property_id"],
        "line_type": l["line_type"],
        "provisional_value_cents": l["provisional_value_cents"],
        "final_value_cents": l["final_value_cents"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def _state_rule_for_report_calendar(state_code):
    """The state's DormancyRule set supplies the reporting calendar. When
    several rules exist for the state (one per property type), they share the
    calendar fields in any well-formed configuration; take the first. When no
    rule exists yet, the DormancyRule field defaults (06-30 / 11-01) supply
    the calendar — report creation is not gated on rule existence."""
    for rule in db.dormancy_rules.values():
        if rule["state_code"] == state_code:
            return rule
    return {
        "report_cutoff_month_day": "06-30",
        "report_due_month_day": "11-01",
    }


@bp.post("/escheatment/holder-reports")
def create_report():
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    state_code = mw.req_string(data, "state_code")
    report_year = mw.req_int(data, "report_year", min_value=1)

    for existing in db.reports.values():
        if (
            existing["state_code"] == state_code
            and existing["report_year"] == report_year
            and existing["status"] != "SUPERSEDED"
        ):
            raise_error(
                errors.ERR_DUPLICATE_REPORT_PERIOD,
                "A non-SUPERSEDED report already exists for this state and year",
            )
    rule = _state_rule_for_report_calendar(state_code)
    report = new_entity({
        "state_code": state_code,
        "report_year": report_year,
        "status": "DRAFT",
        "supersedes_report_id": None,
        "cutoff_date": rule_cutoff_date(rule, report_year),
        "due_date": rule_due_date(rule, report_year),
        "submitted_date": None,
        "submitted_by_user_id": None,
        "accepted_date": None,
        "rejection_reason": None,
        "total_provisional_cents": 0,
        "total_final_cents": 0,
        "confirmed_remittance_cents": 0,
        "line_count": 0,
    })
    db.reports[report["id"]] = report
    return resp.success(report_view(report), "object", 201)


@bp.get("/escheatment/holder-reports")
def list_reports():
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    limit, offset = mw.pagination_params()
    items = list(db.reports.values())
    state_code = mw.request.args.get("state_code")
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    report_year = mw.request.args.get("report_year")
    if report_year is not None:
        try:
            year = int(report_year)
        except ValueError:
            raise_error(errors.ERR_INVALID_REQUEST, "report_year must be an integer")
        items = [r for r in items if r["report_year"] == year]
    status = mw.request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([report_view(r) for r in page], "array", 200, pagination=meta)


@bp.get("/escheatment/holder-reports/<reportId>")
def get_report(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    report = get_report_or_404(reportId)
    return resp.success(report_view(report), "object", 200)


@bp.post("/escheatment/holder-reports/<reportId>/amendments")
def create_amendment(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    expected_version = mw.req_int(data, "expected_report_version", min_value=1)
    report = get_report_or_404(reportId)

    # OCC check (layer 7) precedes the state check (layer 8).
    if expected_version != report["version"]:
        raise_error(
            errors.ERR_STALE_VERSION,
            "expected_report_version does not match the report's current version",
        )
    if report["status"] != "ACCEPTED":
        raise_error(
            errors.ERR_REPORT_NOT_ACCEPTED,
            "Amendment requires the report to be ACCEPTED",
        )
    for other in db.reports.values():
        if (
            other["supersedes_report_id"] == report["id"]
            and other["status"] in ("DRAFT", "SUBMITTED")
        ):
            raise_error(
                errors.ERR_PENDING_AMENDMENT_EXISTS,
                "A DRAFT or SUBMITTED amendment of this report already exists",
            )
    amendment = new_entity({
        "state_code": report["state_code"],
        "report_year": report["report_year"],
        "status": "DRAFT",
        "supersedes_report_id": report["id"],
        "cutoff_date": report["cutoff_date"],
        "due_date": report["due_date"],
        "submitted_date": None,
        "submitted_by_user_id": None,
        "accepted_date": None,
        "rejection_reason": None,
        "total_provisional_cents": 0,
        "total_final_cents": 0,
        "confirmed_remittance_cents": 0,
        "line_count": 0,
    })
    db.reports[amendment["id"]] = amendment
    # Copy every non-REMOVED line of the prior report as a fresh INCLUDED line.
    for line in list(db.line_items.values()):
        if line["report_id"] != report["id"] or line["status"] == "REMOVED":
            continue
        copied = new_entity({
            "report_id": amendment["id"],
            "property_id": line["property_id"],
            "line_type": line["line_type"],
            "provisional_value_cents": line["provisional_value_cents"],
            "final_value_cents": None,
            "status": "INCLUDED",
        })
        db.line_items[copied["id"]] = copied
    recompute_report_totals(amendment, bump=False)
    touch(amendment)
    # The superseded report's version increments at amendment creation, though
    # it remains ACCEPTED until the amendment itself is accepted.
    touch(report)
    return resp.success(report_view(amendment), "object", 201)


@bp.get("/escheatment/holder-reports/<reportId>/amendments")
def list_amendments(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    report = get_report_or_404(reportId)
    limit, offset = mw.pagination_params()
    items = [r for r in db.reports.values() if r["supersedes_report_id"] == report["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([report_view(r) for r in page], "array", 200, pagination=meta)


@bp.post("/escheatment/holder-reports/<reportId>/line-items")
def add_line_item(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    property_id = mw.req_string(data, "property_id")
    expected_version = mw.req_int(data, "expected_report_version", min_value=1)
    report = get_report_or_404(reportId)
    prop = get_property_or_404(property_id)

    # OCC (layer 7) before state (layer 8) before referential (layer 11).
    if expected_version != report["version"]:
        raise_error(
            errors.ERR_STALE_VERSION,
            "expected_report_version does not match the report's current version",
        )
    if report["status"] != "DRAFT":
        raise_error(errors.ERR_REPORT_NOT_DRAFT, "Line addition requires a DRAFT report")
    if prop["status"] != "REPORTABLE" or prop["state_code"] != report["state_code"]:
        raise_error(
            errors.ERR_PROPERTY_NOT_REPORTABLE,
            "Line addition requires a REPORTABLE property of the report's state",
        )
    if prop["property_type"] == "BROKERAGE_SHARES":
        detail = next(
            (d for d in db.securities_details.values() if d["property_id"] == prop["id"]),
            None,
        )
        if detail is None:
            raise_error(
                errors.ERR_SECURITIES_DETAIL_REQUIRED,
                "BROKERAGE_SHARES property requires a SecuritiesDetail before inclusion",
            )
        line_type = "SECURITIES"
        provisional = securities_provisional_value(detail)
    else:
        line_type = "CASH"
        provisional = prop["original_value_cents"]
    line = new_entity({
        "report_id": report["id"],
        "property_id": prop["id"],
        "line_type": line_type,
        "provisional_value_cents": provisional,
        "final_value_cents": None,
        "status": "INCLUDED",
    })
    db.line_items[line["id"]] = line
    recompute_report_totals(report, bump=True)
    return resp.success(line_item_view(line), "object", 201)


@bp.get("/escheatment/holder-reports/<reportId>/line-items")
def list_line_items(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    report = get_report_or_404(reportId)
    limit, offset = mw.pagination_params()
    items = [l for l in db.line_items.values() if l["report_id"] == report["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([line_item_view(l) for l in page], "array", 200, pagination=meta)


@bp.post("/escheatment/holder-reports/<reportId>/line-items/<lineId>/remove")
def remove_line_item(reportId, lineId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    mw.body_json(required=False)
    report = get_report_or_404(reportId)
    line = db.line_items.get(lineId)
    if line is None or line["report_id"] != report["id"]:
        raise_error(
            errors.ERR_LINE_ITEM_NOT_FOUND,
            "Line item does not exist on this report",
        )
    if report["status"] != "DRAFT":
        raise_error(errors.ERR_REPORT_NOT_DRAFT, "Line removal requires a DRAFT report")
    if line["status"] != "INCLUDED":
        raise_error(
            errors.ERR_LINE_ITEM_NOT_REMOVABLE,
            "Line removal requires line status INCLUDED",
        )
    line["status"] = "REMOVED"
    touch(line)
    recompute_report_totals(report, bump=True)
    return resp.success(line_item_view(line), "object", 200)


@bp.post("/escheatment/holder-reports/<reportId>/submit")
def submit_report(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    mw.body_json(required=False)
    report = get_report_or_404(reportId)
    if report["status"] != "DRAFT":
        raise_error(errors.ERR_REPORT_NOT_DRAFT, "Submit requires a DRAFT report")
    # The empty-report guard covers the included set (INCLUDED or FINAL): a
    # REJECTED-then-reopened report carries already-FINAL cash lines and must
    # remain resubmittable through the reopen workflow.
    included_set = [l for l in db.line_items.values()
                    if l["report_id"] == report["id"] and l["status"] in ("INCLUDED", "FINAL")]
    if not included_set:
        raise_error(errors.ERR_EMPTY_REPORT, "Submit requires at least one INCLUDED line")
    lines = [l for l in included_set if l["status"] == "INCLUDED"]
    for line in lines:
        prop = db.properties.get(line["property_id"])
        if prop is None:
            continue
        rule = find_applicable_rule(
            prop["state_code"], prop["property_type"], prop["last_contact_date"]
        )
        threshold = rule["dd_threshold_cents"] if rule else 0
        if prop["original_value_cents"] >= threshold and not terminal_letter_exists(prop["id"]):
            raise_error(
                errors.ERR_DUE_DILIGENCE_INCOMPLETE,
                "An over-threshold INCLUDED line lacks a terminal due-diligence letter",
            )
    today = clock.today()
    report["submitted_date"] = today
    report["submitted_by_user_id"] = ctx.user_id
    report["status"] = "SUBMITTED"
    for line in lines:
        if line["line_type"] == "CASH":
            line["status"] = "FINAL"
            line["final_value_cents"] = line["provisional_value_cents"]
            touch(line)
    recompute_report_totals(report, bump=True)
    return resp.success(report_view(report), "object", 200)


@bp.post("/escheatment/holder-reports/<reportId>/accept")
def accept_report(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    mw.body_json(required=False)
    report = get_report_or_404(reportId)
    if report["status"] != "SUBMITTED":
        raise_error(errors.ERR_REPORT_NOT_SUBMITTED, "Accept requires a SUBMITTED report")
    if ctx.user_id == report["submitted_by_user_id"]:
        raise_error(
            errors.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            "The acceptor must differ from the submitting officer",
        )
    report["status"] = "ACCEPTED"
    report["accepted_date"] = clock.today()
    # Cascade: line properties REPORTABLE -> REPORTED.
    for line in db.line_items.values():
        if line["report_id"] != report["id"] or line["status"] not in ("INCLUDED", "FINAL"):
            continue
        prop = db.properties.get(line["property_id"])
        if prop is not None and prop["status"] == "REPORTABLE":
            prop["status"] = "REPORTED"
            touch(prop)
    # Cascade: the superseded report ACCEPTED -> SUPERSEDED.
    if report["supersedes_report_id"] is not None:
        prior = db.reports.get(report["supersedes_report_id"])
        if prior is not None and prior["status"] == "ACCEPTED":
            prior["status"] = "SUPERSEDED"
            touch(prior)
    touch(report)
    return resp.success(report_view(report), "object", 200)


@bp.post("/escheatment/holder-reports/<reportId>/reject")
def reject_report(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("StateAuditor",))
    data = mw.body_json()
    reason = mw.req_string(data, "rejection_reason")
    report = get_report_or_404(reportId)
    if report["status"] != "SUBMITTED":
        raise_error(errors.ERR_REPORT_NOT_SUBMITTED, "Reject requires a SUBMITTED report")
    report["status"] = "REJECTED"
    report["rejection_reason"] = reason
    touch(report)
    return resp.success(report_view(report), "object", 200)


@bp.post("/escheatment/holder-reports/<reportId>/reopen")
def reopen_report(reportId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    mw.body_json(required=False)
    report = get_report_or_404(reportId)
    if report["status"] != "REJECTED":
        raise_error(errors.ERR_REPORT_NOT_REJECTED, "Reopen requires a REJECTED report")
    report["status"] = "DRAFT"
    report["submitted_date"] = None
    report["submitted_by_user_id"] = None
    report["rejection_reason"] = None
    touch(report)
    return resp.success(report_view(report), "object", 200)
