"""Related-service addenda and specialised transportation (PRD 3.4)."""
from flask import Blueprint

from calc import (
    recompute_placement_encumbrance,
    service_addendum_encumbrance,
    transport_encumbrance,
    window_collides,
)
from cascades import (
    account_of,
    book_encumbrance,
    promote_from_waitlist,
    unwind_active_assignment,
)
from common import (
    SERVICE_TYPES,
    addendum_or_404,
    assignment_or_404,
    collection,
    placement_or_404,
    route_or_404,
    single,
)
from errors import fail
from middleware import (
    ALL_ROLES,
    FISCAL_OFFICER,
    PLACEMENT_COORDINATOR,
    endpoint,
)
from response import created, ok
from store import db, new_row, public, touch
from validation import (
    get_bool,
    get_enum,
    get_id,
    get_int,
    get_quarter_hours,
    q_str,
    read_body,
)

bp = Blueprint("services", __name__)


# =========================================================================
# service addenda
# =========================================================================

@endpoint(bp, "GET", "/service-addenda", ALL_ROLES)
def list_addenda():
    return collection(db.addenda.values(), [
        ("placement_id", q_str("placement_id")),
        ("status", q_str("status")),
    ])


@endpoint(bp, "GET", "/service-addenda/<addendum_id>", ALL_ROLES)
def get_addendum(addendum_id):
    return single(addendum_or_404(addendum_id))


@endpoint(bp, "POST", "/service-addenda", (PLACEMENT_COORDINATOR,))
def create_addendum():
    body = read_body((
        "placement_id", "service_type", "authorized_hours_per_week", "contract_weeks",
        "medicaid_billable",
    ))
    placement_id = get_id(body, "placement_id")
    service_type = get_enum(body, "service_type", SERVICE_TYPES)
    hours = get_quarter_hours(body, "authorized_hours_per_week", exclusive_min=0, maximum=40)
    weeks = get_int(body, "contract_weeks", required=False, default=36, minimum=1, maximum=52)
    medicaid_billable = get_bool(body, "medicaid_billable", default=False)

    placement_or_404(placement_id)

    for existing in db.addenda.values():
        if (existing["placement_id"] == placement_id
                and existing["service_type"] == service_type
                and existing["status"] in ("PROPOSED", "ACTIVE")):
            fail("ERR_DUPLICATE_RESOURCE",
                 "A live addendum for this service type already exists on the placement.")

    row = new_row("addendum", {
        "placement_id": placement_id,
        "service_type": service_type,
        "authorized_hours_per_week": hours,
        "contract_weeks": weeks,
        "hourly_rate_cents": 0,
        "medicaid_billable": medicaid_billable,
        "encumbrance_cents": 0,
        "delivered_hours_ytd": 0,
        "status": "PROPOSED",
    })
    db.addenda[row["id"]] = row
    return created(public(row))


@endpoint(bp, "POST", "/service-addenda/<addendum_id>/authorize", (FISCAL_OFFICER,))
def authorize_addendum(addendum_id):
    addendum = addendum_or_404(addendum_id)
    read_body(())

    if addendum["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a PROPOSED addendum may be authorised.")

    placement = db.placements.get(addendum["placement_id"])
    if placement is None or placement["status"] not in ("CONTRACTED", "ACTIVE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The parent placement must be CONTRACTED or ACTIVE.")

    schedule = db.rate_schedules.get(placement["rate_schedule_id"])
    hourly_rate = schedule["service_hourly_rate_cents"] if schedule is not None else 0
    addendum["hourly_rate_cents"] = hourly_rate
    amount = service_addendum_encumbrance(addendum, hourly_rate)

    account = account_of(placement)
    if account is None or account["available_cents"] < amount:
        addendum["hourly_rate_cents"] = 0
        fail("ERR_INSUFFICIENT_FISCAL_AUTHORITY",
             "The appropriation cannot cover the addendum commitment.")

    addendum["encumbrance_cents"] = amount
    addendum["status"] = "ACTIVE"
    touch(addendum)

    placement["addendum_encumbrance_cents"] += amount
    recompute_placement_encumbrance(placement)
    touch(placement)
    book_encumbrance(account, amount)
    return ok(public(addendum))


# =========================================================================
# transportation assignments
# =========================================================================

@endpoint(bp, "GET", "/transportation-assignments", ALL_ROLES)
def list_assignments():
    return collection(db.assignments.values(), [
        ("placement_id", q_str("placement_id")),
        ("route_id", q_str("route_id")),
        ("status", q_str("status")),
    ])


@endpoint(bp, "GET", "/transportation-assignments/<assignment_id>", ALL_ROLES)
def get_assignment(assignment_id):
    return single(assignment_or_404(assignment_id))


@endpoint(bp, "POST", "/transportation-assignments", (PLACEMENT_COORDINATOR,))
def create_assignment():
    body = read_body((
        "placement_id", "route_id", "pickup_window_start_min", "pickup_window_end_min",
        "days_per_week", "contract_weeks",
    ))
    placement_id = get_id(body, "placement_id")
    route_id = get_id(body, "route_id")
    window_start = get_int(body, "pickup_window_start_min", minimum=0, maximum=1439)
    window_end = get_int(body, "pickup_window_end_min", minimum=1, maximum=1440)
    days_per_week = get_int(body, "days_per_week", minimum=1, maximum=7)
    weeks = get_int(body, "contract_weeks", required=False, default=36, minimum=1, maximum=52)
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST",
             "pickup_window_end_min must be strictly greater than pickup_window_start_min.")

    placement = placement_or_404(placement_id)
    route = route_or_404(route_id)

    if placement["status"] not in ("CONTRACTED", "ACTIVE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The placement must be CONTRACTED or ACTIVE to request transportation.")
    if not placement["transportation_required"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The placement does not require district-funded transportation.")

    if (window_start < route["service_window_start_min"]
            or window_end > route["service_window_end_min"]):
        fail("ERR_TRANSPORT_WINDOW_OVERLAP",
             "The pickup window falls outside the route's service window.")
    if window_collides(route_id, window_start, window_end):
        fail("ERR_TRANSPORT_WINDOW_OVERLAP",
             "The pickup window collides with another active rider on this route.")

    row = new_row("assignment", {
        "placement_id": placement_id,
        "route_id": route_id,
        "pickup_window_start_min": window_start,
        "pickup_window_end_min": window_end,
        "days_per_week": days_per_week,
        "contract_weeks": weeks,
        "encumbrance_cents": 0,
        "status": "REQUESTED",
        "promoted_at": None,
    })

    if route["seats_available"] >= 1:
        amount = transport_encumbrance(row, route)
        account = account_of(placement)
        if account is None or account["available_cents"] < amount:
            fail("ERR_INSUFFICIENT_FISCAL_AUTHORITY",
                 "The appropriation cannot cover the transport commitment.")
        row["status"] = "ACTIVE"
        row["encumbrance_cents"] = amount
        db.assignments[row["id"]] = row
        route["seats_committed"] += 1
        route["seats_available"] = route["seat_capacity"] - route["seats_committed"]
        touch(route)
        placement["transport_status"] = "ASSIGNED"
        placement["transport_encumbrance_cents"] += amount
        recompute_placement_encumbrance(placement)
        touch(placement)
        book_encumbrance(account, amount)
    else:
        row["status"] = "WAITLISTED"
        db.assignments[row["id"]] = row
        placement["transport_status"] = "WAITLISTED"
        touch(placement)

    return created(public(row))


@endpoint(bp, "POST", "/transportation-assignments/<assignment_id>/release",
          (PLACEMENT_COORDINATOR,))
def release_assignment(assignment_id):
    assignment = assignment_or_404(assignment_id)
    read_body(())

    if assignment["status"] not in ("ACTIVE", "WAITLISTED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only an ACTIVE or WAITLISTED assignment may be released.")

    placement = db.placements.get(assignment["placement_id"])
    account = account_of(placement) if placement is not None else None
    prior = assignment["status"]
    assignment["status"] = "RELEASED"
    touch(assignment)

    if prior == "ACTIVE":
        route = unwind_active_assignment(assignment, placement, account)
        if placement is not None:
            remaining = any(
                a["placement_id"] == placement["id"] and a["status"] == "ACTIVE"
                for a in db.assignments.values()
            )
            if not remaining:
                placement["transport_status"] = "RELEASED"
            recompute_placement_encumbrance(placement)
            touch(placement)
        if route is not None:
            promote_from_waitlist(route, account)
    else:
        if placement is not None:
            remaining = any(
                a["placement_id"] == placement["id"] and a["status"] in ("ACTIVE", "WAITLISTED")
                for a in db.assignments.values()
            )
            if not remaining:
                placement["transport_status"] = "RELEASED"
                touch(placement)

    return ok(public(assignment))
