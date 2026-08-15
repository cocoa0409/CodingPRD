"""ComplianceReport endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_REQUIREMENT_NOT_CONFIGURED,
    ERR_REPORT_PERIOD_OVERLAP, ERR_VALIDATION,
)
from middleware import authorized, ALL_ROLES, ROLE_COORDINATOR, ROLE_AUDITOR
from response import success_object
from services.core import new_record, public, apply_changes, compute_snapshot
from util import CLOCK, parse_date
from validate import get_body, reject_unknown, req_date, req_enum, req_str, opt_str
from routes.helpers import check_site_fk, get_path, list_query

bp = Blueprint("reports", __name__)

OVERLAP_STATUSES = ("DRAFT", "STALE", "SUBMITTED", "ACCEPTED")


def _snapshot_fields(site_id, period_start, period_end):
    attainments, count_only, strict, score = compute_snapshot(
        site_id, period_start, period_end)
    return {
        "type_attainments": attainments,
        "overall_compliant_count_only": count_only,
        "overall_compliant_strict": strict,
        "overall_score_pct": score,
        "snapshot_generated_at": CLOCK.now_iso(),
    }


@bp.post("/compliance-reports")
def create_report():
    authorized([ROLE_COORDINATOR])
    body = get_body()
    check_site_fk(body)
    reject_unknown(body, ["site_id", "period_start", "period_end"])
    site_id = req_str(body, "site_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    if parse_date(period_end) < parse_date(period_start):
        raise_error(ERR_VALIDATION, "period_end must not precede period_start")

    # priority 8c: at least one requirement configured at the site
    if not any(r["site_id"] == site_id for r in db["requirements"].values()):
        raise_error(ERR_REQUIREMENT_NOT_CONFIGURED,
                    "no DrillTypeRequirement configured at this site")

    # priority 9: closed-interval period overlap
    ps, pe = parse_date(period_start), parse_date(period_end)
    for r in db["compliance_reports"].values():
        if r["site_id"] != site_id or r["status"] not in OVERLAP_STATUSES:
            continue
        if ps <= parse_date(r["period_end"]) and parse_date(r["period_start"]) <= pe:
            raise_error(ERR_REPORT_PERIOD_OVERLAP,
                        "report period overlaps another report at this site")

    fields = {
        "site_id": site_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "submitted_at": None,
        "decided_by_user_id": None,
        "auditor_comment": None,
    }
    fields.update(_snapshot_fields(site_id, period_start, period_end))
    rec = new_record("compliance_reports", fields)
    return success_object(public(rec), 201)


@bp.get("/sites/<rid>/compliance-reports")
def list_reports(rid):
    authorized(ALL_ROLES)
    get_path("sites", rid)
    filters = {"site_id": rid, "status": request.args.get("status")}
    return list_query("compliance_reports", filters)


@bp.post("/compliance-reports/<rid>/submit")
def submit_report(rid):
    authorized([ROLE_COORDINATOR])
    rec = get_path("compliance_reports", rid)
    body = get_body()
    reject_unknown(body, [])

    if rec["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT report may be submitted")

    apply_changes(rec, {"status": "SUBMITTED", "submitted_at": CLOCK.now_iso()})
    return success_object(public(rec))


@bp.post("/compliance-reports/<rid>/decide")
def decide_report(rid):
    caller = authorized([ROLE_AUDITOR])
    rec = get_path("compliance_reports", rid)
    body = get_body()
    reject_unknown(body, ["decision", "auditor_comment"])
    decision = req_enum(body, "decision", ["ACCEPT", "REJECT"])
    comment = opt_str(body, "auditor_comment")

    if rec["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "only a SUBMITTED report may be decided")

    apply_changes(rec, {
        "status": "ACCEPTED" if decision == "ACCEPT" else "REJECTED",
        "decided_by_user_id": caller.user_id,
        "auditor_comment": comment,
    })
    return success_object(public(rec))


@bp.post("/compliance-reports/<rid>/regenerate")
def regenerate_report(rid):
    authorized([ROLE_COORDINATOR])
    rec = get_path("compliance_reports", rid)
    body = get_body()
    reject_unknown(body, [])

    if rec["status"] not in ("STALE", "REJECTED"):
        raise_error(ERR_INVALID_STATE,
                    "only a STALE or REJECTED report may be regenerated")

    changes = {"status": "DRAFT"}
    changes.update(_snapshot_fields(rec["site_id"], rec["period_start"], rec["period_end"]))
    if rec["status"] == "REJECTED":
        changes["auditor_comment"] = None
        changes["decided_by_user_id"] = None
    apply_changes(rec, changes)
    return success_object(public(rec))
