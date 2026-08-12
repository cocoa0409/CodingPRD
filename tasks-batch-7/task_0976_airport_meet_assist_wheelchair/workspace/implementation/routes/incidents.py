"""Incidents."""
from flask import Blueprint

import db
from errors import bad_request, invalid_state
from middleware import require_roles
from response import success_object
from routes.util import (get_or_404, json_body, require_enum, require_fields,
                         serialize_incident)
from services import cascades

bp = Blueprint("incidents", __name__)

ALL_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "Agent",
             "Confirmer", "BillingClerk")


@bp.post("/maa/incidents")
def create_incident():
    require_roles("Agent", "OpsManager", "Dispatcher")
    body = json_body()
    require_fields(body, ["assignment_id", "kind", "severity", "description"])
    asg = db.assignments.get(body["assignment_id"])
    if asg is None:
        raise bad_request("assignment_id does not resolve")
    kind = require_enum(body["kind"],
                        {"FALL", "MISSED_CONNECTION", "MEDICAL", "PROPERTY_DAMAGE", "SECURITY"},
                        "kind")
    severity = require_enum(body["severity"], {"MINOR", "MAJOR", "CRITICAL"}, "severity")
    if not isinstance(body["description"], str):
        raise bad_request("description must be a string")
    incident = db.common_fields()
    incident.update({
        "assist_request_id": asg["assist_request_id"],
        "assignment_id": asg["id"],
        "kind": kind,
        "severity": severity,
        "description": body["description"],
        "status": "OPEN",
        "opened_at_utc": db.now(),
    })
    db.incidents[incident["id"]] = incident
    return success_object(serialize_incident(incident), status=201)


@bp.get("/maa/incidents/<iid>")
def get_incident(iid):
    require_roles(*ALL_ROLES)
    incident = get_or_404(db.incidents, iid, "Incident")
    return success_object(serialize_incident(incident))


@bp.post("/maa/incidents/<iid>/events")
def incident_event(iid):
    require_roles("OpsManager")
    incident = get_or_404(db.incidents, iid, "Incident")
    body = json_body()
    require_fields(body, ["event_type"])
    event_type = require_enum(body["event_type"], {"ACK", "RESOLVE"}, "event_type")
    if event_type == "ACK":
        if incident["status"] != "OPEN":
            raise invalid_state("Incident must be OPEN to acknowledge")
        incident["status"] = "ACKED"
        db.touch(incident)
    else:  # RESOLVE
        if incident["status"] != "ACKED":
            raise invalid_state("Incident must be ACKED to resolve")
        incident["status"] = "RESOLVED"
        db.touch(incident)
        if incident["severity"] == "CRITICAL":
            asg = db.assignments.get(incident["assignment_id"])
            if asg is not None:
                agent = db.agents.get(asg["agent_id"])
                if agent is not None and agent["status"] == "ACTIVE":
                    agent["status"] = "SUSPENDED"
                    db.touch(agent)
                    for other in list(db.assignments.values()):
                        if other["agent_id"] == agent["id"]:
                            cascades.cancel_assignment_for_agent_suspend(other)
                # PROPERTY_DAMAGE + FINALIZED billing -> ADJUSTMENT invoice
                if incident["kind"] == "PROPERTY_DAMAGE":
                    request = db.assist_requests.get(asg["assist_request_id"])
                    if request is not None and request["billing_status"] == "FINALIZED":
                        final_inv = None
                        for inv in db.invoices.values():
                            if (inv["assist_request_id"] == request["id"]
                                    and inv["invoice_kind"] == "FINAL"):
                                final_inv = inv
                                break
                        if final_inv is not None:
                            credit = int(round(0.20 * (request.get("final_charge_cents") or 0)))
                            adj = db.common_fields()
                            adj.update({
                                "assist_request_id": request["id"],
                                "invoice_kind": "ADJUSTMENT",
                                "amount_cents": -credit,
                                "status": "OPEN",
                                "bill_to": request["bill_to"],
                                "supersedes_invoice_id": final_inv["id"],
                                "writeoff_baseline_cents": None,
                                "created_by_user_id": None,
                            })
                            db.invoices[adj["id"]] = adj
                            if final_inv["status"] == "OPEN":
                                final_inv["status"] = "VOID"
                                db.touch(final_inv)
    return success_object(serialize_incident(incident))
