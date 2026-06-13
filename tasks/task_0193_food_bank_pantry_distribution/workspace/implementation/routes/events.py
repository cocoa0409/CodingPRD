"""DistributionEvent endpoints: plan, fetch, list, pack, finalize, void."""
from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_AGENCY_SCOPE_VIOLATION,
    ERR_HOUSEHOLD_NOT_CERTIFIED,
    ERR_OVER_DISTRIBUTION,
)
from middleware import get_identity, require_role
from response import object_response, array_response
from services import models
from services.calc import round2
from services.events import (
    planned_event_poundage,
    order_has_tefap_reserved_line,
    reserved_lines,
    finalize_cascade,
)
from services.validate import (
    get_json_body,
    parse_pagination,
    paginate,
    require_number,
)
from routes.lookups import get_order, get_household, get_event

bp = Blueprint("events", __name__)

READ_ROLES_ALL = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor", "AgencyCoordinator"}


def _owning_agency_id(event):
    order = db.agency_orders.get(event["agency_order_id"])
    return order["agency_id"] if order else None


@bp.post("/distribution-events")
def plan_event():
    user_id, role = get_identity()
    require_role(role, {"AgencyCoordinator"})
    body = get_json_body()
    if "agency_order_id" not in body or not isinstance(body.get("agency_order_id"), str):
        raise err(ERR_INVALID_REQUEST, "Missing or invalid agency_order_id.")
    order = get_order(body["agency_order_id"])
    if "client_household_id" not in body or not isinstance(
        body.get("client_household_id"), str
    ):
        raise err(ERR_INVALID_REQUEST, "Missing or invalid client_household_id.")
    household = get_household(body["client_household_id"])

    # scope ownership (priority 3): coordinator owns both order and household.
    if order["agency_id"] != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Order is not the caller's agency's.")
    if household["agency_id"] != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Household is not the caller's agency's.")

    event = models._common_create()
    event.update(
        {
            "agency_order_id": order["id"],
            "client_household_id": household["id"],
            "planned_lbs": 0,
            "actual_distributed_lbs": 0,
            "tefap_lbs": 0,
            "status": "PLANNED",
        }
    )
    db.distribution_events[event["id"]] = event
    return object_response(models.serialize_event(event), status=201)


@bp.get("/distribution-events/<event_id>")
def fetch_event(event_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    event = get_event(event_id)
    return object_response(models.serialize_event(event))


@bp.get("/distribution-events")
def list_events():
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    limit, offset = parse_pagination()
    events = list(db.distribution_events.values())
    for key in ("agency_order_id", "client_household_id", "status"):
        val = request.args.get(key)
        if val is not None:
            events = [e for e in events if e[key] == val]
    events.sort(key=lambda e: e["_seq"])
    page, total = paginate(events, limit, offset)
    return array_response([models.serialize_event(e) for e in page], limit, offset, total)


@bp.post("/distribution-events/<event_id>/pack")
def pack_event(event_id):
    user_id, role = get_identity()
    require_role(role, {"AgencyCoordinator"})
    event = get_event(event_id)
    # scope ownership (priority 3)
    if _owning_agency_id(event) != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Event is not the caller's agency's.")
    # state legality (priority 6)
    if event["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "Event is not PLANNED.")
    order = db.agency_orders[event["agency_order_id"]]
    household = db.client_households[event["client_household_id"]]
    # cross-entity precondition: order must be APPROVED.
    if order["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Linked order is not APPROVED.")
    # household certification (priority 8)
    if household["certification_status"] != "CERTIFIED":
        raise err(ERR_HOUSEHOLD_NOT_CERTIFIED, "Household is not CERTIFIED.")
    if order_has_tefap_reserved_line(order["id"]) and not household["tefap_eligible"]:
        raise err(
            ERR_HOUSEHOLD_NOT_CERTIFIED,
            "TEFAP line packed for a non-eligible household.",
        )

    event["planned_lbs"] = planned_event_poundage(order["id"])
    for line in reserved_lines(order["id"], {"RESERVED"}):
        line["line_status"] = "PACKED"
        models.touch(line)
    event["status"] = "PACKED"
    models.touch(event)
    return object_response(models.serialize_event(event))


@bp.post("/distribution-events/<event_id>/finalize")
def finalize_event(event_id):
    user_id, role = get_identity()
    require_role(role, {"AgencyCoordinator"})
    event = get_event(event_id)
    if _owning_agency_id(event) != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Event is not the caller's agency's.")
    body = get_json_body()
    actual = require_number(body, "actual_distributed_lbs", non_negative=True)
    # state legality (priority 6)
    if event["status"] != "PACKED":
        raise err(ERR_INVALID_STATE, "Event is not PACKED.")
    # over-distribution bound (priority 12)
    if round2(actual) > event["planned_lbs"]:
        raise err(ERR_OVER_DISTRIBUTION, "actual_distributed_lbs exceeds planned_lbs.")

    finalize_cascade(event, actual)
    return object_response(models.serialize_event(event))


@bp.post("/distribution-events/<event_id>/void")
def void_event(event_id):
    user_id, role = get_identity()
    require_role(role, {"AgencyCoordinator"})
    event = get_event(event_id)
    if _owning_agency_id(event) != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Event is not the caller's agency's.")
    if event["status"] not in ("PLANNED", "PACKED"):
        raise err(ERR_INVALID_STATE, "Event is not PLANNED or PACKED.")
    if event["status"] == "PACKED":
        order = db.agency_orders[event["agency_order_id"]]
        for line in reserved_lines(order["id"], {"PACKED"}):
            line["line_status"] = "RESERVED"
            models.touch(line)
        event["planned_lbs"] = 0
    event["status"] = "VOIDED"
    models.touch(event)
    return object_response(models.serialize_event(event))
