"""Service ticket endpoints and state transitions."""
from datetime import timedelta
from flask import Blueprint, request

import errors
from db import store, new_id, now_iso, parse_iso
from middleware import require_auth, require_role
from response import success_object, success_list
from services import serialize, domain
from services.validate import (get_json_body, reject_unknown_fields, require_fields,
                               as_string, as_bool, as_number, as_int, as_enum,
                               as_iso8601, check_range, parse_pagination)

bp = Blueprint("tickets", __name__)

JOB_TYPES = {"DIAGNOSIS", "CLEANOUT", "INSPECTION", "RETROFIT_AERATION", "RETROFIT_VIBRATOR"}
BUFFER = timedelta(hours=2)


@bp.route("/service-tickets", methods=["POST"])
def create_ticket():
    ctx = require_auth()
    body = get_json_body()
    allowed = {"site_id", "vessel_id", "job_type", "requires_entry", "est_hours",
               "crew_size", "description"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["site_id", "vessel_id", "job_type", "requires_entry",
                          "est_hours", "crew_size"])
    site_id = as_string(body["site_id"], "site_id")
    vessel_id = as_string(body["vessel_id"], "vessel_id")
    job_type = as_enum(body["job_type"], "job_type", JOB_TYPES)
    requires_entry = as_bool(body["requires_entry"], "requires_entry")
    est_hours = as_number(body["est_hours"], "est_hours")
    check_range(est_hours, "est_hours", 0, None, min_exclusive=True)
    crew_size = as_int(body["crew_size"], "crew_size")
    if crew_size < 1:
        raise errors.validation("crew_size must be >= 1")
    description = ""
    if "description" in body:
        description = as_string(body["description"], "description")

    require_role(ctx, {"PlantOperator", "ServiceManager"})

    site = store.sites.get(site_id)
    if site is None:
        raise errors.not_found(errors.ERR_SITE_NOT_FOUND, "Site not found")
    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")

    if ctx.role == "PlantOperator" and ctx.user_id != site_id:
        raise errors.forbidden("PlantOperator may only open tickets for its own site")

    ts = now_iso()
    ticket = {
        "id": new_id(),
        "site_id": site_id,
        "vessel_id": vessel_id,
        "technician_id": None,
        "source_permit_id": None,
        "job_type": job_type,
        "requires_entry": requires_entry,
        "est_hours": est_hours,
        "crew_size": crew_size,
        "description": description,
        "status": "DRAFT",
        "estimate_cents": None,
        "commercial_track": None,
        "window_start": None,
        "window_end": None,
        "actual_hours": None,
        "mileage_miles": None,
        "disposal_tons": None,
        "invoice_labor_cents": None,
        "invoice_mobilization_cents": None,
        "invoice_disposal_cents": None,
        "invoice_subtotal_cents": None,
        "invoice_discount_cents": None,
        "invoice_tax_cents": None,
        "invoice_total_cents": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    ticket["estimate_cents"] = domain.compute_estimate_cents(ticket, v, site)
    store.service_tickets[ticket["id"]] = ticket
    return success_object(serialize.serialize_ticket(ticket), status=201)


@bp.route("/service-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    require_auth()
    t = store.service_tickets.get(ticket_id)
    if t is None:
        raise errors.not_found(errors.ERR_TICKET_NOT_FOUND, "Ticket not found")
    return success_object(serialize.serialize_ticket(t))


@bp.route("/service-tickets", methods=["GET"])
def list_tickets():
    require_auth()
    limit, offset = parse_pagination()
    site_id = request.args.get("site_id")
    vessel_id = request.args.get("vessel_id")
    technician_id = request.args.get("technician_id")
    source_permit_id = request.args.get("source_permit_id")
    status = request.args.get("status")
    tickets = list(store.service_tickets.values())
    if site_id is not None:
        tickets = [t for t in tickets if t["site_id"] == site_id]
    if vessel_id is not None:
        tickets = [t for t in tickets if t["vessel_id"] == vessel_id]
    if technician_id is not None:
        tickets = [t for t in tickets if t.get("technician_id") == technician_id]
    if source_permit_id is not None:
        tickets = [t for t in tickets if t.get("source_permit_id") == source_permit_id]
    if status is not None:
        tickets = [t for t in tickets if t["status"] == status]
    tickets.sort(key=lambda t: t["created_at"])
    total = len(tickets)
    page = tickets[offset:offset + limit]
    return success_list([serialize.serialize_ticket(t) for t in page],
                        limit=limit, offset=offset, total_count=total)


def _get_ticket_or_404(ticket_id):
    t = store.service_tickets.get(ticket_id)
    if t is None:
        raise errors.not_found(errors.ERR_TICKET_NOT_FOUND, "Ticket not found")
    return t


@bp.route("/service-tickets/<ticket_id>/quote", methods=["POST"])
def quote_ticket(ticket_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, set())
    require_role(ctx, {"ServiceManager"})
    t = _get_ticket_or_404(ticket_id)
    if t["status"] != "DRAFT":
        raise errors.conflict(errors.ERR_INVALID_TICKET_STATE,
                              "Ticket must be DRAFT to quote")
    site = store.sites.get(t["site_id"])
    threshold = site.get("capital_threshold_cents", 500000) if site else 500000
    t["commercial_track"] = ("CAPITAL_PROJECT" if t["estimate_cents"] >= threshold
                             else "CONTRACT_SERVICE")
    t["status"] = "QUOTED"
    t["updated_at"] = now_iso()
    t["version"] = t["version"] + 1
    return success_object(serialize.serialize_ticket(t))


@bp.route("/service-tickets/<ticket_id>/approve", methods=["POST"])
def approve_ticket(ticket_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, set())
    require_role(ctx, {"PlantOperator", "ServiceManager"})
    t = _get_ticket_or_404(ticket_id)
    if t["status"] != "QUOTED":
        raise errors.conflict(errors.ERR_INVALID_TICKET_STATE,
                              "Ticket must be QUOTED to approve")
    # Approve role must match commercial_track.
    if t["commercial_track"] == "CONTRACT_SERVICE":
        # owning PlantOperator approves
        if ctx.role != "PlantOperator" or ctx.user_id != t["site_id"]:
            raise errors.forbidden(
                "CONTRACT_SERVICE track requires the owning PlantOperator")
    else:  # CAPITAL_PROJECT
        if ctx.role != "ServiceManager":
            raise errors.forbidden(
                "CAPITAL_PROJECT track requires a ServiceManager")
    t["status"] = "APPROVED"
    t["updated_at"] = now_iso()
    t["version"] = t["version"] + 1
    return success_object(serialize.serialize_ticket(t))


@bp.route("/service-tickets/<ticket_id>/decline", methods=["POST"])
def decline_ticket(ticket_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, set())
    require_role(ctx, {"PlantOperator"})
    t = _get_ticket_or_404(ticket_id)
    if ctx.user_id != t["site_id"]:
        raise errors.forbidden("PlantOperator may only decline tickets for its own site")
    if t["status"] != "QUOTED":
        raise errors.conflict(errors.ERR_INVALID_TICKET_STATE,
                              "Ticket must be QUOTED to decline")
    t["status"] = "DECLINED"
    t["updated_at"] = now_iso()
    t["version"] = t["version"] + 1
    return success_object(serialize.serialize_ticket(t))


def _check_technician_double_booking(technician_id: str, new_start, new_end, exclude_ticket_id=None):
    """Half-open overlap with another SCHEDULED/IN_PROGRESS/ON_HOLD ticket for this tech."""
    for t in store.service_tickets.values():
        if t.get("technician_id") != technician_id:
            continue
        if t["status"] not in ("SCHEDULED", "IN_PROGRESS", "ON_HOLD"):
            continue
        if exclude_ticket_id is not None and t["id"] == exclude_ticket_id:
            continue
        ws = t.get("window_start")
        we = t.get("window_end")
        if not ws or not we:
            continue
        ws_dt = parse_iso(ws)
        we_dt = parse_iso(we)
        # half-open overlap: [ws, we) intersects [new_start, new_end)
        if ws_dt < new_end and new_start < we_dt:
            return True
    return False


def _check_vessel_downtime_buffer(vessel_id: str, new_start, new_end, exclude_ticket_id=None):
    """2-hour buffer against other occupied downtime intervals on the same vessel.

    Excludes intervals that share this ticket's id (or, for permits, intervals whose
    ticket_id == this ticket's id)."""
    # Other tickets' occupied windows
    for t in store.service_tickets.values():
        if t["vessel_id"] != vessel_id:
            continue
        if t["status"] not in ("SCHEDULED", "IN_PROGRESS", "ON_HOLD"):
            continue
        if exclude_ticket_id is not None and t["id"] == exclude_ticket_id:
            continue
        ws = t.get("window_start")
        we = t.get("window_end")
        if not ws or not we:
            continue
        ws_dt = parse_iso(ws)
        we_dt = parse_iso(we)
        # gap on both sides >= 2h  =>  new_end + 2h <= ws  OR  we + 2h <= new_start
        if not (new_end + BUFFER <= ws_dt or we_dt + BUFFER <= new_start):
            return True
    # Permit windows with status DRAFT/ISSUED/ACTIVE/SUSPENDED
    for p in store.entry_permits.values():
        if p["vessel_id"] != vessel_id:
            continue
        if p["status"] not in ("DRAFT", "ISSUED", "ACTIVE", "SUSPENDED"):
            continue
        # Exempt intervals that share this ticket's id.
        if exclude_ticket_id is not None and p.get("ticket_id") == exclude_ticket_id:
            continue
        ws_dt = parse_iso(p["window_start"])
        we_dt = parse_iso(p["window_end"])
        if not (new_end + BUFFER <= ws_dt or we_dt + BUFFER <= new_start):
            return True
    return False


@bp.route("/service-tickets/<ticket_id>/schedule", methods=["POST"])
def schedule_ticket(ticket_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"technician_id", "window_start", "window_end"})
    require_fields(body, ["technician_id", "window_start", "window_end"])
    technician_id = as_string(body["technician_id"], "technician_id")
    window_start = as_iso8601(body["window_start"], "window_start")
    window_end = as_iso8601(body["window_end"], "window_end")
    ws_dt = parse_iso(window_start)
    we_dt = parse_iso(window_end)
    if not (we_dt > ws_dt):
        raise errors.validation("window_end must be strictly after window_start")

    require_role(ctx, {"ServiceManager"})
    t = _get_ticket_or_404(ticket_id)

    tech = store.technicians.get(technician_id)
    if tech is None:
        raise errors.not_found(errors.ERR_TECHNICIAN_NOT_FOUND, "Technician not found")
    if not tech.get("active", True):
        raise errors.validation("Technician is not active")

    if t["status"] != "APPROVED":
        raise errors.conflict(errors.ERR_INVALID_TICKET_STATE,
                              "Ticket must be APPROVED to schedule")

    # Window strictly in the future relative to logical clock.
    if not (ws_dt > store.logical_clock):
        raise errors.conflict(errors.ERR_WINDOW_IN_PAST,
                              "window_start is not strictly after the current logical clock")

    if _check_technician_double_booking(technician_id, ws_dt, we_dt, exclude_ticket_id=t["id"]):
        raise errors.conflict(errors.ERR_TECHNICIAN_DOUBLE_BOOKED,
                              "Technician already occupies an overlapping window")

    if _check_vessel_downtime_buffer(t["vessel_id"], ws_dt, we_dt, exclude_ticket_id=t["id"]):
        raise errors.conflict(errors.ERR_VESSEL_DOWNTIME_CONFLICT,
                              "Vessel downtime buffer violation (2 hours)")

    site = store.sites.get(t["site_id"])
    if site is not None and site.get("credit_hold", False):
        raise errors.conflict(errors.ERR_CREDIT_HOLD,
                              "Site is on credit hold")

    t["technician_id"] = technician_id
    t["window_start"] = window_start
    t["window_end"] = window_end
    t["status"] = "SCHEDULED"
    t["updated_at"] = now_iso()
    t["version"] = t["version"] + 1
    return success_object(serialize.serialize_ticket(t))


@bp.route("/service-tickets/<ticket_id>/start", methods=["POST"])
def start_ticket(ticket_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, set())
    require_role(ctx, {"Technician"})
    t = _get_ticket_or_404(ticket_id)
    if ctx.user_id != t.get("technician_id"):
        raise errors.forbidden("Acting technician must equal ticket.technician_id")
    if t["status"] != "SCHEDULED":
        raise errors.conflict(errors.ERR_INVALID_TICKET_STATE,
                              "Ticket must be SCHEDULED to start")
    if t.get("requires_entry"):
        active_permit = any(
            p.get("ticket_id") == t["id"] and p["status"] == "ACTIVE"
            for p in store.entry_permits.values()
        )
        if not active_permit:
            raise errors.conflict(errors.ERR_ENTRY_PERMIT_REQUIRED,
                                  "An ACTIVE EntryPermit is required to start")
    t["status"] = "IN_PROGRESS"
    t["updated_at"] = now_iso()
    t["version"] = t["version"] + 1
    return success_object(serialize.serialize_ticket(t))


@bp.route("/service-tickets/<ticket_id>/complete", methods=["POST"])
def complete_ticket(ticket_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"actual_hours", "mileage_miles", "disposal_tons"})
    require_fields(body, ["actual_hours", "mileage_miles", "disposal_tons"])
    actual_hours = as_number(body["actual_hours"], "actual_hours")
    check_range(actual_hours, "actual_hours", 0, None, min_exclusive=True)
    mileage = as_number(body["mileage_miles"], "mileage_miles")
    check_range(mileage, "mileage_miles", 0, None)
    disposal = as_number(body["disposal_tons"], "disposal_tons")
    check_range(disposal, "disposal_tons", 0, None)

    require_role(ctx, {"Technician"})
    t = _get_ticket_or_404(ticket_id)
    if ctx.user_id != t.get("technician_id"):
        raise errors.forbidden("Acting technician must equal ticket.technician_id")
    if t["status"] != "IN_PROGRESS":
        raise errors.conflict(errors.ERR_INVALID_TICKET_STATE,
                              "Ticket must be IN_PROGRESS to complete")

    site = store.sites.get(t["site_id"])
    invoice = domain.compute_invoice(t, site or {}, actual_hours, mileage, disposal)
    t.update(invoice)
    t["actual_hours"] = actual_hours
    t["mileage_miles"] = mileage
    t["disposal_tons"] = disposal
    t["status"] = "COMPLETED"
    t["updated_at"] = now_iso()
    t["version"] = t["version"] + 1
    return success_object(serialize.serialize_ticket(t))
