"""Entry permit endpoints, atmosphere control, and bound-ticket cascade."""
from flask import Blueprint, request

import errors
from db import store, new_id, now_iso, parse_iso
from middleware import require_auth, require_role
from response import success_object, success_list
from services import serialize, domain
from services.validate import (get_json_body, reject_unknown_fields, require_fields,
                               as_string, as_bool, as_number, as_iso8601,
                               check_range, parse_pagination)
from routes.tickets import _check_vessel_downtime_buffer

bp = Blueprint("permits", __name__)


@bp.route("/entry-permits", methods=["POST"])
def create_permit():
    ctx = require_auth()
    body = get_json_body()
    allowed = {"vessel_id", "ticket_id", "entrant_technician_id",
               "window_start", "window_end"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["vessel_id", "ticket_id", "entrant_technician_id",
                          "window_start", "window_end"])
    vessel_id = as_string(body["vessel_id"], "vessel_id")
    ticket_id = as_string(body["ticket_id"], "ticket_id")
    entrant_technician_id = as_string(body["entrant_technician_id"], "entrant_technician_id")
    window_start = as_iso8601(body["window_start"], "window_start")
    window_end = as_iso8601(body["window_end"], "window_end")
    ws_dt = parse_iso(window_start)
    we_dt = parse_iso(window_end)
    if not (we_dt > ws_dt):
        raise errors.validation("window_end must be strictly after window_start")

    require_role(ctx, {"SafetyOfficer"})

    v = store.vessels.get(vessel_id)
    if v is None:
        raise errors.not_found(errors.ERR_VESSEL_NOT_FOUND, "Vessel not found")
    t = store.service_tickets.get(ticket_id)
    if t is None:
        raise errors.not_found(errors.ERR_TICKET_NOT_FOUND, "Ticket not found")
    tech = store.technicians.get(entrant_technician_id)
    if tech is None:
        raise errors.not_found(errors.ERR_TECHNICIAN_NOT_FOUND, "Technician not found")

    # The permit's window joins the vessel downtime calendar (2-hour buffer),
    # exempting intervals that share this ticket_id.
    if _check_vessel_downtime_buffer(vessel_id, ws_dt, we_dt, exclude_ticket_id=ticket_id):
        raise errors.conflict(errors.ERR_VESSEL_DOWNTIME_CONFLICT,
                              "Vessel downtime buffer violation (2 hours)")

    ts = now_iso()
    p = {
        "id": new_id(),
        "vessel_id": vessel_id,
        "ticket_id": ticket_id,
        "entrant_technician_id": entrant_technician_id,
        "issuer_user_id": None,
        "window_start": window_start,
        "window_end": window_end,
        "lockout_checklist_confirmed": False,
        "atmosphere_ok": None,
        "last_oxygen_pct": None,
        "last_combustible_pct": None,
        "status": "DRAFT",
        "void_reason": "NONE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.entry_permits[p["id"]] = p
    return success_object(serialize.serialize_permit(p), status=201)


@bp.route("/entry-permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    require_auth()
    p = store.entry_permits.get(permit_id)
    if p is None:
        raise errors.not_found(errors.ERR_PERMIT_NOT_FOUND, "Permit not found")
    return success_object(serialize.serialize_permit(p))


@bp.route("/entry-permits", methods=["GET"])
def list_permits():
    require_auth()
    limit, offset = parse_pagination()
    vessel_id = request.args.get("vessel_id")
    ticket_id = request.args.get("ticket_id")
    entrant_technician_id = request.args.get("entrant_technician_id")
    status = request.args.get("status")
    permits = list(store.entry_permits.values())
    if vessel_id is not None:
        permits = [p for p in permits if p["vessel_id"] == vessel_id]
    if ticket_id is not None:
        permits = [p for p in permits if p["ticket_id"] == ticket_id]
    if entrant_technician_id is not None:
        permits = [p for p in permits if p["entrant_technician_id"] == entrant_technician_id]
    if status is not None:
        permits = [p for p in permits if p["status"] == status]
    permits.sort(key=lambda p: p["created_at"])
    total = len(permits)
    page = permits[offset:offset + limit]
    return success_list([serialize.serialize_permit(p) for p in page],
                        limit=limit, offset=offset, total_count=total)


def _get_permit_or_404(permit_id):
    p = store.entry_permits.get(permit_id)
    if p is None:
        raise errors.not_found(errors.ERR_PERMIT_NOT_FOUND, "Permit not found")
    return p


@bp.route("/entry-permits/<permit_id>/issue", methods=["POST"])
def issue_permit(permit_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"lockout_checklist_confirmed"})
    require_fields(body, ["lockout_checklist_confirmed"])
    lockout = as_bool(body["lockout_checklist_confirmed"], "lockout_checklist_confirmed")

    require_role(ctx, {"SafetyOfficer"})
    p = _get_permit_or_404(permit_id)
    if p["status"] != "DRAFT":
        raise errors.conflict(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be DRAFT to issue")

    # Bin-entry safety cluster, per §2.10 ordering: lockout -> SoD -> engulfment.
    if not lockout:
        raise errors.conflict(errors.ERR_LOCKOUT_NOT_VERIFIED,
                              "Lockout checklist must be confirmed")
    if ctx.user_id == p["entrant_technician_id"]:
        raise errors.conflict(errors.ERR_SOD_ISSUER_EQUALS_ENTRANT,
                              "Issuer must differ from entrant (segregation of duties)")
    inbound_dispatched = any(
        o["vessel_id"] == p["vessel_id"] and o["status"] == "DISPATCHED"
        for o in store.replenishment_orders.values()
    )
    if inbound_dispatched:
        raise errors.conflict(errors.ERR_INBOUND_DELIVERY_PENDING,
                              "A DISPATCHED inbound order exists for the vessel")

    p["status"] = "ISSUED"
    p["issuer_user_id"] = ctx.user_id
    p["lockout_checklist_confirmed"] = True
    p["updated_at"] = now_iso()
    p["version"] = p["version"] + 1
    return success_object(serialize.serialize_permit(p))


@bp.route("/entry-permits/<permit_id>/activate", methods=["POST"])
def activate_permit(permit_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"oxygen_pct", "combustible_pct"})
    require_fields(body, ["oxygen_pct", "combustible_pct"])
    oxygen_pct = as_number(body["oxygen_pct"], "oxygen_pct")
    check_range(oxygen_pct, "oxygen_pct", 0, 100)
    combustible_pct = as_number(body["combustible_pct"], "combustible_pct")
    check_range(combustible_pct, "combustible_pct", 0, 100)

    require_role(ctx, {"SafetyOfficer"})
    p = _get_permit_or_404(permit_id)
    if p["status"] != "ISSUED":
        raise errors.conflict(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be ISSUED to activate")

    if not domain.atmosphere_passes(oxygen_pct, combustible_pct):
        raise errors.conflict(errors.ERR_ATMOSPHERE_UNSAFE,
                              "Atmosphere outside pass limits")

    p["status"] = "ACTIVE"
    p["atmosphere_ok"] = True
    p["last_oxygen_pct"] = oxygen_pct
    p["last_combustible_pct"] = combustible_pct
    p["updated_at"] = now_iso()
    p["version"] = p["version"] + 1
    return success_object(serialize.serialize_permit(p))


def _cascade_ticket_on_suspend(permit):
    """ACTIVE->SUSPENDED cascade: bound IN_PROGRESS ticket -> ON_HOLD."""
    t = store.service_tickets.get(permit["ticket_id"])
    if t is not None and t["status"] == "IN_PROGRESS":
        t["status"] = "ON_HOLD"
        t["updated_at"] = now_iso()
        t["version"] = t["version"] + 1


def _cascade_ticket_on_resume(permit):
    """SUSPENDED->ACTIVE cascade: bound ON_HOLD ticket -> IN_PROGRESS."""
    t = store.service_tickets.get(permit["ticket_id"])
    if t is not None and t["status"] == "ON_HOLD":
        t["status"] = "IN_PROGRESS"
        t["updated_at"] = now_iso()
        t["version"] = t["version"] + 1


@bp.route("/entry-permits/<permit_id>/atmosphere-check", methods=["POST"])
def atmosphere_check(permit_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"oxygen_pct", "combustible_pct"})
    require_fields(body, ["oxygen_pct", "combustible_pct"])
    oxygen_pct = as_number(body["oxygen_pct"], "oxygen_pct")
    check_range(oxygen_pct, "oxygen_pct", 0, 100)
    combustible_pct = as_number(body["combustible_pct"], "combustible_pct")
    check_range(combustible_pct, "combustible_pct", 0, 100)

    require_role(ctx, {"SafetyOfficer", "Technician"})
    p = _get_permit_or_404(permit_id)
    if p["status"] != "ACTIVE":
        raise errors.conflict(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be ACTIVE for an atmosphere check")

    p["last_oxygen_pct"] = oxygen_pct
    p["last_combustible_pct"] = combustible_pct
    if domain.atmosphere_passes(oxygen_pct, combustible_pct):
        # Passing: stays ACTIVE; only readings update.
        p["updated_at"] = now_iso()
        p["version"] = p["version"] + 1
    else:
        p["status"] = "SUSPENDED"
        p["atmosphere_ok"] = False
        p["updated_at"] = now_iso()
        p["version"] = p["version"] + 1
        _cascade_ticket_on_suspend(p)
    return success_object(serialize.serialize_permit(p))


@bp.route("/entry-permits/<permit_id>/resume", methods=["POST"])
def resume_permit(permit_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"oxygen_pct", "combustible_pct"})
    require_fields(body, ["oxygen_pct", "combustible_pct"])
    oxygen_pct = as_number(body["oxygen_pct"], "oxygen_pct")
    check_range(oxygen_pct, "oxygen_pct", 0, 100)
    combustible_pct = as_number(body["combustible_pct"], "combustible_pct")
    check_range(combustible_pct, "combustible_pct", 0, 100)

    require_role(ctx, {"SafetyOfficer"})
    p = _get_permit_or_404(permit_id)
    if p["status"] != "SUSPENDED":
        raise errors.conflict(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be SUSPENDED to resume")

    if not domain.atmosphere_passes(oxygen_pct, combustible_pct):
        raise errors.conflict(errors.ERR_ATMOSPHERE_UNSAFE,
                              "Atmosphere outside pass limits")

    p["status"] = "ACTIVE"
    p["atmosphere_ok"] = True
    p["last_oxygen_pct"] = oxygen_pct
    p["last_combustible_pct"] = combustible_pct
    p["updated_at"] = now_iso()
    p["version"] = p["version"] + 1
    _cascade_ticket_on_resume(p)
    return success_object(serialize.serialize_permit(p))


@bp.route("/entry-permits/<permit_id>/close", methods=["POST"])
def close_permit(permit_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"findings"})
    require_fields(body, ["findings"])
    findings = body["findings"]
    if not isinstance(findings, str) or not findings:
        raise errors.validation("findings must be a non-empty string")

    require_role(ctx, {"SafetyOfficer"})
    p = _get_permit_or_404(permit_id)
    if p["status"] != "ACTIVE":
        raise errors.conflict(errors.ERR_INVALID_PERMIT_STATE,
                              "Permit must be ACTIVE to close")

    p["status"] = "CLOSED"
    p["updated_at"] = now_iso()
    p["version"] = p["version"] + 1

    # Non-NONE findings auto-create a DRAFT DIAGNOSIS ServiceTicket.
    if findings != "NONE":
        v = store.vessels.get(p["vessel_id"])
        site_id = v["site_id"] if v is not None else None
        site = store.sites.get(site_id) if site_id else None
        ts = now_iso()
        ticket = {
            "id": new_id(),
            "site_id": site_id,
            "vessel_id": p["vessel_id"],
            "technician_id": None,
            "source_permit_id": p["id"],
            "job_type": "DIAGNOSIS",
            "requires_entry": False,
            "est_hours": 4,
            "crew_size": 1,
            "description": "",
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
        if v is not None and site is not None:
            ticket["estimate_cents"] = domain.compute_estimate_cents(ticket, v, site)
        store.service_tickets[ticket["id"]] = ticket

    return success_object(serialize.serialize_permit(p))
