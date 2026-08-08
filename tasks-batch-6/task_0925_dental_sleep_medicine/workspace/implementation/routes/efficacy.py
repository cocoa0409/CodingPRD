"""Efficacy reports — the document that closes the cross-provider loop."""

from flask import Blueprint, request

import calc
import domain
import validation as v
from access import (actor, body_refs, gate_device, gate_frozen, in_scope, new_row,
                    path_row, require_identity, require_scope, touch)
from envelope import created, ok
from errors import fail
from serializers import dump
from store import DB, add_days, clock_date

bp = Blueprint("efficacy", __name__)


@bp.post("/efficacy-reports")
def create_report():
    uid, role = actor(["Dentist"])
    body = v.read_body()
    refs = body_refs(body, ["referral_id", "appliance_id", "efficacy_study_id"])
    referral = refs["referral_id"]
    if referral is not None:
        gate_frozen(DB["patients"].get(referral["patient_id"]))
        require_identity(uid, referral["treating_dentist_id"])
    fields = [
        v.S("referral_id", required=True),
        v.S("appliance_id", required=True),
        v.S("efficacy_study_id", required=True),
        v.I("expected_referral_version", required=True),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    appliance = refs["appliance_id"]
    study = refs["efficacy_study_id"]
    if study["study_purpose"] != "EFFICACY":
        fail("ERR_VALIDATION", "efficacy_study_id must name a study of purpose EFFICACY.")
    if study.get("appliance_id") != appliance["id"]:
        fail("ERR_VALIDATION", "The efficacy study must name the appliance under test.")
    if body["expected_referral_version"] != referral["version"]:
        fail("ERR_STALE_VERSION", "expected_referral_version does not match the referral.")
    gate_device(appliance)
    if study["status"] != "DIAGNOSTIC_VALID":
        fail("ERR_STUDY_NON_DIAGNOSTIC", "The efficacy study failed its quality gate.")
    if appliance["lifecycle_status"] not in ("TITRATION_PLATEAU", "EFFICACY_PENDING"):
        fail("ERR_PLATEAU_REQUIRED", "The device must be at plateau or awaiting efficacy.")

    diagnostic = DB["sleep_studies"].get(referral["diagnostic_study_id"])
    patient = DB["patients"].get(referral["patient_id"])
    payer = domain.medical_payer_of(patient)
    residual_target = payer["residual_ahi_target"] if payer else 5.0
    pct_target = payer["pct_reduction_target"] if payer else 0.50
    baseline = diagnostic["severity_index"] if diagnostic else None
    residual = study["severity_index"]
    pct_reduction, meets_absolute, meets_relative, outcome = calc.efficacy_outcome(
        baseline, residual, residual_target, pct_target)

    for older in list(DB["efficacy_reports"].values()):
        if older["referral_id"] == referral["id"] and older["status"] == "DISPUTED":
            older["status"] = "SUPERSEDED"
            touch(older)
            recompute = DB["referrals"].get(older["referral_id"])
            if recompute is not None:
                domain.recompute_loop_count(recompute["referring_physician_id"])

    touch(referral)
    row = new_row("efficacy_reports", {
        "patient_id": referral["patient_id"],
        "referral_id": referral["id"],
        "appliance_id": appliance["id"],
        "efficacy_study_id": study["id"],
        "baseline_index": baseline,
        "residual_index": residual,
        "pct_reduction": pct_reduction,
        "meets_absolute_target": meets_absolute,
        "meets_relative_target": meets_relative,
        "outcome": outcome,
        "due_by": domain.add_days_or_none(appliance.get("plateau_declared_on"),
                                          calc.EFFICACY_REPORT_DUE_DAYS),
        "submitted_on": None,
        "physician_decision_on": None,
        "dispute_reason": None,
        "revision_count": 0,
        "status": "DRAFT",
    })
    return created(dump("efficacy_report", row))


@bp.get("/efficacy-reports/<report_id>")
def read_report(report_id):
    uid, role = actor(["Dentist", "SleepPhysician", "ClinicCoordinator", "PlatformAdmin"])
    row = path_row("report_id", report_id)
    require_scope(role, uid, row["patient_id"])
    return ok(dump("efficacy_report", row))


@bp.get("/efficacy-reports")
def list_reports():
    uid, role = actor(["Dentist", "SleepPhysician", "ClinicCoordinator", "PlatformAdmin"])
    limit, offset = v.pagination()
    filters = {
        "patient_id": request.args.get("patient_id"),
        "referral_id": request.args.get("referral_id"),
        "appliance_id": request.args.get("appliance_id"),
        "efficacy_study_id": request.args.get("efficacy_study_id"),
        "status": request.args.get("status"),
    }
    return domain.paginate("efficacy_report", "efficacy_reports", filters, limit, offset,
                           lambda r: in_scope(role, uid, r["patient_id"]))


@bp.post("/efficacy-reports/<report_id>/submit")
def submit_report(report_id):
    uid, role = actor(["Dentist"])
    report = path_row("report_id", report_id)
    body = v.read_body()
    referral = DB["referrals"].get(report["referral_id"])
    appliance = DB["appliances"].get(report["appliance_id"])
    gate_frozen(DB["patients"].get(report["patient_id"]))
    require_identity(uid, referral["treating_dentist_id"] if referral else None)
    v.rung7(body, [])
    if report["status"] not in ("DRAFT", "SUBMITTED", "DISPUTED"):
        fail("ERR_INVALID_STATE", "This report may no longer be submitted.")
    if report["status"] == "SUBMITTED":
        fail("ERR_INVALID_STATE", "The report has already been submitted.")
    if report["status"] == "DRAFT" and appliance["lifecycle_status"] != "TITRATION_PLATEAU":
        fail("ERR_INVALID_STATE", "A first submission requires the device at plateau.")
    gate_device(appliance)
    study = DB["sleep_studies"].get(report["efficacy_study_id"])
    if study is None or study["status"] != "DIAGNOSTIC_VALID":
        fail("ERR_STUDY_NON_DIAGNOSTIC", "The efficacy study failed its quality gate.")

    first_submission = report["status"] == "DRAFT"
    if not first_submission:
        report["revision_count"] = report["revision_count"] + 1
    report["submitted_on"] = clock_date()
    report["status"] = "SUBMITTED"
    touch(report)
    if first_submission and appliance["lifecycle_status"] == "TITRATION_PLATEAU":
        appliance["lifecycle_status"] = "EFFICACY_PENDING"
        touch(appliance)
    if referral is not None:
        domain.recompute_loop_count(referral["referring_physician_id"])
    return ok(dump("efficacy_report", report))


@bp.post("/efficacy-reports/<report_id>/physician-response")
def physician_response(report_id):
    uid, role = actor(["SleepPhysician"])
    report = path_row("report_id", report_id)
    body = v.read_body()
    referral = DB["referrals"].get(report["referral_id"])
    appliance = DB["appliances"].get(report["appliance_id"])
    gate_frozen(DB["patients"].get(report["patient_id"]))
    if referral is None or uid not in (referral["referring_physician_id"],
                                       referral["treating_dentist_id"]):
        require_scope(role, uid, report["patient_id"])
    fields = [
        v.S("decision", required=True, enum=v.ENUM_REPORT_DECISION),
        v.S("dispute_reason"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if body["decision"] == "DISPUTED" and body.get("dispute_reason") is None:
        fail("ERR_VALIDATION", "dispute_reason is required on a dispute.")
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED report may be answered.")
    gate_device(appliance)
    if uid != referral["referring_physician_id"]:
        fail("ERR_SELF_REFERRAL", "Only the referring physician may answer this report.")

    report["physician_decision_on"] = clock_date()
    if body["decision"] == "SIGNED":
        report["status"] = "SIGNED"
        touch(report)
        referral["status"] = "CLOSED"
        referral["loop_status"] = "CLOSED"
        touch(referral)
        if appliance is not None:
            if appliance["lifecycle_status"] == "EFFICACY_PENDING":
                appliance["lifecycle_status"] = "ACTIVE_THERAPY"
            appliance["recall_status"] = "NOT_DUE"
            appliance["next_recall_due_on"] = add_days(clock_date(), calc.FIRST_RECALL_DAYS)
            touch(appliance)
    else:
        report["status"] = "DISPUTED"
        report["dispute_reason"] = body["dispute_reason"]
        touch(report)
        if appliance is not None and report["outcome"] == "PARTIAL":
            if appliance["lifecycle_status"] == "EFFICACY_PENDING":
                appliance["lifecycle_status"] = "IN_TITRATION"
            appliance["plateau_declared_on"] = None
            touch(appliance)
    domain.recompute_loop_count(referral["referring_physician_id"])
    return ok(dump("efficacy_report", report))
