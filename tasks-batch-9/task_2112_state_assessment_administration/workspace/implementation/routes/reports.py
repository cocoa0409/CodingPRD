"""Irregularity reports, the return-for-information loop and adjudication
(PRD 3.7)."""

from flask import Blueprint, request

import serialize
from cascades import invalidate_session, refresh_report_window, revoke_proctor_for_breach
from db import create, db, now, ordered, touch
from derive import MAX_RETURN_CYCLES, window_of_report
from errors import api_error
from middleware import (
    ALL_ROLES,
    PROCTOR,
    STATE_OFFICER,
    body_reference,
    endpoint,
    json_body,
    report_transition_guard,
    require_scope,
    resolve,
)
from response import object_response, paginate
from validators import (
    enum_field,
    identifier_field,
    nullable_identifier,
    optional_text,
    string_field,
)

bp = Blueprint("reports", __name__)

CATEGORIES = {"ADMIN_ERROR", "SECURITY_BREACH", "TECH_FAILURE", "STUDENT_MISCONDUCT"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
REPORT_TO_STATUS = {"SUBMITTED", "WITHDRAWN", "UNDER_REVIEW", "RETURNED_FOR_INFO", "ADJUDICATED"}
DISPOSITIONS = {"DISMISSED", "INVALIDATE_REGISTRATION", "INVALIDATE_SESSION", "BREACH_CONFIRMED"}

DECLARED_EDGES = {
    ("DRAFT", "SUBMITTED"),
    ("DRAFT", "WITHDRAWN"),
    ("SUBMITTED", "UNDER_REVIEW"),
    ("UNDER_REVIEW", "RETURNED_FOR_INFO"),
    ("RETURNED_FOR_INFO", "SUBMITTED"),
    ("UNDER_REVIEW", "ADJUDICATED"),
}

INVALIDATABLE_REGISTRATION_STATUSES = ("SCORED", "RELEASED", "UNDER_APPEAL", "CORRECTED")


@bp.post("/irregularity-reports")
@endpoint(PROCTOR)
def file_report(actor):
    # Check 4 — a proctor files against the session being run.
    named_session = body_reference("session_id")
    scoped_session = db.sessions.get(named_session) if named_session else None
    if scoped_session is not None:
        require_scope(scoped_session["proctor_id"] == actor.user_id)

    body = json_body()
    session_id = identifier_field(body, "session_id")
    registration_id = nullable_identifier(body, "registration_id")
    category = enum_field(body, "category", CATEGORIES)
    severity = enum_field(body, "severity", SEVERITIES)
    narrative = string_field(body, "narrative", min_length=1, max_length=2000)

    resolve(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")
    if registration_id is not None:
        resolve(db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND")

    report = create(
        db.reports,
        {
            "session_id": session_id,
            "registration_id": registration_id,
            "reporter_proctor_id": actor.user_id,
            "material_lot_id": None,
            "category": category,
            "severity": severity,
            "narrative": narrative,
            "status": "DRAFT",
            "disposition": None,
            "return_count": 0,
            "adjudicated_at": None,
            "system_generated": False,
        },
    )
    return object_response(serialize.report(report), 201)


@bp.get("/irregularity-reports/<irregularity_report_id>")
@endpoint(*ALL_ROLES)
def read_report(actor, irregularity_report_id):
    report = resolve(db.reports, irregularity_report_id, "ERR_IRREGULARITY_REPORT_NOT_FOUND")
    return object_response(serialize.report(report))


@bp.get("/irregularity-reports")
@endpoint(*ALL_ROLES)
def list_reports(actor):
    session_id = request.args.get("session_id")
    registration_id = request.args.get("registration_id")
    reporter_proctor_id = request.args.get("reporter_proctor_id")
    material_lot_id = request.args.get("material_lot_id")
    status = request.args.get("status")
    category = request.args.get("category")
    items = [
        report
        for report in db.reports.values()
        if (session_id is None or report["session_id"] == session_id)
        and (registration_id is None or report["registration_id"] == registration_id)
        and (reporter_proctor_id is None or report["reporter_proctor_id"] == reporter_proctor_id)
        and (material_lot_id is None or report["material_lot_id"] == material_lot_id)
        and (status is None or report["status"] == status)
        and (category is None or report["category"] == category)
    ]
    return paginate(ordered(items), serialize.report)


@bp.post("/irregularity-reports/<irregularity_report_id>/transitions")
@endpoint(PROCTOR, STATE_OFFICER, sub_operation=report_transition_guard)
def transition_report(actor, irregularity_report_id):
    report = resolve(db.reports, irregularity_report_id, "ERR_IRREGULARITY_REPORT_NOT_FOUND")
    if actor.role == PROCTOR:
        require_scope(report["reporter_proctor_id"] == actor.user_id)

    body = json_body()
    to_status = enum_field(body, "to_status", REPORT_TO_STATUS)
    disposition = enum_field(body, "disposition", DISPOSITIONS, required=False)
    optional_text(body, "note")
    if to_status == "ADJUDICATED" and disposition is None:
        raise api_error("ERR_INVALID_REQUEST", "disposition is required when adjudicating.")

    if (report["status"], to_status) not in DECLARED_EDGES:
        raise api_error("ERR_INVALID_STATE_TRANSITION")

    if to_status == "RETURNED_FOR_INFO":
        _return_for_info(report)
    elif to_status == "ADJUDICATED":
        _adjudicate(report, disposition)
    else:
        report["status"] = to_status
        touch(report)
        refresh_report_window(report)
    return object_response(serialize.report(report))


def _return_for_info(report):
    if report["system_generated"]:
        raise api_error(
            "ERR_INVALID_STATE_TRANSITION",
            "a system-generated report has no filer to return it to.",
        )
    if report["return_count"] >= MAX_RETURN_CYCLES:
        raise api_error("ERR_RETURN_CYCLE_LIMIT")
    report["status"] = "RETURNED_FOR_INFO"
    report["return_count"] += 1
    touch(report)
    refresh_report_window(report)


def _adjudicate(report, disposition):
    session = db.sessions.get(report["session_id"]) if report["session_id"] else None
    registration = (
        db.registrations.get(report["registration_id"]) if report["registration_id"] else None
    )
    window = window_of_report(report)

    if disposition == "INVALIDATE_REGISTRATION":
        if registration is None:
            raise api_error("ERR_INVALID_STATE_TRANSITION", "the report names no registration.")
        if window is not None and window["status"] == "FINALIZED":
            raise api_error("ERR_INVALID_STATE_TRANSITION", "the window is already finalized.")
        if registration["score_status"] not in INVALIDATABLE_REGISTRATION_STATUSES:
            raise api_error(
                "ERR_INVALID_STATE_TRANSITION",
                "the registration has no score to invalidate.",
            )
    elif disposition == "INVALIDATE_SESSION":
        if session is None:
            raise api_error("ERR_INVALID_STATE_TRANSITION", "the report names no session.")
        if session["status"] != "CLOSED":
            raise api_error("ERR_INVALID_STATE_TRANSITION", "the named session is not closed.")
        if window is not None and window["status"] == "FINALIZED":
            raise api_error("ERR_INVALID_STATE_TRANSITION", "the window is already finalized.")
    elif disposition == "BREACH_CONFIRMED":
        if session is None:
            raise api_error("ERR_INVALID_STATE_TRANSITION", "the report names no session.")
        if session["proctor_id"] is None:
            raise api_error("ERR_INVALID_STATE_TRANSITION", "the named session has no proctor.")

    report["status"] = "ADJUDICATED"
    report["disposition"] = disposition
    report["adjudicated_at"] = now()
    touch(report)

    if disposition == "DISMISSED":
        from cascades import reverse_lot_charge

        if report["material_lot_id"]:
            reverse_lot_charge(report)
    elif disposition == "INVALIDATE_REGISTRATION":
        registration["score_status"] = "INVALIDATED"
        touch(registration)
    elif disposition == "INVALIDATE_SESSION":
        invalidate_session(session)
    elif disposition == "BREACH_CONFIRMED":
        revoke_proctor_for_breach(session)

    refresh_report_window(report)
