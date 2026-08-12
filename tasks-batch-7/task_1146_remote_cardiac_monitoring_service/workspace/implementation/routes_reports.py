"""Diagnostic reports."""
from datetime import timedelta
from decimal import Decimal

import db
from bp import bp
from clock import now
from db import base_record, touch
from domain import FINAL_SLA_HOURS, round_half_up_2
from errors import ApiError
from helpers import (READ_ROLES, auth, body, opt_bool, pagination, req_enum,
                     req_str, require, sorted_by_creation)
from response import serialize, success, success_list

REPORT_TYPES = {"INTERIM", "FINAL"}


@bp.post("/v1/episodes/<episode_id>/reports")
def create_report(episode_id):
    uid, role = auth()
    require(role, {"Physician"})
    ep = db.episodes.get(episode_id)
    if ep is None:
        raise ApiError("ERR_EPISODE_NOT_FOUND", 404, "Episode not found")
    d = body()
    report_type = req_enum(d, "report_type", REPORT_TYPES)
    findings_summary = req_str(d, "findings_summary")
    no_significant = opt_bool(d, "no_significant_findings", default=False)
    rec = base_record()
    rec.update({
        "episode_id": ep["id"],
        "reading_physician_id": uid,
        "report_type": report_type,
        "findings_summary": findings_summary,
        "no_significant_findings": no_significant,
        "status": "DRAFT",
        "revision_count": 0,
        "finalized_at": None,
        "turnaround_hours": None,
        "sla_met": None,
    })
    db.reports[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/v1/reports")
def list_reports():
    uid, role = auth()
    require(role, READ_ROLES)
    limit, offset = pagination()
    from flask import request
    ep_f = request.args.get("episode_id")
    phys_f = request.args.get("reading_physician_id")
    status_f = request.args.get("status")
    items = list(db.reports.values())
    if ep_f is not None:
        items = [x for x in items if x["episode_id"] == ep_f]
    if phys_f is not None:
        items = [x for x in items if x["reading_physician_id"] == phys_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    return success_list(sorted_by_creation(items), limit, offset)


def _get_report_or_404(report_id):
    rec = db.reports.get(report_id)
    if rec is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Report not found")
    return rec


@bp.get("/v1/reports/<report_id>")
def get_report(report_id):
    uid, role = auth()
    require(role, READ_ROLES)
    return success(serialize(_get_report_or_404(report_id)))


@bp.post("/v1/reports/<report_id>/finalize")
def finalize_report(report_id):
    uid, role = auth()
    require(role, {"Physician"})
    rec = _get_report_or_404(report_id)
    if rec["reading_physician_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Caller is not the reading physician")
    if rec["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only DRAFT or AMENDED reports can be finalized")
    ep = db.episodes.get(rec["episode_id"])
    # safety gate
    if any(a for a in db.alerts.values()
           if a["episode_id"] == rec["episode_id"]
           and a["severity"] == "CRITICAL" and a["status"] != "CLOSED"):
        raise ApiError("ERR_CRITICAL_ALERTS_OPEN", 422,
                       "A CRITICAL alert on the episode is not CLOSED")
    # referential gate
    if rec["report_type"] == "FINAL" and (
            ep is None or ep["clinical_status"] not in ("COMPLETED", "TERMINATED_EARLY")):
        raise ApiError("ERR_EPISODE_NOT_COMPLETED", 422,
                       "FINAL reports require a clinically terminal episode")
    # constraint gate
    if (rec["report_type"] == "FINAL" and ep is not None
            and ep["transmission_count"] == 0
            and not rec["no_significant_findings"]):
        raise ApiError("ERR_EMPTY_MONITORING_DATA", 422,
                       "FINAL with zero transmissions requires no_significant_findings")
    t = now()
    rec["status"] = "FINALIZED"
    rec["finalized_at"] = t
    if rec["report_type"] == "FINAL" and ep is not None and ep["completed_at"] is not None:
        hours = Decimal(str((t - ep["completed_at"]).total_seconds() / 3600.0))
        rec["turnaround_hours"] = float(round_half_up_2(hours))
        rec["sla_met"] = t <= ep["completed_at"] + timedelta(hours=FINAL_SLA_HOURS)
    touch(rec)
    return success(serialize(rec))


@bp.post("/v1/reports/<report_id>/amend")
def amend_report(report_id):
    uid, role = auth()
    require(role, {"Physician"})
    rec = _get_report_or_404(report_id)
    if rec["reading_physician_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Caller is not the reading physician")
    d = body()
    findings_summary = req_str(d, "findings_summary")
    if rec["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only FINALIZED reports can be amended")
    rec["status"] = "AMENDED"
    rec["findings_summary"] = findings_summary
    rec["revision_count"] += 1
    touch(rec)
    return success(serialize(rec))
