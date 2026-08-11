"""Logical clock, RepairEvent lifecycle, EventReport generation and reads."""

from decimal import Decimal

from flask import Blueprint

import db
import serializers as ser
import services
from errors import (
    ERR_CLOCK_REGRESSION,
    ERR_EVENT_HAS_NO_STATIONS,
    ERR_EVENT_NOT_CLOSABLE,
    ERR_EVENT_NOT_FOUND,
    ERR_INVALID_EVENT_STATE,
    ERR_ITEMS_IN_FLIGHT,
    ERR_NO_OPEN_STATION,
    ERR_REPORT_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_roles
from response import success
from util import as_dt, as_int, as_str, body, list_response, req

bp = Blueprint("events", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")


def get_event_or_404(event_id):
    event = db.events.get(event_id)
    if event is None:
        raise_err(ERR_EVENT_NOT_FOUND, "RepairEvent %s does not exist" % event_id)
    return event


# ------------------------------------------------------------------ clock ---

@bp.post("/api/_clock/set_current_utc")
@require_roles("Coordinator")
def set_clock():
    b = body()
    raw = as_dt(req(b, "to_iso8601"), "to_iso8601")
    new_value = db.parse_dt(raw)
    if new_value < db.clock.current:
        raise_err(ERR_CLOCK_REGRESSION, "Logical clock may not move backwards")
    db.clock.current = new_value
    return success({}, 200)


# ----------------------------------------------------------------- events ---

@bp.post("/api/repair-events")
@require_roles("Coordinator")
def create_event():
    b = body()
    name = as_str(req(b, "name"), "name", required_len=True)
    starts_at = as_dt(req(b, "starts_at"), "starts_at")
    ends_at = as_dt(req(b, "ends_at"), "ends_at")
    if db.parse_dt(ends_at) <= db.parse_dt(starts_at):
        raise_err(ERR_VALIDATION, "ends_at must be after starts_at")
    cap = as_int(req(b, "intake_item_cap"), "intake_item_cap", lo=1)
    rec = db.stamp_new(
        {
            "name": name,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "intake_item_cap": cap,
            "status": "DRAFT",
        }
    )
    db.events[rec["id"]] = rec
    return success(ser.event(rec), 201)


@bp.get("/api/repair-events")
@require_roles(*ALL_ROLES)
def list_events():
    return list_response(db.events.values(), ser.event, [("status", "status")])


@bp.get("/api/repair-events/<event_id>")
@require_roles(*ALL_ROLES)
def get_event(event_id):
    return success(ser.event(get_event_or_404(event_id)), 200)


@bp.post("/api/repair-events/<event_id>/publish")
@require_roles("Coordinator")
def publish_event(event_id):
    event = get_event_or_404(event_id)
    if event["status"] != "DRAFT":
        raise_err(ERR_INVALID_EVENT_STATE, "Only a DRAFT event can be published")
    if not services.stations_of(event["id"]):
        raise_err(ERR_EVENT_HAS_NO_STATIONS, "Event has no stations")
    event["status"] = "PUBLISHED"
    db.touch(event)
    return success(ser.event(event), 200)


@bp.post("/api/repair-events/<event_id>/open-intake")
@require_roles("Coordinator")
def open_intake(event_id):
    event = get_event_or_404(event_id)
    if event["status"] != "PUBLISHED":
        raise_err(ERR_INVALID_EVENT_STATE, "Only a PUBLISHED event can open intake")
    if not any(s["status"] == "OPEN" for s in services.stations_of(event["id"])):
        raise_err(ERR_NO_OPEN_STATION, "No station of this event is OPEN")
    event["status"] = "INTAKE_OPEN"
    db.touch(event)
    return success(ser.event(event), 200)


@bp.post("/api/repair-events/<event_id>/close-intake")
@require_roles("Coordinator")
def close_intake(event_id):
    event = get_event_or_404(event_id)
    if event["status"] != "INTAKE_OPEN":
        raise_err(ERR_INVALID_EVENT_STATE, "Only an INTAKE_OPEN event can close intake")
    for it in services.items_of_event(event["id"]):
        if it["status"] in ("ASSIGNED", "IN_REPAIR"):
            raise_err(ERR_ITEMS_IN_FLIGHT, "Items are assigned or in repair")
    event["status"] = "PUBLISHED"
    db.touch(event)
    return success(ser.event(event), 200)


@bp.post("/api/repair-events/<event_id>/begin-repairs")
@require_roles("Coordinator")
def begin_repairs(event_id):
    event = get_event_or_404(event_id)
    if event["status"] != "INTAKE_OPEN":
        raise_err(ERR_INVALID_EVENT_STATE, "Only an INTAKE_OPEN event can begin repairs")
    event["status"] = "REPAIR_ACTIVE"
    db.touch(event)
    return success(ser.event(event), 200)


@bp.post("/api/repair-events/<event_id>/close")
@require_roles("Coordinator")
def close_event(event_id):
    event = get_event_or_404(event_id)
    if event["status"] != "REPAIR_ACTIVE":
        raise_err(ERR_INVALID_EVENT_STATE, "Only a REPAIR_ACTIVE event can be closed")
    for it in services.items_of_event(event["id"]):
        if it["status"] not in services.ITEM_TERMINAL:
            raise_err(ERR_EVENT_NOT_CLOSABLE, "Event has non-terminal repair items")
    services.event_close_sweep(event)
    event["status"] = "CLOSED"
    db.touch(event)
    return success(ser.event(event), 200)


@bp.post("/api/repair-events/<event_id>/cancel")
@require_roles("Coordinator")
def cancel_event(event_id):
    event = get_event_or_404(event_id)
    if event["status"] in ("REPORTED", "CANCELLED"):
        raise_err(ERR_INVALID_EVENT_STATE, "A terminal event cannot be cancelled")
    services.event_cancel_cascade(event)
    event["status"] = "CANCELLED"
    db.touch(event)
    return success(ser.event(event), 200)


@bp.post("/api/repair-events/<event_id>/report")
@require_roles("Coordinator")
def report_event(event_id):
    event = get_event_or_404(event_id)
    if event["status"] != "CLOSED":
        raise_err(ERR_INVALID_EVENT_STATE, "Only a CLOSED event can be reported")
    for r in db.reports.values():
        if r["event_id"] == event["id"]:
            raise_err(ERR_INVALID_EVENT_STATE, "Event already has a report")

    verified = []
    for o in db.outcomes.values():
        if o["verification_status"] != "VERIFIED":
            continue
        it = db.items.get(o["item_id"])
        if it is not None and it["event_id"] == event["id"]:
            verified.append(o)
    items_total = len(verified)
    items_fixed = sum(1 for o in verified if o["outcome"] == "FIXED")
    items_partial = sum(1 for o in verified if o["outcome"] == "PARTIALLY_FIXED")
    items_not_rep = sum(1 for o in verified if o["outcome"] == "NOT_REPAIRABLE")
    if items_total == 0:
        strict = 0.0
        lenient = 0.0
    else:
        total = Decimal(items_total)
        strict = services.rate_out(Decimal(items_fixed) / total)
        lenient = services.rate_out(
            (Decimal(items_fixed) + Decimal("0.5") * Decimal(items_partial)) / total
        )

    donations_receipt_total = 0
    donations_campaign_total = 0
    for d in db.donations.values():
        if d["event_id"] != event["id"]:
            continue
        if d["status"] == "RECEIPTED":
            donations_receipt_total += d["receipt_value_cents"]
        if d["status"] in ("RECEIVED", "RECEIPTED"):
            donations_campaign_total += d["campaign_value_cents"]

    rec = db.stamp_new(
        {
            "event_id": event["id"],
            "generated_at": db.clock.now_iso(),
            "items_total": items_total,
            "items_fixed": items_fixed,
            "items_partially_fixed": items_partial,
            "items_not_repairable": items_not_rep,
            "success_rate_strict": strict,
            "success_rate_lenient": lenient,
            "diversion_kg_verified": services.kg_out(
                services.diversion_kg(event["id"], {"VERIFIED"})
            ),
            "diversion_kg_projected": services.kg_out(
                services.diversion_kg(event["id"], {"VERIFIED", "RECORDED"})
            ),
            "parts_cost_total_cents": services.committed_parts_cost_event(event["id"]),
            "donations_receipt_total_cents": donations_receipt_total,
            "donations_campaign_total_cents": donations_campaign_total,
        },
        with_version=False,
    )
    db.reports[rec["id"]] = rec
    event["status"] = "REPORTED"
    db.touch(event)
    return success(ser.report(rec), 201)


# ------------------------------------------------------------- reports ----

@bp.get("/api/event-reports")
@require_roles(*ALL_ROLES)
def list_reports():
    return list_response(db.reports.values(), ser.report, [("event_id", "event_id")])


@bp.get("/api/event-reports/<report_id>")
@require_roles(*ALL_ROLES)
def get_report(report_id):
    rec = db.reports.get(report_id)
    if rec is None:
        raise_err(ERR_REPORT_NOT_FOUND, "EventReport %s does not exist" % report_id)
    return success(ser.report(rec), 200)
