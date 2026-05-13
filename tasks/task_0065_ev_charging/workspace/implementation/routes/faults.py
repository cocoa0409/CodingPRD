"""Fault report and repair ticket endpoints."""

from flask import Blueprint, g

import db
from clock import now_iso
from errors import raise_error
from middleware import require_roles
from response import success
from services import audit, pile_service, queue_service
from validators import (
    check_version,
    parse_json_body,
    require_enum,
    require_str,
)


bp = Blueprint("faults", __name__)


VALID_REPORTER_KINDS = {"USER", "AUTO_DETECT"}
VALID_SEVERITY = {"MINOR", "MAJOR", "CRITICAL"}


@bp.post("/fault-reports")
@require_roles({"EVDriver", "FieldTechnician", "PlatformOperator"})
def create_fault_report():
    body = parse_json_body()
    pile_id = require_str(body, "pile_id")
    if pile_id not in db.piles:
        raise_error("ERR_NOT_FOUND", "pile not found")
    reporter_kind = require_enum(body, "reporter_kind", VALID_REPORTER_KINDS)
    reporter_member_id = body.get("reporter_member_id")
    if reporter_kind == "USER":
        if not reporter_member_id:
            raise_error("ERR_VALIDATION", "reporter_member_id required for USER reporter_kind")
        if reporter_member_id not in db.members:
            raise_error("ERR_NOT_FOUND", "reporter_member_id not found")
    else:
        reporter_member_id = None
    symptom_code = require_str(body, "symptom_code", 1, 40)
    severity = require_enum(body, "severity", VALID_SEVERITY)

    record = {
        "pile_id": pile_id,
        "reporter_kind": reporter_kind,
        "reporter_member_id": reporter_member_id,
        "symptom_code": symptom_code,
        "severity": severity,
        "status": "OPEN",
    }
    db.with_common_fields(record)
    db.fault_reports[record["id"]] = record

    audit.write(
        actor_role=g.role,
        actor_id=g.user_id,
        entity_kind="FaultReport",
        entity_id=record["id"],
        event_kind="FAULT_EVENT",
        payload={"reason": "fault_report_created", "severity": severity},
    )

    # CRITICAL fault auto-isolates.
    if severity == "CRITICAL":
        record["status"] = "ISOLATED"
        db.bump(record)
        pile = db.piles[pile_id]
        if pile["lifecycle_state"] == "ON_SHELF":
            pile_service.cascade_fault(pile, g.role, g.user_id)
        audit.write(
            actor_role=g.role,
            actor_id=g.user_id,
            entity_kind="FaultReport",
            entity_id=record["id"],
            event_kind="FAULT_EVENT",
            payload={"reason": "auto_isolate_critical"},
        )

    return success(db.public(record), status=201)


@bp.post("/fault-reports/<report_id>/isolate")
@require_roles({"FieldTechnician", "PlatformOperator"})
def isolate_fault(report_id: str):
    report = db.fault_reports.get(report_id)
    if report is None:
        raise_error("ERR_NOT_FOUND", "fault report not found")
    body = parse_json_body()
    check_version(body, report)

    if report["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "fault report not OPEN")

    report["status"] = "ISOLATED"
    db.bump(report)

    pile = db.piles[report["pile_id"]]
    if pile["lifecycle_state"] == "ON_SHELF":
        pile_service.cascade_fault(pile, g.role, g.user_id)

    audit.write(
        actor_role=g.role,
        actor_id=g.user_id,
        entity_kind="FaultReport",
        entity_id=report["id"],
        event_kind="FAULT_EVENT",
        payload={"reason": "manual_isolate"},
    )
    return success(db.public(report))


@bp.get("/fault-reports/<report_id>")
@require_roles({"FieldTechnician", "PlatformOperator", "StationOwner", "CustomerService"})
def get_fault_report(report_id: str):
    report = db.fault_reports.get(report_id)
    if report is None:
        raise_error("ERR_NOT_FOUND", "fault report not found")
    if g.role == "StationOwner":
        pile = db.piles.get(report["pile_id"])
        station = db.stations.get(pile["station_id"]) if pile else None
        if station is None or station["station_owner_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "not your station's fault report")
    return success(db.public(report))


@bp.post("/fault-reports/<report_id>/repair-tickets")
@require_roles({"PlatformOperator"})
def open_repair_ticket(report_id: str):
    report = db.fault_reports.get(report_id)
    if report is None:
        raise_error("ERR_NOT_FOUND", "fault report not found")
    body = parse_json_body()
    technician_id = require_str(body, "assigned_technician_id")
    record = {
        "fault_report_id": report_id,
        "assigned_technician_id": technician_id,
        "dispatched_at": None,
        "repair_notes": "",
        "status": "OPEN",
    }
    db.with_common_fields(record)
    db.repair_tickets[record["id"]] = record
    return success(db.public(record), status=201)


@bp.post("/repair-tickets/<ticket_id>/dispatch")
@require_roles({"PlatformOperator"})
def dispatch_ticket(ticket_id: str):
    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise_error("ERR_NOT_FOUND", "repair ticket not found")
    body = parse_json_body()
    check_version(body, ticket)
    report = db.fault_reports.get(ticket["fault_report_id"])
    if report is None:
        raise_error("ERR_NOT_FOUND", "parent fault report not found")
    if ticket["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "ticket not OPEN")
    if report["status"] not in {"OPEN", "ISOLATED"}:
        raise_error("ERR_INVALID_STATE", "fault report not in OPEN/ISOLATED")
    ticket["status"] = "DISPATCHED"
    ticket["dispatched_at"] = now_iso()
    db.bump(ticket)

    # Cascade isolation if fault was OPEN.
    if report["status"] == "OPEN":
        report["status"] = "ISOLATED"
        db.bump(report)
        pile = db.piles[report["pile_id"]]
        if pile["lifecycle_state"] == "ON_SHELF":
            pile_service.cascade_fault(pile, g.role, g.user_id)
        audit.write(
            actor_role=g.role,
            actor_id=g.user_id,
            entity_kind="FaultReport",
            entity_id=report["id"],
            event_kind="FAULT_EVENT",
            payload={"reason": "dispatch_cascade_isolate"},
        )

    return success(db.public(ticket))


@bp.post("/repair-tickets/<ticket_id>/begin")
@require_roles({"FieldTechnician"})
def begin_ticket(ticket_id: str):
    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise_error("ERR_NOT_FOUND", "repair ticket not found")
    body = parse_json_body()
    check_version(body, ticket)
    if ticket["status"] != "DISPATCHED":
        raise_error("ERR_INVALID_STATE", "ticket not DISPATCHED")
    if ticket["assigned_technician_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not the assigned technician")
    ticket["status"] = "IN_REPAIR"
    db.bump(ticket)
    return success(db.public(ticket))


@bp.post("/repair-tickets/<ticket_id>/complete")
@require_roles({"FieldTechnician"})
def complete_ticket(ticket_id: str):
    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise_error("ERR_NOT_FOUND", "repair ticket not found")
    body = parse_json_body()
    check_version(body, ticket)
    repair_notes = body.get("repair_notes", "")
    if not isinstance(repair_notes, str) or len(repair_notes) > 1000:
        raise_error("ERR_VALIDATION", "repair_notes must be string up to 1000 chars")
    if ticket["status"] != "IN_REPAIR":
        raise_error("ERR_INVALID_STATE", "ticket not IN_REPAIR")
    if ticket["assigned_technician_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not the assigned technician")
    ticket["status"] = "AWAITING_ACCEPTANCE"
    ticket["repair_notes"] = repair_notes
    db.bump(ticket)
    return success(db.public(ticket))


@bp.post("/repair-tickets/<ticket_id>/accept")
@require_roles({"StationOwner"})
def accept_ticket(ticket_id: str):
    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise_error("ERR_NOT_FOUND", "repair ticket not found")
    body = parse_json_body()
    check_version(body, ticket)
    report = db.fault_reports.get(ticket["fault_report_id"])
    if report is None:
        raise_error("ERR_NOT_FOUND", "parent fault report not found")
    pile = db.piles[report["pile_id"]]
    station = db.stations[pile["station_id"]]
    if station["station_owner_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not the station owner")
    if ticket["status"] != "AWAITING_ACCEPTANCE":
        raise_error("ERR_INVALID_STATE", "ticket not AWAITING_ACCEPTANCE")

    ticket["status"] = "CLOSED"
    db.bump(ticket)
    report["status"] = "RESOLVED"
    db.bump(report)

    if pile["lifecycle_state"] == "ON_SHELF":
        pile["operational_state"] = "IDLE"
        db.bump(pile)
        queue_service.promote_if_possible(station["id"])

    audit.write(
        actor_role=g.role,
        actor_id=g.user_id,
        entity_kind="FaultReport",
        entity_id=report["id"],
        event_kind="FAULT_EVENT",
        payload={"reason": "resolved"},
    )
    return success(db.public(ticket))


@bp.post("/repair-tickets/<ticket_id>/reject")
@require_roles({"StationOwner"})
def reject_ticket(ticket_id: str):
    ticket = db.repair_tickets.get(ticket_id)
    if ticket is None:
        raise_error("ERR_NOT_FOUND", "repair ticket not found")
    body = parse_json_body()
    check_version(body, ticket)
    report = db.fault_reports.get(ticket["fault_report_id"])
    if report is None:
        raise_error("ERR_NOT_FOUND", "parent fault report not found")
    pile = db.piles[report["pile_id"]]
    station = db.stations[pile["station_id"]]
    if station["station_owner_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not the station owner")
    if ticket["status"] != "AWAITING_ACCEPTANCE":
        raise_error("ERR_INVALID_STATE", "ticket not AWAITING_ACCEPTANCE")
    ticket["status"] = "IN_REPAIR"
    db.bump(ticket)
    return success(db.public(ticket))
