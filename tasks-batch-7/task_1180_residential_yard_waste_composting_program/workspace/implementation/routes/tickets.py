"""PickupTicket endpoints (PRD §3.4, §3.6)."""

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_ROUTE_CAPACITY_EXCEEDED, ERR_ROUTE_NOT_PUBLISHED,
                    ERR_ROUTE_TONNAGE_EXCEEDED, ERR_SUBSCRIPTION_NOT_ACTIVE,
                    ERR_SUBSCRIPTION_NOT_FOUND, ERR_TICKET_DATE_OUT_OF_SEASON,
                    ERR_TICKET_NOT_FOUND, ERR_TICKET_NOT_SCHEDULED,
                    ERR_TICKET_NOT_YET_DUE,
                    err_invalid_request, err_invalid_state, err_not_found,
                    err_resident_not_owner)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import (base_record, light_record, touch, ticket_out, parse_date,
                           recompute_entitlement, total_season_weeks,
                           AVG_TICKET_WEIGHT_LBS, WEEKDAYS)
from services.validate import require_body, check_unknown_fields, req_str, req_int, req_date, req_bool

bp = Blueprint("tickets", __name__)

READ_ROLES = ("Resident", "Driver", "FieldInspector", "RouteSupervisor",
              "ProgramAdmin", "BillingClerk")


def _get_ticket_or_404(tid):
    t = STORE.tickets.get(tid)
    if not t:
        raise err_not_found(ERR_TICKET_NOT_FOUND, "Ticket not found")
    return t


@bp.post("/pickup-tickets")
def create_ticket():
    require_roles("RouteSupervisor")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"subscription_id", "route_id", "service_date"})
    subscription_id = req_str(data, "subscription_id")
    route_id = req_str(data, "route_id")
    service_date = req_date(data, "service_date")

    # body FK existence
    sub = STORE.subscriptions.get(subscription_id)
    if not sub:
        raise err_not_found(ERR_SUBSCRIPTION_NOT_FOUND, "Subscription not found")
    route = STORE.routes.get(route_id)
    if not route:
        raise err_not_found()

    # shape: service_date weekday must match route weekday
    wd = WEEKDAYS[parse_date(service_date).weekday()]
    if wd != route["weekday"]:
        raise err_invalid_request("service_date weekday does not match route weekday")

    # state: subscription ACTIVE
    if sub["status"] != "ACTIVE":
        raise ApiError(ERR_SUBSCRIPTION_NOT_ACTIVE,
                       "Subscription must be ACTIVE to schedule a ticket", 409)

    # temporal: service_date inside zone season window
    hh = STORE.households.get(sub["household_id"])
    zone = STORE.zones.get(hh["zone_id"]) if hh else None
    sd = parse_date(service_date)
    if zone:
        if sd < parse_date(zone["season_start_date"]) or sd > parse_date(zone["season_end_date"]):
            raise ApiError(ERR_TICKET_DATE_OUT_OF_SEASON,
                           "service_date outside zone season window", 422)

    # referential: route PUBLISHED
    if route["status"] != "PUBLISHED":
        raise ApiError(ERR_ROUTE_NOT_PUBLISHED, "Route must be PUBLISHED", 409)

    # capacity: stops then tonnage
    existing = [t for t in STORE.tickets.values()
                if t["route_id"] == route_id and t["service_date"] == service_date
                and t["status"] != "SKIPPED"]
    if len(existing) >= route["max_stops"]:
        raise ApiError(ERR_ROUTE_CAPACITY_EXCEEDED,
                       "Route stop capacity reached for this date", 409)
    projected = (len(existing) + 1) * AVG_TICKET_WEIGHT_LBS
    if projected > route["max_tonnage_lbs"]:
        raise ApiError(ERR_ROUTE_TONNAGE_EXCEEDED,
                       "Projected tonnage exceeds route cap", 409)

    t = base_record()
    t.update({
        "subscription_id": subscription_id, "route_id": route_id,
        "service_date": service_date, "status": "SCHEDULED",
        "weight_lbs": None, "completed_at": None,
        "missed_reported_by": None, "missed_validated_by": None,
    })
    STORE.tickets[t["id"]] = t
    return success_object(ticket_out(t), 201)


@bp.get("/pickup-tickets")
def list_tickets():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.tickets.values())
    sid = request.args.get("subscription_id")
    rid = request.args.get("route_id")
    sd = request.args.get("service_date")
    st = request.args.get("status")
    if sid is not None:
        items = [t for t in items if t["subscription_id"] == sid]
    if rid is not None:
        items = [t for t in items if t["route_id"] == rid]
    if sd is not None:
        items = [t for t in items if t["service_date"] == sd]
    if st is not None:
        items = [t for t in items if t["status"] == st]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ticket_out(t) for t in page], limit, offset, total)


@bp.get("/pickup-tickets/<tid>")
def get_ticket(tid):
    require_roles(*READ_ROLES)
    t = _get_ticket_or_404(tid)
    return success_object(ticket_out(t))


@bp.post("/pickup-tickets/<tid>/complete")
def complete_ticket(tid):
    require_roles("Driver")
    t = _get_ticket_or_404(tid)
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"weight_lbs"})
    weight = req_int(data, "weight_lbs")
    if weight <= 0:
        raise err_invalid_request("weight_lbs must be > 0")

    if t["status"] != "SCHEDULED":
        raise ApiError(ERR_TICKET_NOT_SCHEDULED, "Ticket is not SCHEDULED", 409)
    sub = STORE.subscriptions.get(t["subscription_id"])
    if not sub or sub["status"] != "ACTIVE":
        raise ApiError(ERR_SUBSCRIPTION_NOT_ACTIVE,
                       "Subscription must be ACTIVE to complete a ticket", 409)

    t["status"] = "COMPLETED"
    t["weight_lbs"] = weight
    t["completed_at"] = STORE.clock_iso()
    touch(t)
    recompute_entitlement(sub["household_id"])
    return success_object(ticket_out(t))


@bp.post("/pickup-tickets/<tid>/report-missed")
def report_missed(tid):
    user_id, role = require_roles("Resident")
    t = _get_ticket_or_404(tid)
    data = request.get_json(silent=True)
    if data is not None:
        if not isinstance(data, dict):
            raise err_invalid_request("Request body must be a JSON object")
        check_unknown_fields(data, set())

    sub = STORE.subscriptions.get(t["subscription_id"])
    if user_id != (sub["household_id"] if sub else None):
        raise err_resident_not_owner()

    if t["status"] != "SCHEDULED":
        raise ApiError(ERR_TICKET_NOT_SCHEDULED, "Ticket is not SCHEDULED", 409)

    # temporal: only on/after service_date
    if parse_date(t["service_date"]) > STORE.clock_date():
        raise ApiError(ERR_TICKET_NOT_YET_DUE,
                       "Cannot report a miss before the service date", 422)

    t["status"] = "MISSED_REPORTED"
    t["missed_reported_by"] = sub["household_id"]
    touch(t)
    return success_object(ticket_out(t))


@bp.post("/pickup-tickets/<tid>/validate-missed")
def validate_missed(tid):
    user_id, role = require_roles("RouteSupervisor")
    t = _get_ticket_or_404(tid)
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"validated"})
    validated = req_bool(data, "validated")

    if t["status"] != "MISSED_REPORTED":
        raise err_invalid_state("Ticket is not MISSED_REPORTED")

    sub = STORE.subscriptions.get(t["subscription_id"])
    if validated:
        t["status"] = "MISSED"
        t["missed_validated_by"] = user_id
        touch(t)
        # create ServiceCredit PENDING_APPROVAL
        hh = STORE.households.get(sub["household_id"])
        zone = STORE.zones.get(hh["zone_id"]) if hh else None
        if sub["service_model"] == "OPT_IN":
            tsw = total_season_weeks(zone)
            amount = sub["base_fee_cents"] // tsw
        else:
            amount = zone["universal_flat_credit_cents"]
        c = light_record()
        c.update({
            "household_id": sub["household_id"],
            "subscription_id": sub["id"],
            "missed_pickup_ticket_id": t["id"],
            "amount_cents": amount,
            "status": "PENDING_APPROVAL",
            "validated_by": user_id,
            "approved_by": None,
        })
        STORE.credits[c["id"]] = c
    else:
        t["status"] = "SCHEDULED"
        t["missed_reported_by"] = None
        touch(t)
    return success_object(ticket_out(t))
