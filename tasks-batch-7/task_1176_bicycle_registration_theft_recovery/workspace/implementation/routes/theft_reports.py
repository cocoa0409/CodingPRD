"""Theft reports and the registrar review loop (PRD §3.4)."""
from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import theft_report_view
from response import list_response, ok_object
from routes.common import field, load

bp = Blueprint("theft_reports", __name__)

OPEN_REPORT_STATES = {"UNDER_REVIEW", "NEEDS_INFO", "FLAGGED"}


@bp.post("/registry/theft-reports")
@require_roles("Owner")
def create_theft_report():
    data = body()
    bicycle_id = field(data, "bicycle_id", "string", required=True)
    occurred_at = field(data, "occurred_at", "datetime", required=True)
    theft_location = field(data, "theft_location", "string", required=True)
    police_case_number = field(data, "police_case_number", "string", required=False, nullable=True)
    description = field(data, "description", "string", required=False, nullable=True)

    bicycle = load(db.bicycles, bicycle_id, "ERR_BICYCLE_NOT_FOUND")
    if bicycle["current_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the bicycle's owner may report it stolen")
    if bicycle["integrity_status"] == "MERGED":
        fail("ERR_BICYCLE_MERGED", "Merged bicycles accept no further operations")
    if any(r["bicycle_id"] == bicycle_id and r["status"] in OPEN_REPORT_STATES
           for r in db.theft_reports.values()):
        fail("ERR_REPORT_ALREADY_OPEN", "A non-terminal theft report already exists for this bicycle")

    rec = db.new_record({
        "bicycle_id": bicycle_id,
        "owner_id": g.user_id,
        "occurred_at": occurred_at,
        "theft_location": theft_location,
        "police_case_number": police_case_number,
        "description": description,
        "status": "UNDER_REVIEW",
        "info_request_text": None,
        "response_text": None,
        "reason_text": None,
        "flagged_at": None,
    })
    db.theft_reports[rec["id"]] = rec
    return ok_object(theft_report_view(rec), status=201)


@bp.get("/registry/theft-reports")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def list_theft_reports():
    recs = list(db.theft_reports.values())
    if g.role == "Owner":
        recs = [r for r in recs if r["owner_id"] == g.user_id]
    elif g.role == "Partner":
        # Partners see only FLAGGED reports (the actionable stolen-registry feed).
        recs = [r for r in recs if r["status"] == "FLAGGED"]
    for param, key in (("bicycle_id", "bicycle_id"), ("owner_id", "owner_id"),
                       ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [r for r in recs if r[key] == value]
    return list_response(recs, theft_report_view)


@bp.get("/registry/theft-reports/<report_id>")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def read_theft_report(report_id):
    rec = load(db.theft_reports, report_id, "ERR_THEFT_REPORT_NOT_FOUND")
    if g.role == "Owner" and rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may read only their own reports")
    if g.role == "Partner" and rec["status"] != "FLAGGED":
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Partners may read only FLAGGED reports")
    return ok_object(theft_report_view(rec))


@bp.post("/registry/theft-reports/<report_id>/request-info")
@require_roles("Registrar")
def request_info(report_id):
    info_request_text = field(body(), "info_request_text", "string", required=True)
    rec = load(db.theft_reports, report_id, "ERR_THEFT_REPORT_NOT_FOUND")
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_THEFT_REPORT_NOT_ACTIONABLE", "Report is not under review")
    rec["info_request_text"] = info_request_text
    rec["status"] = "NEEDS_INFO"
    db.bump(rec)
    return ok_object(theft_report_view(rec))


@bp.post("/registry/theft-reports/<report_id>/respond")
@require_roles("Owner")
def respond(report_id):
    response_text = field(body(), "response_text", "string", required=True)
    rec = load(db.theft_reports, report_id, "ERR_THEFT_REPORT_NOT_FOUND")
    if rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the report's owner may respond")
    if rec["status"] != "NEEDS_INFO":
        fail("ERR_THEFT_REPORT_NOT_ACTIONABLE", "Report is not awaiting information")
    rec["response_text"] = response_text
    rec["status"] = "UNDER_REVIEW"
    db.bump(rec)
    return ok_object(theft_report_view(rec))


@bp.post("/registry/theft-reports/<report_id>/flag")
@require_roles("Registrar")
def flag_report(report_id):
    rec = load(db.theft_reports, report_id, "ERR_THEFT_REPORT_NOT_FOUND")
    bicycle = db.bicycles.get(rec["bicycle_id"])
    # Stage 9 merge guard precedes the stage-10 from-state check.
    if bicycle is not None and bicycle["integrity_status"] == "MERGED":
        fail("ERR_BICYCLE_MERGED", "Merged bicycles accept no further operations")
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_THEFT_REPORT_NOT_ACTIONABLE", "Report is not under review")

    rec["status"] = "FLAGGED"
    rec["flagged_at"] = db.now()
    db.bump(rec)

    # Cascade: bicycle REGISTERED -> STOLEN; pending transfers force-cancelled
    # with TRANSFER_CANCELLED_STOLEN to each buyer; REPORT_FLAGGED to the owner.
    if bicycle is not None:
        bicycle["registry_status"] = "STOLEN"
        db.bump(bicycle)
        for t in db.transfers.values():
            if t["bicycle_id"] == bicycle["id"] and t["status"] == "PENDING_ACCEPTANCE":
                t["status"] = "CANCELLED"
                db.bump(t)
                db.notify(t["to_owner_id"], "TRANSFER_CANCELLED_STOLEN",
                          "A pending transfer was cancelled because the bicycle was reported stolen.",
                          related_entity_type="OwnershipTransfer", related_entity_id=t["id"])
        db.notify(bicycle["current_owner_id"], "REPORT_FLAGGED",
                  "Your theft report has been flagged in the registry.",
                  related_entity_type="TheftReport", related_entity_id=rec["id"])
    return ok_object(theft_report_view(rec))


@bp.post("/registry/theft-reports/<report_id>/reject")
@require_roles("Registrar")
def reject_report(report_id):
    reason_text = field(body(), "reason_text", "string", required=True)
    rec = load(db.theft_reports, report_id, "ERR_THEFT_REPORT_NOT_FOUND")
    if rec["status"] not in ("UNDER_REVIEW", "NEEDS_INFO"):
        fail("ERR_THEFT_REPORT_NOT_ACTIONABLE", "Report cannot be rejected from its state")
    rec["reason_text"] = reason_text
    rec["status"] = "REJECTED"
    db.bump(rec)
    return ok_object(theft_report_view(rec))


@bp.post("/registry/theft-reports/<report_id>/withdraw")
@require_roles("Owner")
def withdraw_report(report_id):
    rec = load(db.theft_reports, report_id, "ERR_THEFT_REPORT_NOT_FOUND")
    if rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the report's owner may withdraw it")

    if rec["status"] in ("UNDER_REVIEW", "NEEDS_INFO"):
        rec["status"] = "WITHDRAWN"
        db.bump(rec)
        return ok_object(theft_report_view(rec))

    if rec["status"] == "FLAGGED":
        # Permitted only while no match on this report stands CONFIRMED.
        if any(m["theft_report_id"] == rec["id"] and m["status"] == "CONFIRMED"
               for m in db.matches.values()):
            fail("ERR_THEFT_REPORT_NOT_ACTIONABLE",
                 "A confirmed match exists; the report cannot be withdrawn")
        rec["status"] = "WITHDRAWN"
        db.bump(rec)
        # Unwind the flag: bicycle STOLEN -> REGISTERED; open matches EXPIRED.
        bicycle = db.bicycles.get(rec["bicycle_id"])
        if bicycle is not None and bicycle["registry_status"] == "STOLEN":
            bicycle["registry_status"] = "REGISTERED"
            db.bump(bicycle)
        for m in db.matches.values():
            if m["theft_report_id"] == rec["id"] and m["status"] in ("PROPOSED", "NOTIFIED"):
                m["status"] = "EXPIRED"
                db.bump(m)
        return ok_object(theft_report_view(rec))

    fail("ERR_THEFT_REPORT_NOT_ACTIONABLE", "Report cannot be withdrawn from its state")
