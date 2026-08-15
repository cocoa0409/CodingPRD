"""Assignments: launch, board, complete, cancel, recall, reassign."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, now, touch
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok, ok_list
from services import (
    LONG_DUTY_THRESHOLD_MINUTES,
    LONG_REST_MINUTES,
    SHORT_REST_MINUTES,
    assignment_view,
    base_entity,
    boat_interval_conflict,
    demote_entry,
    duty_ok,
    invoice_composition,
    pilot_has_current_endorsement,
    pilot_interval_conflict,
    pilot_rotation_entry,
    rest_ok,
    restore_entry,
    select_boat,
    select_pilot,
)
from util import (
    body,
    minutes_between,
    opt_dt,
    pagination_args,
    paginate,
    req_int,
)

bp = Blueprint("assignments", __name__)


def _get_assignment(aid):
    a = DB["assignments"].get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Assignment does not exist")
    return a


def _own_assignment(user_id, assignment):
    """Pilot ownership: only the assignment's pilot may act on it."""
    if assignment["pilot_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Pilot may act only on their own assignments"
        )


@bp.get("/pilotage/assignments")
def list_assignments():
    auth(ANY_ROLE)
    limit, offset = pagination_args()
    items = list(DB["assignments"].values())
    for field in ("order_id", "pilot_id", "boat_id", "apprentice_id", "service_status", "billing_status"):
        v = request.args.get(field)
        if v is not None:
            items = [a for a in items if a.get(field) == v]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([assignment_view(a) for a in page], total, limit, offset)


@bp.get("/pilotage/assignments/<aid>")
def get_assignment(aid):
    auth(ANY_ROLE)
    return ok(assignment_view(_get_assignment(aid)))


@bp.post("/pilotage/assignments/<aid>/start")
def start_assignment(aid):
    user_id, _ = auth(["Pilot"])
    assignment = _get_assignment(aid)
    _own_assignment(user_id, assignment)
    if assignment["service_status"] != "ASSIGNED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Assignment cannot be started from {assignment['service_status']}",
        )
    assignment["actual_start"] = now()
    assignment["service_status"] = "EN_ROUTE"
    touch(assignment)
    # Side effect: the order advances DISPATCHED -> IN_SERVICE.
    order = DB["vessel_orders"].get(assignment["order_id"])
    if order is not None and order["status"] == "DISPATCHED":
        order["status"] = "IN_SERVICE"
        touch(order)
    return ok(assignment_view(assignment))


@bp.post("/pilotage/assignments/<aid>/board")
def board_assignment(aid):
    user_id, _ = auth(["Pilot"])
    assignment = _get_assignment(aid)
    _own_assignment(user_id, assignment)
    if assignment["service_status"] != "EN_ROUTE":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Assignment cannot be boarded from {assignment['service_status']}",
        )
    assignment["service_status"] = "ABOARD"
    touch(assignment)
    return ok(assignment_view(assignment))


@bp.post("/pilotage/assignments/<aid>/complete")
def complete_assignment(aid):
    user_id, _ = auth(["Pilot"])
    assignment = _get_assignment(aid)
    _own_assignment(user_id, assignment)
    # State guard (priority 5) precedes structural validation (priority 23).
    if assignment["service_status"] != "ABOARD":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Assignment cannot be completed from {assignment['service_status']}",
        )
    data = body()
    detention_minutes = req_int(data, "detention_minutes", minimum=0)
    delay_minutes = req_int(data, "delay_minutes", minimum=0)

    assignment["actual_end"] = now()
    assignment["detention_minutes"] = detention_minutes
    assignment["delay_minutes"] = delay_minutes
    assignment["service_status"] = "COMPLETED"

    # Rest requirement: duration at/above 480 minutes (inclusive) earns the
    # 960-minute long rest; shorter duties earn 600 minutes.
    duration = minutes_between(assignment["actual_start"], assignment["actual_end"])
    rest = LONG_REST_MINUTES if duration >= LONG_DUTY_THRESHOLD_MINUTES else SHORT_REST_MINUTES
    pilot = DB["pilots"].get(assignment["pilot_id"])
    if pilot is not None:
        pilot["rest_until"] = assignment["actual_end"] + timedelta(minutes=rest)
        touch(pilot)

    # Invoice composition: final marginal-rate base plus detention/delay
    # extras; exactly one ISSUED invoice per assignment.
    order = DB["vessel_orders"].get(assignment["order_id"])
    schedule = DB["tariff_schedules"].get(order["tariff_schedule_id"]) if order else None
    if schedule is not None and order is not None:
        base, detention, delay, total = invoice_composition(
            order, schedule, detention_minutes, delay_minutes
        )
    else:
        base, detention, delay, total = 0, 0, 0, 0
    invoice = base_entity()
    invoice.update(
        {
            "assignment_id": assignment["id"],
            "base_fee_cents": base,
            "detention_fee_cents": detention,
            "delay_fee_cents": delay,
            "total_cents": total,
            "status": "ISSUED",
            "finalized_at": None,
        }
    )
    DB["invoices"][invoice["id"]] = invoice

    # Billing dimension advances as part of the same write.
    assignment["billing_status"] = "INVOICED"
    touch(assignment)

    # Order completes (the boat's ON_RUN status is derived and clears itself
    # once no assignment is EN_ROUTE/ABOARD).
    if order is not None and order["status"] == "IN_SERVICE":
        order["status"] = "COMPLETED"
        touch(order)

    # Training credit for a riding apprentice.
    if assignment["apprentice_id"] is not None:
        apprentice = DB["apprentices"].get(assignment["apprentice_id"])
        if apprentice is not None:
            apprentice["trips_completed"] += 1
            touch(apprentice)

    return ok(assignment_view(assignment))


@bp.post("/pilotage/assignments/<aid>/cancel")
def cancel_assignment(aid):
    auth(["Dispatcher"])
    assignment = _get_assignment(aid)
    if assignment["service_status"] not in ("ASSIGNED", "RECALLED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Assignment cannot be cancelled from {assignment['service_status']}",
        )
    if assignment["service_status"] == "ASSIGNED":
        # Compensation for the dispatch demotion: restore the recorded slot.
        entry = pilot_rotation_entry(assignment["pilot_id"])
        if entry is not None:
            restore_entry(entry)
        # Direct cancellation while the order is still DISPATCHED reverts the
        # order to BOOKED so it can be dispatched again.
        order = DB["vessel_orders"].get(assignment["order_id"])
        if order is not None and order["status"] == "DISPATCHED":
            order["status"] = "BOOKED"
            touch(order)
    # From RECALLED only the boat interval is released (implicit once the
    # assignment leaves the open-state set); the recalled pilot's turn was
    # consumed, so no board restoration happens.
    assignment["service_status"] = "CANCELLED"
    touch(assignment)
    return ok(assignment_view(assignment))


@bp.post("/pilotage/assignments/<aid>/recall")
def recall_assignment(aid):
    auth(["Dispatcher"])
    assignment = _get_assignment(aid)
    if assignment["service_status"] != "ASSIGNED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Assignment cannot be recalled from {assignment['service_status']}",
        )
    assignment["service_status"] = "RECALLED"
    assignment["recall_count"] += 1
    touch(assignment)
    return ok(assignment_view(assignment))


@bp.post("/pilotage/assignments/<aid>/reassign")
def reassign_assignment(aid):
    auth(["Dispatcher"])
    assignment = _get_assignment(aid)
    data = body()

    # Existence of body-referenced ids (priority 3).
    explicit_pilot = None
    if data.get("pilot_id") is not None:
        explicit_pilot = DB["pilots"].get(data["pilot_id"])
        if explicit_pilot is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Pilot does not exist")
    explicit_boat = None
    if data.get("boat_id") is not None:
        explicit_boat = DB["pilot_boats"].get(data["boat_id"])
        if explicit_boat is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Pilot boat does not exist")

    if assignment["service_status"] != "RECALLED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Assignment cannot be reassigned from {assignment['service_status']}",
        )

    # Effective window: payload values respecify; absent values keep current.
    new_start = opt_dt(data, "scheduled_start") or assignment["scheduled_start"]
    new_end = opt_dt(data, "scheduled_end") or assignment["scheduled_end"]
    if new_end <= new_start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "scheduled_end must be strictly after scheduled_start",
        )

    order = DB["vessel_orders"].get(assignment["order_id"])
    planned = minutes_between(new_start, new_end)

    if explicit_pilot is not None:
        pilot = explicit_pilot
        # Explicit-pilot validation in pinned order (priorities 8-11, 19):
        # license currency, tonnage cap, rest, rolling duty, closed interval.
        if not pilot_has_current_endorsement(pilot["id"]):
            raise ApiError(
                "ERR_LICENSE_NOT_CURRENT",
                422,
                "Pilot lacks a CURRENT endorsement with expires_at after now",
            )
        if not pilot_has_current_endorsement(pilot["id"], order["gt"]):
            raise ApiError(
                "ERR_TONNAGE_EXCEEDS_ENDORSEMENT",
                422,
                "Pilot's endorsement tonnage cap is below the order's gt",
            )
        if not rest_ok(pilot):
            raise ApiError(
                "ERR_FATIGUE_REST_ACTIVE", 422, "Pilot is still resting"
            )
        if not duty_ok(pilot["id"], planned):
            raise ApiError(
                "ERR_FATIGUE_DUTY_LIMIT",
                422,
                "Pilot's projected rolling duty exceeds the 7-day ceiling",
            )
        if pilot_interval_conflict(
            pilot["id"], new_start, new_end, exclude_assignment_id=assignment["id"]
        ):
            raise ApiError(
                "ERR_PILOT_TIME_CONFLICT",
                409,
                "Pilot has a closed-interval conflict with an open assignment",
            )
    else:
        # Absent pilot_id: the rotation selector runs over the new window.
        pilot = select_pilot(
            order, new_start, new_end, exclude_assignment_id=assignment["id"]
        )
        if pilot is None:
            raise ApiError(
                "ERR_NO_ELIGIBLE_PILOT",
                422,
                "No eligible pilot for this reassignment",
            )

    if explicit_boat is not None:
        boat = explicit_boat
        if boat_interval_conflict(
            boat["id"], new_start, new_end, exclude_assignment_id=assignment["id"]
        ):
            raise ApiError(
                "ERR_BOAT_TIME_CONFLICT",
                409,
                "Boat has a buffered-interval conflict with an open assignment",
            )
    else:
        boat = DB["pilot_boats"].get(assignment["boat_id"])

    assignment["pilot_id"] = pilot["id"]
    assignment["boat_id"] = boat["id"] if boat else assignment["boat_id"]
    assignment["scheduled_start"] = new_start
    assignment["scheduled_end"] = new_end
    assignment["service_status"] = "ASSIGNED"
    touch(assignment)

    # The newly assigned pilot's entry records the same demotion as dispatch.
    entry = pilot_rotation_entry(pilot["id"])
    if entry is not None:
        demote_entry(entry)

    return ok(assignment_view(assignment))
