"""MonitoringAlert lifecycle (PRD §3.8) and SubprocessorDisclosure lifecycle
(PRD §3.9). Alert escalation pulls the reassessment due date forward and
opens a fresh DRAFT cycle; subprocessor decisions are segregated from the
review starter.
"""
from datetime import timedelta

from flask import Blueprint, g, request

import calc
import db
import errors
import helpers
import sweeps
import util
from errors import ApiError
from middleware import (body, paginate, require_roles, scope_vendor_or_403)
from response import ok, ok_list
from serializers import serialize

bp = Blueprint("monitoring", __name__, url_prefix="/vsa/vendors/<vid>")

SIGNALS = ("BREACH_REPORT", "CERT_LAPSE", "FINANCIAL_DISTRESS",
           "NEGATIVE_NEWS", "SCAN_FINDING")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
SUBPROCESSOR_APPROVE_POSTURES = ("APPROVED", "CONDITIONAL", "ASSESSING")
FILING_BLOCKED_POSTURES = ("OFFBOARDING", "OFFBOARDED")


def _resolve_alert(vid, aid):
    vendor = helpers.get_vendor(vid)
    alert = helpers.get_vendor_child(db.alerts, vendor, aid, "MonitoringAlert")
    return vendor, alert


@bp.post("/monitoring-alerts")
@require_roles("PlatformAdmin")
def create_alert(vid):
    vendor = helpers.get_vendor(vid)
    data = body()
    signal = data.get("signal")
    severity = data.get("severity")
    detected_at = data.get("detected_at")
    if signal not in SIGNALS:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "signal must be one of %s" % (SIGNALS,))
    if severity not in SEVERITIES:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "severity must be one of %s" % (SEVERITIES,))
    if not util.is_dt(detected_at):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "detected_at must be an ISO 8601 datetime")
    alert = {
        "vendor_id": vid,
        "signal": signal,
        "severity": severity,
        "detected_at": util.iso(util.parse_dt(detected_at)),
        "status": "OPEN",
        "disposition": None,
    }
    helpers.stamp_new("alerts", alert)
    db.alerts[alert["id"]] = alert
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)
    return ok(serialize("alert", alert), 201)


@bp.get("/monitoring-alerts")
@require_roles("RiskAnalyst", "SecurityApprover", "PlatformAdmin")
def list_alerts(vid):
    helpers.get_vendor(vid)
    items = [a for a in db.alerts.values() if a["vendor_id"] == vid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("alert", a) for a in page], limit, offset, total)


@bp.post("/monitoring-alerts/<aid>/acknowledge")
@require_roles("RiskAnalyst")
def acknowledge_alert(vid, aid):
    vendor, alert = _resolve_alert(vid, aid)
    if alert["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only an OPEN alert can be acknowledged")
    disposition = body().get("disposition")
    if disposition is not None:
        if not isinstance(disposition, str):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "disposition must be a string")
        alert["disposition"] = disposition
    alert["status"] = "ACKNOWLEDGED"
    helpers.touch("alerts", alert)
    return ok(serialize("alert", alert))


@bp.post("/monitoring-alerts/<aid>/dismiss")
@require_roles("RiskAnalyst")
def dismiss_alert(vid, aid):
    vendor, alert = _resolve_alert(vid, aid)
    if alert["status"] != "ACKNOWLEDGED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only an ACKNOWLEDGED alert can be dismissed")
    disposition = body().get("disposition")
    if not isinstance(disposition, str) or not disposition:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "disposition must be non-empty")
    alert["disposition"] = disposition
    alert["status"] = "DISMISSED"
    helpers.touch("alerts", alert)
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)
    return ok(serialize("alert", alert))


@bp.post("/monitoring-alerts/<aid>/escalate")
@require_roles("RiskAnalyst")
def escalate_alert(vid, aid):
    vendor, alert = _resolve_alert(vid, aid)
    if alert["status"] != "ACKNOWLEDGED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only an ACKNOWLEDGED alert can be escalated")
    # Escalatability (priority 20): severity + posture gate.
    if alert["severity"] not in ("HIGH", "CRITICAL") \
            or vendor["posture"] not in ("APPROVED", "CONDITIONAL"):
        raise ApiError(errors.ERR_ALERT_NOT_ESCALATABLE, 422,
                       "Escalation requires severity HIGH/CRITICAL and vendor "
                       "posture APPROVED or CONDITIONAL")
    disposition = body().get("disposition")
    if disposition is not None:
        if not isinstance(disposition, str):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "disposition must be a string")
        alert["disposition"] = disposition
    alert["status"] = "ESCALATED"
    now = util.now()
    delta = (calc.DELTA_CRITICAL_DAYS if alert["severity"] == "CRITICAL"
             else calc.DELTA_HIGH_DAYS)
    previous_due = (util.parse_dt(vendor["next_reassessment_due"])
                    if vendor.get("next_reassessment_due") else None)
    new_due = calc.pull_forward(previous_due, now + timedelta(days=delta))
    vendor["next_reassessment_due"] = util.iso(new_due)
    helpers.append_schedule(vid, "ALERT_ESCALATION", previous_due, new_due,
                            alert["id"])
    vendor["posture"] = "ASSESSING"
    cycle = sweeps.make_draft_cycle(vendor)
    vendor["active_cycle_id"] = cycle["id"]
    helpers.touch("alerts", alert)
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)
    return ok(serialize("alert", alert))


# ------------------------- subprocessors -------------------------------------

def _resolve_subprocessor(vid, sid):
    vendor = helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    sub = helpers.get_vendor_child(db.subprocessors, vendor, sid,
                                   "SubprocessorDisclosure")
    return vendor, sub


@bp.post("/subprocessors")
@require_roles("VendorContact")
def create_subprocessor(vid):
    vendor = helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    if vendor["posture"] in FILING_BLOCKED_POSTURES:
        raise ApiError(errors.ERR_VENDOR_POSTURE_BLOCKS, 422,
                       "Vendor posture %s does not permit new disclosures"
                       % vendor["posture"])
    data = body()
    name = data.get("subprocessor_name")
    categories = data.get("data_categories")
    region = data.get("region")
    if not isinstance(name, str) or not name:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "subprocessor_name is required")
    if not isinstance(categories, list):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "data_categories must be a list")
    if not isinstance(region, str) or not region:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "region is required")
    sub = {
        "vendor_id": vid,
        "subprocessor_name": name,
        "data_categories": categories,
        "region": region,
        "status": "DISCLOSED",
        "decided_by": None,
        "_review_started_by": None,
    }
    helpers.stamp_new("subprocessors", sub)
    db.subprocessors[sub["id"]] = sub
    return ok(serialize("subprocessor", sub), 201)


@bp.get("/subprocessors")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_subprocessors(vid):
    helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    items = [s for s in db.subprocessors.values() if s["vendor_id"] == vid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("subprocessor", s) for s in page],
                   limit, offset, total)


@bp.post("/subprocessors/<sid>/start-review")
@require_roles("RiskAnalyst")
def start_subprocessor_review(vid, sid):
    vendor, sub = _resolve_subprocessor(vid, sid)
    if sub["status"] != "DISCLOSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a DISCLOSED disclosure can enter review")
    sub["status"] = "UNDER_REVIEW"
    sub["_review_started_by"] = g.user_id
    helpers.touch("subprocessors", sub)
    return ok(serialize("subprocessor", sub))


@bp.post("/subprocessors/<sid>/approve")
@require_roles("SecurityApprover")
def approve_subprocessor(vid, sid):
    vendor, sub = _resolve_subprocessor(vid, sid)
    if sub["status"] != "UNDER_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only an UNDER_REVIEW disclosure can be approved")
    # Segregation of duties: approver != the analyst who started the review.
    if g.user_id == sub.get("_review_started_by"):
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 422,
                       "Subprocessor approver must differ from the review starter")
    if vendor["posture"] not in SUBPROCESSOR_APPROVE_POSTURES:
        raise ApiError(errors.ERR_VENDOR_POSTURE_BLOCKS, 422,
                       "Vendor posture %s does not permit subprocessor approval"
                       % vendor["posture"])
    sub["status"] = "APPROVED"
    sub["decided_by"] = g.user_id
    helpers.touch("subprocessors", sub)
    return ok(serialize("subprocessor", sub))


@bp.post("/subprocessors/<sid>/reject")
@require_roles("SecurityApprover")
def reject_subprocessor(vid, sid):
    vendor, sub = _resolve_subprocessor(vid, sid)
    if sub["status"] != "UNDER_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only an UNDER_REVIEW disclosure can be rejected")
    sub["status"] = "REJECTED"
    sub["decided_by"] = g.user_id
    helpers.touch("subprocessors", sub)
    return ok(serialize("subprocessor", sub))


@bp.post("/subprocessors/<sid>/withdraw")
@require_roles("VendorContact")
def withdraw_subprocessor(vid, sid):
    vendor, sub = _resolve_subprocessor(vid, sid)
    if sub["status"] != "DISCLOSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a DISCLOSED disclosure can be withdrawn")
    sub["status"] = "WITHDRAWN"
    helpers.touch("subprocessors", sub)
    return ok(serialize("subprocessor", sub))
