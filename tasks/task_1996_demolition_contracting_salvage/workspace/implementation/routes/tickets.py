"""DebrisTicket endpoints: manifesting, receipt, dispute, reconciliation with
delta caps, voiding, and project tonnage counter reconciliation."""

from decimal import Decimal

from flask import Blueprint, request

from db import store, now, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_PROJECT_STOPPED,
                    ERR_TICKET_WEIGHT_INVALID, ERR_RECONCILE_DELTA_EXCEEDED)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_debris_ticket
from services import (get_project, get_debris_ticket, project_tickets,
                      recompute_diversion, RECONCILE_DELTA_CAP_TONS)
from util import req_str, req_enum, req_tons, opt_str

bp = Blueprint("tickets", __name__)

FACILITY_TYPES = ("LANDFILL", "RECYCLING", "TRANSFER")
MATERIAL_CLASSES = ("CONCRETE", "METAL", "WOOD", "MIXED_CD")
TICKET_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "HaulingDispatcher")
TICKET_ACTIONS = ("RECEIVE", "DISPUTE", "RECONCILE", "VOID")
TICKET_CREATABLE_PHASES = ("DEMOLITION_ACTIVE", "DEBRIS_CLEARANCE")


@bp.post("/demolition/projects/<pid>/debris-tickets")
@require_roles("HaulingDispatcher")
def create_ticket(pid):
    b = body()
    ticket_number = req_str(b, "ticket_number")
    facility_type = req_enum(b, "facility_type", FACILITY_TYPES)
    material_class = req_enum(b, "material_class", MATERIAL_CLASSES)
    gross = req_tons(b, "gross_tons")
    project = get_project(pid)
    if project["status"] not in TICKET_CREATABLE_PHASES:
        raise err(ERR_INVALID_STATE, "tickets require DEMOLITION_ACTIVE or DEBRIS_CLEARANCE")
    if project["work_posture"] != "WORKABLE":
        raise err(ERR_PROJECT_STOPPED, "project work_posture is STOPPED")

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "ticket_number": ticket_number,
        "facility_type": facility_type,
        "material_class": material_class,
        "gross_tons": gross,
        "diverted_tons": Decimal("0"),
        "disposed_tons": Decimal("0"),
        "status": "MANIFESTED",
        "received_at": None,
    })
    store.debris_tickets[rec["id"]] = rec

    project["in_transit_tons"] += gross
    touch(project)
    return success(ser_debris_ticket(rec), status=201)


@bp.get("/demolition/projects/<pid>/debris-tickets")
@require_roles(*TICKET_READ_ROLES)
def list_tickets(pid):
    project = get_project(pid)
    items = project_tickets(project["id"])
    status_arg = request.args.get("status")
    if status_arg is not None:
        items = [t for t in items if t["status"] == status_arg]
    return list_response(items, ser_debris_ticket)


@bp.post("/demolition/debris-tickets/<tid>/transition")
@require_roles("HaulingDispatcher")
def ticket_transition(tid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in TICKET_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    # Optional free-text fields; validate type only when present.
    opt_str(b, "reason")
    diverted_payload = None
    if "diverted_tons" in b and b["diverted_tons"] is not None:
        diverted_payload = req_tons(b, "diverted_tons", allow_zero=True)
    corrected_gross = None
    if "corrected_gross_tons" in b and b["corrected_gross_tons"] is not None:
        corrected_gross = req_tons(b, "corrected_gross_tons", allow_zero=True)
    corrected_diverted = None
    if "corrected_diverted_tons" in b and b["corrected_diverted_tons"] is not None:
        corrected_diverted = req_tons(b, "corrected_diverted_tons", allow_zero=True)

    ticket = get_debris_ticket(tid)
    project = store.projects[ticket["project_id"]]
    status = ticket["status"]

    if action == "RECEIVE":
        if status != "MANIFESTED":
            raise err(ERR_INVALID_STATE, "RECEIVE requires MANIFESTED")
        if diverted_payload is None:
            raise err(ERR_VALIDATION, "diverted_tons is required")
        if diverted_payload > ticket["gross_tons"]:
            raise err(ERR_TICKET_WEIGHT_INVALID, "diverted_tons exceeds gross_tons")
        ticket["diverted_tons"] = diverted_payload
        ticket["disposed_tons"] = ticket["gross_tons"] - diverted_payload
        ticket["received_at"] = now()
        ticket["status"] = "RECEIVED"
        touch(ticket)
        project["in_transit_tons"] -= ticket["gross_tons"]
        project["landfill_tons"] += ticket["disposed_tons"]
        project["diverted_tons"] += ticket["diverted_tons"]
        recompute_diversion(project)
        touch(project)

    elif action == "DISPUTE":
        if status != "RECEIVED":
            raise err(ERR_INVALID_STATE, "DISPUTE requires RECEIVED")
        ticket["status"] = "DISPUTED"
        touch(ticket)

    elif action == "RECONCILE":
        if status not in ("RECEIVED", "DISPUTED"):
            raise err(ERR_INVALID_STATE, "RECONCILE requires RECEIVED or DISPUTED")
        if corrected_gross is None or corrected_diverted is None:
            raise err(ERR_VALIDATION,
                      "corrected_gross_tons and corrected_diverted_tons are required")
        if (abs(corrected_gross - ticket["gross_tons"]) > RECONCILE_DELTA_CAP_TONS
                or abs(corrected_diverted - ticket["diverted_tons"]) > RECONCILE_DELTA_CAP_TONS):
            raise err(ERR_RECONCILE_DELTA_EXCEEDED, "correction exceeds 2.0 tons")
        if corrected_diverted > corrected_gross:
            raise err(ERR_TICKET_WEIGHT_INVALID,
                      "corrected_diverted_tons exceeds corrected_gross_tons")
        old_disposed = ticket["disposed_tons"]
        old_diverted = ticket["diverted_tons"]
        ticket["gross_tons"] = corrected_gross
        ticket["diverted_tons"] = corrected_diverted
        ticket["disposed_tons"] = corrected_gross - corrected_diverted
        ticket["status"] = "RECONCILED"
        touch(ticket)
        project["landfill_tons"] += ticket["disposed_tons"] - old_disposed
        project["diverted_tons"] += corrected_diverted - old_diverted
        recompute_diversion(project)
        touch(project)

    else:  # VOID
        if status == "MANIFESTED":
            ticket["status"] = "VOIDED"
            touch(ticket)
            project["in_transit_tons"] -= ticket["gross_tons"]
            project["removed_tons"] += ticket["gross_tons"]
            recompute_diversion(project)
            touch(project)
        elif status == "RECEIVED":
            ticket["status"] = "VOIDED"
            touch(ticket)
            project["landfill_tons"] -= ticket["disposed_tons"]
            project["diverted_tons"] -= ticket["diverted_tons"]
            project["removed_tons"] += ticket["gross_tons"]
            recompute_diversion(project)
            touch(project)
        else:
            raise err(ERR_INVALID_STATE, "VOID requires MANIFESTED or RECEIVED")

    return success(ser_debris_ticket(ticket))
