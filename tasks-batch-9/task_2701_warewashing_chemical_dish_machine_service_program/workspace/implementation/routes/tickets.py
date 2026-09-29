"""Service tickets: customer reports, priority stamping and dispatch."""

from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from middleware import (
    ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT, ROLE_PLATFORM_ADMIN,
    ROLE_QUALITY_AUDITOR, ROLE_SERVICE_TECHNICIAN,
)
from routes import common
from services import calc, derive

bp = Blueprint("tickets", __name__)

SYMPTOMS = ("MACHINE_DOWN", "LOW_TEMP", "NO_CHEMICAL", "LEAK", "RACK_QUALITY")


@bp.route("/service-tickets", methods=["POST"])
def create_ticket():
    user_id, role = middleware.require_roles(
        ROLE_CUSTOMER_CONTACT, ROLE_ACCOUNT_MANAGER
    )
    raw = middleware.raw_body()
    if role == ROLE_CUSTOMER_CONTACT:
        candidate = db.get("machine_placements", raw.get("placement_id"))
        if candidate is not None:
            middleware.scope_customer(
                role, user_id, common.owner_of_placement(candidate)
            )

    body = middleware.body_object()
    placement_id = middleware.f_str(body, "placement_id", required=True)
    symptom = middleware.f_enum(
        body, "reported_symptom", SYMPTOMS, required=True
    )

    placement = middleware.must_reference(
        "machine_placements", placement_id, "placement_id"
    )
    if placement["placement_status"] != "INSTALLED":
        raise ApiError(
            "ERR_PLACEMENT_NOT_INSTALLED",
            "The placement is %s, not INSTALLED"
            % placement["placement_status"],
        )
    for existing in derive.tickets_of_placement(placement_id):
        if (existing["reported_symptom"] == symptom
                and existing["status"] in calc.OPEN_TICKET_STATUSES):
            raise ApiError(
                "ERR_DUPLICATE_OPEN_TICKET",
                "An open ticket for %s already exists" % symptom,
            )

    site = db.get("sites", placement["site_id"])
    ticket = derive.create_ticket(
        placement, site, "CUSTOMER_REPORT", symptom, None, user_id
    )
    return response.created(response.serialize(ticket))


@bp.route("/service-tickets/<ticket_id>", methods=["GET"])
def read_ticket(ticket_id):
    user_id, role = middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR,
        ROLE_CUSTOMER_CONTACT,
    )
    row = db.get("service_tickets", ticket_id)
    middleware.scope_customer(role, user_id, common.owner_of_ticket(row))
    row = middleware.must_exist("service_tickets", ticket_id, "ServiceTicket")
    return response.ok(response.serialize(row))


@bp.route("/service-tickets", methods=["GET"])
def list_tickets():
    middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_SERVICE_TECHNICIAN, ROLE_QUALITY_AUDITOR
    )
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("service_tickets"), (
        ("placement_id", "placement_id"),
        ("alert_id", "alert_id"),
        ("assigned_technician_id", "assigned_technician_id"),
        ("status", "status"),
        ("origin", "origin"),
        ("reported_symptom", "reported_symptom"),
    ))
    return common.listing(rows, limit, offset)


@bp.route("/service-tickets/<ticket_id>/dispatch", methods=["POST"])
def dispatch_ticket(ticket_id):
    middleware.require_roles(ROLE_PLATFORM_ADMIN)
    body = middleware.body_object()
    override_id = middleware.f_str(body, "override_technician_id")

    ticket = middleware.must_exist(
        "service_tickets", ticket_id, "ServiceTicket"
    )
    override = None
    if override_id is not None:
        override = middleware.must_reference(
            "technicians", override_id, "override_technician_id"
        )

    if ticket["status"] != "QUEUED":
        raise ApiError(
            "ERR_TICKET_NOT_DISPATCHABLE",
            "The ticket is %s, not QUEUED" % ticket["status"],
        )

    placement = db.get("machine_placements", ticket["placement_id"])
    site = db.get("sites", placement["site_id"]) if placement else None
    if site is None:
        raise ApiError(
            "ERR_NO_ELIGIBLE_TECHNICIAN", "The ticket's site is unresolvable"
        )
    needs_cert = bool(ticket["requires_sanitation_cert"])

    if override is not None:
        if override["region_code"] != site["region_code"]:
            raise ApiError(
                "ERR_TECHNICIAN_REGION_MISMATCH",
                "The technician's region does not match the site's",
            )
        if not calc.technician_eligible(override, site, needs_cert):
            raise ApiError(
                "ERR_NO_ELIGIBLE_TECHNICIAN",
                "The named technician is not eligible",
            )
        chosen = override
    else:
        candidates = [
            technician for technician in db.rows("technicians")
            if calc.technician_eligible(technician, site, needs_cert)
        ]
        if not candidates:
            raise ApiError(
                "ERR_NO_ELIGIBLE_TECHNICIAN",
                "No technician is eligible for this ticket",
            )
        chosen = calc.rank_technicians(candidates)[0]

    ticket["status"] = "DISPATCHED"
    ticket["assigned_technician_id"] = chosen["id"]
    db.mark(ticket)
    derive.recompute_technician(chosen)
    derive.recompute_site(site)
    return response.ok(response.serialize(ticket))
