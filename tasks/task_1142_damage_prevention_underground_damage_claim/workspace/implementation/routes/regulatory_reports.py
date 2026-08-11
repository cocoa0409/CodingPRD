"""RegulatoryReport endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db
from errors import (err_amend_chain, err_invalid_request, err_invalid_state,
                    err_not_found, err_period_overlap)
from middleware import require_roles
from serializers import report_out
from services.core import (FILING_WINDOW_DAYS, PENALTY_BASE_CENTS,
                           PENALTY_CAP_CENTS, PENALTY_PER_DAY_CENTS, touch)
from util import (get_pagination, new_id, paginate, parse_body, parse_dt,
                  require_enum, success_envelope)

bp = Blueprint("regulatory_reports", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


@bp.route("/damage-recovery/regulatory-reports", methods=["POST"])
def create_report():
    require_roles("ClaimsAdjuster")
    body = parse_body(required_fields=["report_type"])
    report_type = require_enum(body["report_type"], ("INCIDENT", "QUARTERLY_SUMMARY"), "report_type")
    case_id = body.get("damage_case_id")
    period_start = None
    period_end = None
    if report_type == "INCIDENT":
        if case_id is None:
            raise err_invalid_request("damage_case_id is required for INCIDENT")
        case = db.damage_cases.get(case_id)
        if case is None:
            raise err_not_found("damage case not found")
    else:
        if case_id is not None:
            raise err_invalid_request("damage_case_id must be null for QUARTERLY_SUMMARY")
        if body.get("period_start") is None or body.get("period_end") is None:
            raise err_invalid_request("period_start and period_end are required for QUARTERLY_SUMMARY")
        period_start = parse_dt(body["period_start"], "period_start")
        period_end = parse_dt(body["period_end"], "period_end")
        if period_end < period_start:
            raise err_invalid_request("period_end must be on or after period_start")
        # closed interval overlap incl. shared boundary day, among non-SUPERSEDED quarterlies
        for r in db.regulatory_reports.values():
            if r["report_type"] != "QUARTERLY_SUMMARY" or r["status"] == "SUPERSEDED":
                continue
            if period_start <= r["period_end"] and r["period_start"] <= period_end:
                raise err_period_overlap()
    payload_notes = body.get("payload_notes", "")
    if not isinstance(payload_notes, str):
        raise err_invalid_request("payload_notes must be a string")
    now = clock.get_current_utc()
    rid = new_id()
    report = {
        "id": rid,
        "damage_case_id": case_id,
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "payload_notes": payload_notes,
        "amends_report_id": None,
        "status": "DRAFT",
        "filed_at": None,
        "days_late": 0,
        "penalty_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.regulatory_reports[rid] = report
    return success_envelope(report_out(report), "object", 201)


@bp.route("/damage-recovery/regulatory-reports/<rid>", methods=["GET"])
def get_report(rid):
    require_roles(*ALL_ROLES)
    r = db.regulatory_reports.get(rid)
    if r is None:
        raise err_not_found("regulatory report not found")
    return success_envelope(report_out(r), "object", 200)


@bp.route("/damage-recovery/regulatory-reports", methods=["GET"])
def list_reports():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.regulatory_reports.values())
    case_id = request.args.get("damage_case_id")
    amends = request.args.get("amends_report_id")
    rtype = request.args.get("report_type")
    status = request.args.get("status")
    if case_id is not None:
        items = [r for r in items if r["damage_case_id"] == case_id]
    if amends is not None:
        items = [r for r in items if r["amends_report_id"] == amends]
    if rtype is not None:
        items = [r for r in items if r["report_type"] == rtype]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([report_out(r) for r in page], "array", 200, meta)


@bp.route("/damage-recovery/regulatory-reports/<rid>/file", methods=["POST"])
def file_report(rid):
    require_roles("ClaimsAdjuster")
    r = db.regulatory_reports.get(rid)
    if r is None:
        raise err_not_found("regulatory report not found")
    if r["status"] != "DRAFT":
        raise err_invalid_state("report is not DRAFT")
    now = clock.get_current_utc()
    if r["report_type"] == "INCIDENT":
        case = db.damage_cases.get(r["damage_case_id"])
        if case is None:
            raise err_not_found("damage case not found")
        base = case["occurred_at"]
    else:
        base = r["period_end"]
    deadline = base + timedelta(days=FILING_WINDOW_DAYS)
    if now <= deadline:
        days_late = 0
        penalty = 0
    else:
        days_late = int((now - deadline).total_seconds() // 86400)
        if days_late < 1:
            days_late = 1
        penalty = min(PENALTY_CAP_CENTS, PENALTY_BASE_CENTS + PENALTY_PER_DAY_CENTS * days_late)
    r["status"] = "FILED"
    r["filed_at"] = now
    r["days_late"] = days_late
    r["penalty_cents"] = penalty
    r["updated_at"] = now
    r["version"] += 1
    return success_envelope(report_out(r), "object", 200)


@bp.route("/damage-recovery/regulatory-reports/<rid>/amend", methods=["POST"])
def amend_report(rid):
    require_roles("ClaimsAdjuster")
    r = db.regulatory_reports.get(rid)
    if r is None:
        raise err_not_found("regulatory report not found")
    if r["status"] != "FILED":
        raise err_amend_chain()
    body = parse_body()
    payload_notes = body.get("payload_notes", r["payload_notes"])
    if not isinstance(payload_notes, str):
        raise err_invalid_request("payload_notes must be a string")
    now = clock.get_current_utc()
    r["status"] = "SUPERSEDED"
    r["updated_at"] = now
    r["version"] += 1
    nid = new_id()
    successor = {
        "id": nid,
        "damage_case_id": r["damage_case_id"],
        "report_type": r["report_type"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "payload_notes": payload_notes,
        "amends_report_id": r["id"],
        "status": "DRAFT",
        "filed_at": None,
        "days_late": 0,
        "penalty_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.regulatory_reports[nid] = successor
    return success_envelope(report_out(successor), "object", 200)
