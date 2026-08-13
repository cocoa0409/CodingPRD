"""Incident reports and site posture inputs (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import db
import domain
import errors
import util

bp = Blueprint("incidents", __name__)
READ_ROLES = ("Driver", "SiteOperator", "NetworkAdmin")
OPERATOR_TARGETS = ("ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "REOPENED")

# Declared transitions: current -> allowed targets
_TRANSITIONS = {
    "OPEN": ("ACKNOWLEDGED", "DISMISSED"),
    "ACKNOWLEDGED": ("INVESTIGATING", "DISMISSED"),
    "INVESTIGATING": ("RESOLVED", "DISMISSED"),
    "RESOLVED": ("REOPENED",),
    "REOPENED": ("INVESTIGATING",),
    "DISMISSED": (),
}


@bp.post("/sites/<site_id>/incidents")
def report_incident(site_id):
    ident = auth.identity()
    auth.require_roles(ident, ("Driver", "SiteOperator"))
    if domain.get("sites", site_id) is None:
        raise errors.not_found("Site not found")
    body = util.get_body(required=True)
    util.req_fields(body, ["category", "severity", "description"])
    category = util.req_enum(body, "category", ("SECURITY", "LIGHTING", "FACILITY"))
    severity = util.req_enum(body, "severity", ("LOW", "MEDIUM", "HIGH", "CRITICAL"))
    description = util.req_str(body, "description")
    reporter = body.get("reporter_driver_id")
    if ident.role == "Driver":
        # A driver's report always names themselves.
        if reporter is not None and reporter != ident.user_id:
            raise errors.forbidden("reporter_driver_id must equal X-User-ID")
        reporter = ident.user_id
    else:
        reporter = None  # SiteOperator reports carry a null reporter
    incident = domain.new_entity("incidents", {
        "site_id": site_id,
        "reporter_driver_id": reporter,
        "booking_id": None,
        "category": category,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "acknowledged_by_user_id": None,
        "resolved_by_user_id": None,
        "resolved_at": None,
        "reopened_count": 0,
    })
    return util.ok(domain.serialize_incident(incident), status=201)


@bp.get("/incidents")
def list_incidents():
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    items = list(domain.all_of("incidents"))
    for field in ("site_id", "reporter_driver_id", "booking_id", "category", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [i for i in items if i[field] == value]
    items = util.sort_created(items)
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_incident(i) for i in page], pagination=pg)


@bp.get("/incidents/<incident_id>")
def get_incident(incident_id):
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    incident = domain.get("incidents", incident_id)
    if incident is None:
        raise errors.not_found("IncidentReport not found")
    return util.ok(domain.serialize_incident(incident))


@bp.post("/incidents/<incident_id>/transition")
def transition_incident(incident_id):
    ident = auth.identity()
    auth.require_roles(ident, ("SiteOperator", "NetworkAdmin"))
    incident = domain.get("incidents", incident_id)
    if incident is None:
        raise errors.not_found("IncidentReport not found")
    body = util.get_body(required=True)
    util.req_fields(body, ["to"])
    to = util.req_enum(body, "to", ("OPEN", "ACKNOWLEDGED", "INVESTIGATING",
                                    "RESOLVED", "REOPENED", "DISMISSED"))
    # Role-scoped targets: operators work the lifecycle; admins dismiss.
    if to == "DISMISSED":
        if ident.role != "NetworkAdmin":
            raise errors.forbidden("DISMISSED is reserved to NetworkAdmin")
    else:
        if ident.role != "SiteOperator":
            raise errors.forbidden("Lifecycle transitions are SiteOperator-only")
        if to not in OPERATOR_TARGETS:
            raise errors.invalid_state(f"No operator transition to {to}")

    if to not in _TRANSITIONS.get(incident["status"], ()):
        raise errors.invalid_state(
            f"Incident {incident['status']} -> {to} not permitted")

    if to == "RESOLVED":
        if ident.user_id is not None \
                and ident.user_id == incident["acknowledged_by_user_id"]:
            raise errors.segregation_of_duties()
        incident["resolved_by_user_id"] = ident.user_id
        incident["resolved_at"] = db.clock_now()
    elif to == "ACKNOWLEDGED":
        incident["acknowledged_by_user_id"] = ident.user_id
    elif to == "REOPENED":
        deadline = incident["resolved_at"] + timedelta(hours=72)
        if db.clock_now() > deadline:  # 72h window inclusive
            raise errors.reopen_window_expired()
        incident["reopened_count"] += 1

    incident["status"] = to
    domain.touch(incident)
    return util.ok(domain.serialize_incident(incident))
