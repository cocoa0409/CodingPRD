"""RecallCampaign + RecallRemediation routes, plus standalone read endpoints."""
from flask import Blueprint, request

import calc
import db
import posture
from auth import get_principal, require_roles
from clock import get_now, to_iso8601
from errors import err
from response import success
from serialize import out
from timeutil import add_months, parse
from datetime import timedelta
from validate import get_body, opt_int, require_enum, require_str
from routes.common import find_or_404, ref_or_404, render_list

bp = Blueprint("recall", __name__)


# ---- Campaign create -------------------------------------------------------
@bp.route("/recall-campaigns", methods=["POST"])
def create_campaign():
    principal = get_principal()
    require_roles(principal, {"ComplianceOfficer"})
    body = get_body()
    model_id = require_str(body, "model_id")
    code = require_str(body, "code")
    severity = require_enum(body, "severity", {"ADVISORY", "MANDATORY"})
    remediation_window_days = opt_int(body, "remediation_window_days", default=90)
    if remediation_window_days <= 0:
        raise err("ERR_INVALID_REQUEST", "remediation_window_days must be > 0")

    # FK reference
    ref_or_404(db.models, model_id)

    for c in db.recall_campaigns.values():
        if c["code"] == code:
            raise err("ERR_DUPLICATE_RECALL_CODE", "Recall code already exists")

    rec = db.base_record(full_common=True)
    rec.update({
        "model_id": model_id,
        "code": code,
        "severity": severity,
        "status": "DRAFT",
        "opened_at": None,
        "remediation_window_days": remediation_window_days,
        "affected_unit_count": 0,
        "remediated_count": 0,
    })
    db.recall_campaigns[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/recall-campaigns", methods=["GET"])
def list_campaigns():
    principal = get_principal()
    require_roles(principal, {"ServiceManager", "ComplianceOfficer"})
    records = list(db.recall_campaigns.values())
    if "model_id" in request.args:
        records = [r for r in records if r["model_id"] == request.args.get("model_id")]
    return render_list(records)


@bp.route("/recall-campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.recall_campaigns, campaign_id)
    return success(out(rec), status=200)


# ---- Campaign open: fan out remediations ----------------------------------
@bp.route("/recall-campaigns/<campaign_id>/open", methods=["POST"])
def open_campaign(campaign_id):
    principal = get_principal()
    require_roles(principal, {"ComplianceOfficer"})
    campaign = find_or_404(db.recall_campaigns, campaign_id)
    if campaign["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Campaign must be DRAFT to open")

    opened_at = get_now()
    campaign["opened_at"] = to_iso8601(opened_at)
    deadline = opened_at + timedelta(days=campaign["remediation_window_days"])
    deadline_iso = to_iso8601(deadline)

    affected = 0
    touched_units = []
    for unit in db.units.values():
        if unit["model_id"] != campaign["model_id"]:
            continue
        if unit["operating_status"] == "DECOMMISSIONED":
            continue
        # Units only exist via activation, so every Unit is ACTIVATED-derived.
        rem = db.base_record(full_common=True)
        rem.update({
            "campaign_id": campaign_id,
            "unit_id": unit["id"],
            "deadline_at": deadline_iso,
            "status": "PENDING",
            "dispatch_id": None,
            "completed_at": None,
        })
        db.recall_remediations[rem["id"]] = rem
        affected += 1
        touched_units.append(unit)

    campaign["affected_unit_count"] = affected
    campaign["status"] = "OPEN"
    db.touch(campaign)
    for unit in touched_units:
        posture.recompute_unit_posture(unit)
    return success(out(campaign), status=200)


# ---- Campaign close --------------------------------------------------------
@bp.route("/recall-campaigns/<campaign_id>/close", methods=["POST"])
def close_campaign(campaign_id):
    principal = get_principal()
    require_roles(principal, {"ComplianceOfficer"})
    campaign = find_or_404(db.recall_campaigns, campaign_id)
    if campaign["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Campaign must be OPEN to close")
    for rem in db.recall_remediations.values():
        if rem["campaign_id"] == campaign_id and rem["status"] in ("PENDING", "SCHEDULED"):
            raise err("ERR_CAMPAIGN_HAS_OPEN_REMEDIATIONS", "Open remediations remain")
    campaign["status"] = "CLOSED"
    db.touch(campaign)
    return success(out(campaign), status=200)


@bp.route("/recall-campaigns/<campaign_id>/remediations", methods=["GET"])
def list_campaign_remediations(campaign_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager", "ComplianceOfficer"})
    find_or_404(db.recall_campaigns, campaign_id)
    records = [r for r in db.recall_remediations.values() if r["campaign_id"] == campaign_id]
    return render_list(records)


# ---- Remediation read + schedule ------------------------------------------
@bp.route("/recall-remediations", methods=["GET"])
def list_remediations():
    principal = get_principal()
    require_roles(principal, {"ServiceManager", "ComplianceOfficer"})
    records = list(db.recall_remediations.values())
    for f in ("campaign_id", "unit_id", "dispatch_id"):
        if f in request.args:
            val = request.args.get(f)
            records = [r for r in records if r.get(f) == val]
    return render_list(records)


@bp.route("/recall-remediations/<remediation_id>", methods=["GET"])
def get_remediation(remediation_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.recall_remediations, remediation_id)
    return success(out(rec), status=200)


@bp.route("/recall-remediations/<remediation_id>/schedule", methods=["POST"])
def schedule_remediation(remediation_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    rem = find_or_404(db.recall_remediations, remediation_id)
    unit = db.units.get(rem["unit_id"])

    if rem["status"] == "OVERDUE":
        raise err("ERR_REMEDIATION_OVERDUE", "Cannot schedule an overdue remediation")
    if rem["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Remediation must be PENDING to schedule")
    if unit["operating_status"] == "DECOMMISSIONED":
        raise err("ERR_INVALID_STATE", "Owning unit is decommissioned")

    # spawn a RECALL-origin dispatch in REQUESTED
    dispatch = db.base_record(full_common=True)
    dispatch.update({
        "unit_id": unit["id"],
        "origin": "RECALL",
        "warranty_claim_id": None,
        "assigned_tech_id": None,
        "status": "REQUESTED",
        "labor_cents": 0,
        "parts_cents": 0,
        "billable": False,
        "invoice_total_cents": 0,
        "resolved_by_tech_id": None,
        "runtime_added_hours": 0,
    })
    db.repair_dispatches[dispatch["id"]] = dispatch

    rem["status"] = "SCHEDULED"
    rem["dispatch_id"] = dispatch["id"]
    db.touch(rem)
    return success(out(rem), status=200)


# ---- Standalone read endpoints (load-assessments, exercise-logs) ----------
@bp.route("/load-assessments", methods=["GET"])
def list_assessments():
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    records = list(db.load_assessments.values())
    if "project_id" in request.args:
        records = [r for r in records if r["project_id"] == request.args.get("project_id")]
    return render_list(records)


@bp.route("/load-assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.load_assessments, assessment_id)
    return success(out(rec), status=200)


@bp.route("/exercise-logs", methods=["GET"])
def list_exercise_logs():
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    records = list(db.exercise_logs.values())
    if "unit_id" in request.args:
        records = [r for r in records if r["unit_id"] == request.args.get("unit_id")]
    return render_list(records)


@bp.route("/exercise-logs/<log_id>", methods=["GET"])
def get_exercise_log(log_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.exercise_logs, log_id)
    return success(out(rec), status=200)
