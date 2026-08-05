"""Public complaints (service requests) and the logical-clock capability."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
import store
import views
from common import (
    ALL_DISTRICT_READERS, ApiError, CLOCK, authenticate, authorize, created,
    get_body, logical_now, ok, ok_list, opt_enum, pagination, paginate,
    parse_dt, query_enum, query_str, req_enum, req_int, req_present,
    req_string, validation,
)

bp = Blueprint("request", __name__)

CATEGORIES = ("STANDING_WATER", "ADULT_ACTIVITY", "DEAD_BIRD", "SPRAY_CONCERN")
HANDLING_STATUSES = ("RECEIVED", "TRIAGED", "ASSIGNED", "INSPECTED", "RESOLVED",
                     "CLOSED")
VERIFICATION_STATUSES = ("FIELD_CONFIRMED", "UNFOUNDED")
PRIORITIES = ("ROUTINE", "PRIORITY", "URGENT")

REQUEST_ACTORS = {
    "TRIAGE": "AbatementManager",
    "ASSIGN": "AbatementManager",
    "INSPECT": "FieldTech",
    "RESOLVE": "FieldTech",
    "REOPEN": "AbatementManager",
    "CLOSE": "AbatementManager",
}


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(authenticate(), ("DistrictAdmin",))
    body = get_body()
    instant = parse_dt(req_present(body, "to_iso8601"), "to_iso8601")
    CLOCK.set(instant)
    return ok({"current_utc": CLOCK.now()})


# --------------------------------------------------------------------------
# Service requests
# --------------------------------------------------------------------------


@bp.post("/service-requests")
def create_service_request():
    actor = authorize(authenticate(), ("Resident",))
    body = get_body()
    area = None
    if body.get("service_area_id") is not None:
        area = store.fetch("ServiceArea", body.get("service_area_id"))

    req_string(body, "service_area_id", 1)
    reporter_contact = req_string(body, "reporter_contact", 1, 120)
    category = req_enum(body, "category", CATEGORIES)
    description = req_string(body, "description", 1, 500)
    x_m = req_int(body, "x_m")
    y_m = req_int(body, "y_m")

    record = store.new_record()
    record.update({
        "service_area_id": area["id"],
        "assigned_applicator_id": None,
        "reporter_contact": reporter_contact,
        "category": category,
        "description": description,
        "x_m": x_m,
        "y_m": y_m,
        "reported_by_user_id": actor.user_id,
        "handling_status": "RECEIVED",
        "verification_status": "UNVERIFIED",
        "priority": "ROUTINE",
        "triaged_at": None,
        "due_at": None,
        "resolved_at": None,
        "reopen_count": 0,
        "resolution_note": None,
    })
    store.SERVICE_REQUESTS[record["id"]] = record

    area["request_total_count"] = area["request_total_count"] + 1
    area["request_open_count"] = area["request_open_count"] + 1
    store.touch(area)

    return created(views.service_request_view(record))


@bp.get("/service-requests")
def list_service_requests():
    authorize(authenticate(), ALL_DISTRICT_READERS + ("Resident",))
    limit, offset = pagination()
    area_id = query_str("service_area_id")
    applicator_id = query_str("assigned_applicator_id")
    handling_status = query_enum("handling_status", HANDLING_STATUSES)
    priority = query_enum("priority", PRIORITIES)
    rows = [r for r in store.SERVICE_REQUESTS.values()
            if (area_id is None or r["service_area_id"] == area_id)
            and (applicator_id is None or r["assigned_applicator_id"] == applicator_id)
            and (handling_status is None or r["handling_status"] == handling_status)
            and (priority is None or r["priority"] == priority)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.service_request_view(r) for r in page], limit, offset, total)


@bp.get("/service-requests/<service_request_id>")
def get_service_request(service_request_id):
    authorize(authenticate(), ALL_DISTRICT_READERS + ("Resident",))
    row = store.fetch("ServiceRequest", service_request_id)
    return ok(views.service_request_view(row))


@bp.post("/service-requests/<service_request_id>/transitions")
def transition_service_request(service_request_id):
    actor = authorize(authenticate(), ("AbatementManager", "FieldTech"))
    body = get_body()
    action, known = domain.read_action(body, REQUEST_ACTORS)
    domain.enforce_actor(action, known, REQUEST_ACTORS, actor)

    row = store.fetch("ServiceRequest", service_request_id)

    applicator = None
    if known and action == "ASSIGN" and body.get("assigned_applicator_id") is not None:
        applicator = store.fetch("Applicator", body.get("assigned_applicator_id"))

    if known and action in ("INSPECT", "RESOLVE"):
        if actor.user_id != row["assigned_applicator_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                           "Only the assigned technician may act on this complaint.")

    domain.require_action_supplied(action)
    priority = None
    verification_status = None
    resolution_note = None
    if known and action == "TRIAGE":
        priority = req_enum(body, "priority", PRIORITIES)
    if known and action == "ASSIGN":
        req_string(body, "assigned_applicator_id", 1)
    if known and action == "INSPECT":
        verification_status = opt_enum(body, "verification_status",
                                       VERIFICATION_STATUSES, default=None)
        if row["handling_status"] == "INSPECTED" and verification_status is None:
            raise validation("verification_status is mandatory on a re-inspection.")
    if known and action == "RESOLVE":
        resolution_note = req_string(body, "resolution_note", 1, 1000)
    domain.require_known_action(action, known)

    area = store.SERVICE_AREAS.get(row["service_area_id"])

    if action == "TRIAGE":
        _triage(row, area, priority)
    elif action == "ASSIGN":
        _assign(row, applicator)
    elif action == "INSPECT":
        _inspect(row, verification_status)
    elif action == "RESOLVE":
        _resolve(row, area, resolution_note)
    elif action == "REOPEN":
        _reopen(row, area)
    else:
        _close(row, area)

    return ok(views.service_request_view(row))


def _triage(row, area, priority):
    if row["handling_status"] != "RECEIVED":
        raise domain.invalid_transition("TRIAGE requires a RECEIVED complaint.")
    floor = calc.POSTURE_FLOOR[area["risk_posture"]] if area else "ROUTINE"
    if calc.PRIORITY_RANK[floor] > calc.PRIORITY_RANK[priority]:
        priority = floor
    row["priority"] = priority
    row["handling_status"] = "TRIAGED"
    row["triaged_at"] = logical_now()
    row["due_at"] = calc.service_request_due_at(row["triaged_at"], priority)
    store.touch(row)


def _assign(row, applicator):
    if row["handling_status"] != "TRIAGED":
        raise domain.invalid_transition("ASSIGN requires a TRIAGED complaint.")
    if applicator["status"] != "ACTIVE":
        raise ApiError("ERR_APPLICATOR_SUSPENDED", 409,
                       "The applicator is suspended.")
    row["assigned_applicator_id"] = applicator["id"]
    row["handling_status"] = "ASSIGNED"
    store.touch(row)


def _inspect(row, verification_status):
    if row["handling_status"] not in ("ASSIGNED", "INSPECTED"):
        raise domain.invalid_transition("INSPECT requires an ASSIGNED or INSPECTED complaint.")
    row["handling_status"] = "INSPECTED"
    if verification_status is not None:
        row["verification_status"] = verification_status
    store.touch(row)


def _resolve(row, area, resolution_note):
    if row["handling_status"] != "INSPECTED":
        raise domain.invalid_transition("RESOLVE requires an INSPECTED complaint.")
    if row["verification_status"] == "UNVERIFIED":
        raise ApiError("ERR_REQUEST_NOT_VERIFIED", 409,
                       "The complaint has no field verdict yet.")
    row["handling_status"] = "RESOLVED"
    row["resolved_at"] = logical_now()
    row["resolution_note"] = resolution_note
    store.touch(row)
    if area is not None:
        domain.counters_move(area, "request_open_count", "request_resolved_count")


def _reopen(row, area):
    if row["handling_status"] != "RESOLVED":
        raise domain.invalid_transition("REOPEN requires a RESOLVED complaint.")
    deadline = row["resolved_at"] + timedelta(days=calc.REOPEN_WINDOW_DAYS)
    if logical_now() > deadline:
        raise ApiError("ERR_REOPEN_WINDOW_EXPIRED", 422,
                       "The reopen window has closed.")
    row["handling_status"] = "TRIAGED"
    row["reopen_count"] = row["reopen_count"] + 1
    row["verification_status"] = "UNVERIFIED"
    row["assigned_applicator_id"] = None
    row["triaged_at"] = logical_now()
    row["due_at"] = calc.service_request_due_at(row["triaged_at"], row["priority"])
    store.touch(row)
    if area is not None:
        domain.counters_move(area, "request_resolved_count", "request_open_count")


def _close(row, area):
    if row["handling_status"] not in ("RESOLVED", "RECEIVED"):
        raise domain.invalid_transition("CLOSE requires a RESOLVED or RECEIVED complaint.")
    from_resolved = row["handling_status"] == "RESOLVED"
    row["handling_status"] = "CLOSED"
    store.touch(row)
    if area is not None:
        if from_resolved:
            domain.counters_move(area, "request_resolved_count", "request_closed_count")
        else:
            domain.counters_move(area, "request_open_count", "request_closed_count")
