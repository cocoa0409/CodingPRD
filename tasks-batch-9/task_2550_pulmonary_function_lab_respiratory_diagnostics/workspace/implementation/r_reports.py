"""Interpretation reports: assignment, turnaround, signing and amendment."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import services as svc
from auth import (authenticate, ALL_ROLES, LAB_MANAGER, INTERPRETING_PHYSICIAN)
from calc import D, num, rnd, trunc_int
from errors import ApiError
from responses import object_response, paginate
from store import db, iso, parse_iso, stamp_new, touch
import validation as v

bp = Blueprint("reports", __name__)


@bp.route("/test-sessions/<session_id>/interpretation-reports",
          methods=["POST"])
def assign_report(session_id):
    authenticate([LAB_MANAGER])
    session = svc.get_session(session_id)
    body = v.get_body()
    expected_version = v.v_int(body, "expected_session_version")
    if expected_version != int(session["version"]):
        raise ApiError("ERR_STALE_SESSION_VERSION",
                       "The study has moved on since it was read.")
    if session["session_status"] != "ACCEPTED":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "Only an ACCEPTED study may be assigned.")
    device = db.devices.get(session["device_id"])
    order = db.orders.get(session["order_id"])
    interpreter = svc.select_interpreter(session, device)

    record = {
        "session_id": session["id"],
        "interpreter_staff_id": interpreter["id"],
        "assigned_at": iso(db.clock),
        "queue_load_pct": None,
        "load_tier": None,
        "sla_minutes": None,
        "due_at": None,
        "signed_at": None,
        "turnaround_minutes": None,
        "sla_breached": None,
        "pattern": None,
        "severity": None,
        "reference_equation_code": session.get("reference_equation_code"),
        "template_version": None,
        "clinical_comment": None,
        "amendment_count": 0,
        "amendment_reason": None,
        "superseded_by_report_id": None,
        "status": "ASSIGNED",
    }
    stamp_new(record)
    svc.adjust_open_reports(interpreter["id"], 1)
    db.reports[record["id"]] = record

    open_count = svc.open_report_total()
    capacity = svc.roster_capacity()
    queue_load = rnd(D(open_count) / D(capacity) * D(100), 2)
    tier = calc.load_tier(queue_load)
    sla_minutes = calc.sla_minutes_for(order["test_context"], tier)
    record["queue_load_pct"] = num(queue_load)
    record["load_tier"] = tier
    record["sla_minutes"] = sla_minutes
    record["due_at"] = iso(parse_iso(record["assigned_at"])
                           + timedelta(minutes=sla_minutes))

    for prior in svc.by_created(list(db.reports.values())):
        if prior["id"] == record["id"]:
            continue
        if prior["session_id"] != session["id"]:
            continue
        if prior["status"] != "ASSIGNED":
            continue
        prior["status"] = "REASSIGNED"
        prior["superseded_by_report_id"] = record["id"]
        touch(prior)
        svc.adjust_open_reports(prior.get("interpreter_staff_id"), -1)

    touch(session)
    return object_response(svc.ser_report(record), 201)


@bp.route("/interpretation-reports/<report_id>", methods=["GET"])
def read_report(report_id):
    authenticate(ALL_ROLES)
    return object_response(svc.ser_report(svc.get_report(report_id)))


@bp.route("/interpretation-reports", methods=["GET"])
def list_reports():
    authenticate(ALL_ROLES)
    session_id = request.args.get("session_id")
    interpreter_staff_id = request.args.get("interpreter_staff_id")
    superseded_by = request.args.get("superseded_by_report_id")
    status = request.args.get("status")
    records = []
    for report in db.reports.values():
        if session_id is not None and report["session_id"] != session_id:
            continue
        if interpreter_staff_id is not None and \
                report["interpreter_staff_id"] != interpreter_staff_id:
            continue
        if superseded_by is not None and \
                report.get("superseded_by_report_id") != superseded_by:
            continue
        if status is not None and report["status"] != status:
            continue
        records.append(report)
    return paginate(records, svc.ser_report)


def _require_interpreter(actor, report):
    if report.get("interpreter_staff_id") != actor.staff_id:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Only the physician named on the report may act on it.")


@bp.route("/interpretation-reports/<report_id>/sign", methods=["POST"])
def sign_report(report_id):
    actor = authenticate([INTERPRETING_PHYSICIAN])
    report = svc.get_report(report_id)
    _require_interpreter(actor, report)
    body = v.get_body()
    comment = v.v_str(body, "clinical_comment")
    if report["status"] not in ("ASSIGNED", "AMENDED"):
        raise ApiError("ERR_REPORT_STATE_INVALID",
                       "Only an ASSIGNED or AMENDED report may be signed.")
    session = db.sessions.get(report["session_id"])
    order = db.orders.get(session["order_id"]) if session else None
    if session is not None and \
            actor.staff_id == session.get("technologist_staff_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The technologist who conducted the study may not "
                       "interpret it.")
    test_context = (order or {}).get("test_context")
    if test_context != "ROUTINE_CLINICAL":
        if session.get("custody_status") != "CUSTODY_SEALED":
            raise ApiError("ERR_CUSTODY_NOT_SEALED",
                           "The custody chain must be CUSTODY_SEALED at "
                           "signing.")
        if test_context == "DISABILITY_EVALUATION":
            witnessed = [e for e in db.custody_events.values()
                         if e["session_id"] == session["id"]
                         and e["event_type"] == "WITNESS_SIGNED"]
            if not witnessed:
                raise ApiError("ERR_WITNESS_ATTESTATION_MISSING",
                               "A witness attestation is required before "
                               "signing a disability report.")

    signed_at = db.clock
    assigned_at = parse_iso(report["assigned_at"])
    due_at = parse_iso(report["due_at"])
    turnaround = trunc_int(D((signed_at - assigned_at).total_seconds())
                           / D(60))
    report["signed_at"] = iso(signed_at)
    report["turnaround_minutes"] = turnaround
    report["sla_breached"] = bool(due_at is not None and signed_at > due_at)
    report["clinical_comment"] = comment
    report["template_version"] = calc.REPORT_TEMPLATE_VERSION
    if session is not None and session.get("fev1_fvc_ratio") is not None \
            and session.get("fvc_pct_predicted") is not None:
        pattern, severity = calc.pattern_and_severity(
            session["fev1_fvc_ratio"], session["ratio_lln"],
            session["fvc_pct_predicted"], session.get("fev1_pct_predicted"))
        report["pattern"] = pattern
        report["severity"] = severity
    report["status"] = "SIGNED"
    touch(report)
    svc.adjust_open_reports(report["interpreter_staff_id"], -1)

    if session is not None and session["session_status"] == "ACCEPTED":
        session["session_status"] = "REPORTED"
        session["turnaround_minutes"] = turnaround
        touch(session)
        if order is not None and order["status"] == "IN_TESTING":
            order["status"] = "COMPLETED"
            touch(order)
            patient = db.patients.get(order["patient_id"])
            if patient is not None:
                patient["completed_order_count"] = int(
                    patient.get("completed_order_count") or 0) + 1
                touch(patient)
    return object_response(svc.ser_report(report), 200)


@bp.route("/interpretation-reports/<report_id>/amend", methods=["POST"])
def amend_report(report_id):
    actor = authenticate([INTERPRETING_PHYSICIAN])
    report = svc.get_report(report_id)
    _require_interpreter(actor, report)
    body = v.get_body()
    reason = v.v_str(body, "amendment_reason")
    if report["status"] != "SIGNED":
        raise ApiError("ERR_REPORT_STATE_INVALID",
                       "Only a SIGNED report may be amended.")
    report["amendment_count"] = int(report.get("amendment_count") or 0) + 1
    report["amendment_reason"] = reason
    report["status"] = "AMENDED"
    touch(report)
    svc.adjust_open_reports(report["interpreter_staff_id"], 1)
    return object_response(svc.ser_report(report), 200)
