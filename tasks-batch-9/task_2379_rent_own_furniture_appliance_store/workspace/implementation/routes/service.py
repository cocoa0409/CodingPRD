"""Service during the agreement: bay windows, swaps and resolutions."""

from flask import Blueprint

import clock
import middleware
import response
import validators
from db import base_row, db, public, touch
from errors import ApiError
from routes import common
from services import calc, domain

bp = Blueprint("service", __name__)

ISSUE_CODES = ("MECHANICAL", "COSMETIC", "MISSING_PART", "ELECTRICAL", "INFESTATION")
RESOLUTIONS = ("REPAIRED", "SWAPPED")
LIVE_TICKET_STATUSES = ("SCHEDULED", "SWAP_ISSUED")


def _bay_overlaps(store_id, start, end):
    """Closed intervals: touching endpoints DO collide (PRD 3.7)."""
    count = 0
    for ticket in db.tickets.values():
        if ticket["store_id"] != store_id:
            continue
        if ticket["status"] not in LIVE_TICKET_STATUSES:
            continue
        other_start = clock.parse(ticket["window_start_at"])
        other_end = clock.parse(ticket["window_end_at"])
        if other_start is None or other_end is None:
            continue
        if start <= other_end and end >= other_start:
            count += 1
    return count


@bp.post("/agreements/<agreement_id>/service-tickets")
def create_ticket(agreement_id):
    user_id, role = middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SERVICE_TECHNICIAN,
            middleware.CUSTOMER,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    middleware.require_owner(role, user_id, agreement["customer_id"])
    body = validators.json_body()
    issue_code = validators.enum(body, "issue_code", ISSUE_CODES)
    start = validators.datetime_field(body, "window_start_at")
    end = validators.datetime_field(body, "window_end_at")

    domain.check_payment_status(agreement, domain.OP_TICKET_CREATE)

    if end <= start:
        raise ApiError("ERR_INVALID_WINDOW")
    store = domain.require_store(agreement["store_id"])
    if not store["service_intake_open"]:
        raise ApiError("ERR_SERVICE_INTAKE_CLOSED")
    if _bay_overlaps(store["id"], start, end) >= store["service_bay_capacity"]:
        raise ApiError("ERR_SERVICE_CAPACITY_EXCEEDED")

    ticket = base_row()
    ticket["agreement_id"] = agreement["id"]
    ticket["store_id"] = agreement["store_id"]
    ticket["unit_id"] = agreement["unit_id"]
    ticket["replacement_unit_id"] = None
    ticket["issue_code"] = issue_code
    ticket["window_start_at"] = clock.fmt(start)
    ticket["window_end_at"] = clock.fmt(end)
    ticket["status"] = "SCHEDULED"
    ticket["resolution"] = "NONE"
    ticket["rent_credit_days"] = 0
    ticket["issued_by_user_id"] = user_id
    db.tickets[ticket["id"]] = ticket
    return response.object_response(public(ticket), 201)


@bp.get("/service-tickets/<ticket_id>")
def read_ticket(ticket_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.SERVICE_TECHNICIAN,
            middleware.CUSTOMER,
        )
    )
    ticket = domain.require_ticket(ticket_id)
    return response.object_response(public(ticket))


@bp.get("/service-tickets")
def list_tickets():
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    return common.paged(
        list(db.tickets.values()),
        primary="window_start_at",
        filters=("agreement_id", "store_id", "unit_id", "replacement_unit_id", "status"),
    )


@bp.post("/service-tickets/<ticket_id>/issue-swap")
def issue_swap(ticket_id):
    user_id, _ = middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    ticket = domain.require_ticket(ticket_id)
    body = validators.json_body()
    replacement_id = validators.identifier(body, "replacement_unit_id")
    replacement = domain.require_unit(replacement_id)

    agreement = db.agreements.get(ticket["agreement_id"])
    domain.check_possession_status(agreement, domain.OP_SWAP_ISSUE)
    if ticket["status"] != "SCHEDULED":
        raise ApiError("ERR_TICKET_STATE_INVALID")

    serviced = db.units.get(ticket["unit_id"])
    if (
        replacement["status"] != "AVAILABLE"
        or replacement["store_id"] != ticket["store_id"]
        or serviced is None
        or replacement["category"] != serviced["category"]
    ):
        raise ApiError("ERR_REPLACEMENT_UNIT_INVALID")

    ticket["status"] = "SWAP_ISSUED"
    ticket["replacement_unit_id"] = replacement["id"]
    ticket["issued_by_user_id"] = user_id
    touch(ticket)

    replacement["status"] = "ON_RENT"
    replacement["replaced_unit_id"] = serviced["id"]
    replacement["accumulated_rent_received_cents"] = serviced[
        "accumulated_rent_received_cents"
    ]
    touch(replacement)

    agreement["unit_id"] = replacement["id"]
    agreement["possession_status"] = "SERVICE_SWAP_PENDING"
    agreement["swap_count"] += 1
    touch(agreement)

    serviced["status"] = "IN_SERVICE"
    touch(serviced)

    store = db.stores.get(ticket["store_id"])
    if store is not None:
        domain.sync_store(store)
    return response.object_response(public(ticket))


@bp.post("/service-tickets/<ticket_id>/resolve")
def resolve_ticket(ticket_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SERVICE_TECHNICIAN,
        )
    )
    ticket = domain.require_ticket(ticket_id)
    body = validators.json_body()
    resolution = validators.enum(body, "resolution", RESOLUTIONS)
    credit_days = validators.integer(
        body, "rent_credit_days", minimum=0, maximum=30
    )

    if ticket["status"] not in LIVE_TICKET_STATUSES:
        raise ApiError("ERR_TICKET_STATE_INVALID")
    expected = "REPAIRED" if ticket["status"] == "SCHEDULED" else "SWAPPED"
    if resolution != expected:
        raise ApiError("ERR_TICKET_RESOLUTION_MISMATCH")

    was_swapped = ticket["status"] == "SWAP_ISSUED"
    ticket["status"] = "RESOLVED"
    ticket["resolution"] = resolution
    ticket["rent_credit_days"] = credit_days
    touch(ticket)

    agreement = db.agreements.get(ticket["agreement_id"])
    if agreement is not None:
        agreement["service_credit_days"] += credit_days
        if was_swapped:
            agreement["possession_status"] = "DELIVERED"
        touch(agreement)

    if was_swapped:
        serviced = db.units.get(ticket["unit_id"])
        if serviced is not None and serviced["status"] == "IN_SERVICE":
            serviced["status"] = "AVAILABLE"
            serviced["rent_cycle_count"] += 1
            serviced["condition_grade"] = calc.GRADE_STEP_DOWN[
                serviced["condition_grade"]
            ]
            touch(serviced)
        store = db.stores.get(ticket["store_id"])
        if store is not None:
            domain.sync_store(store)
    return response.object_response(public(ticket))
