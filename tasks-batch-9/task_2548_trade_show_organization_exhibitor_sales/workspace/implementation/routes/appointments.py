"""Selection appointments: booking, listing and exercise (PRD 3.4)."""
from flask import Blueprint, request

import calc
import guards
import services
import validate
import views
from db import (base_row, by_created, db, fmt_dt, now, parse_date, parse_dt,
                touch)
from errors import ApiError
from middleware import (EXHIBITOR, FLOOR_MANAGER, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, list_response, object_response, pagination, re_int

bp = Blueprint("appointments", __name__)


@bp.route("/shows/<show_id>/selection-appointments", methods=["POST"])
def create_appointment(show_id):
    body = validate.body()
    exhibitor_id = validate.text(body, "exhibitor_id", 1, 64)
    round_index = validate.integer(body, "round_index", minimum=1)
    window_start = validate.datetime_field(body, "window_start")
    window_end = validate.datetime_field(body, "window_end")

    authenticate((SHOW_DIRECTOR, SALES_REP))
    show = guards.get_show(show_id)
    exhibitor = guards.get_exhibitor(exhibitor_id)
    guards.require_exhibitor_active(exhibitor)

    start = window_start
    end = window_end
    event_start = parse_date(show["event_start"])
    if not (start < end) or start.date() > event_start or end.date() > event_start:
        raise ApiError("ERR_INVALID_APPOINTMENT_WINDOW",
                       "the desk window must be well-formed and on or before event_start")

    concurrent = 1
    for other in calc.show_appointments(show["id"]):
        if other["state"] != "SCHEDULED" or other["round_index"] != round_index:
            continue
        other_start = parse_dt(other["window_start"])
        other_end = parse_dt(other["window_end"])
        if other_start < end and start < other_end:
            concurrent += 1
    if concurrent > show["selection_desk_capacity"]:
        raise ApiError("ERR_SELECTION_DESK_CAPACITY_EXCEEDED",
                       "the selection desk is fully booked for this window")

    row = base_row()
    row.update({
        "show_id": show["id"],
        "exhibitor_id": exhibitor["id"],
        "round_index": round_index,
        "window_start": fmt_dt(window_start),
        "window_end": fmt_dt(window_end),
        "state": "SCHEDULED",
        "rank": None,
        "certified_points_at_rank": None,
    })
    db.selection_appointments[row["id"]] = row
    return created(views.appointment_view(row))


@bp.route("/selection-appointments/<appointment_id>", methods=["GET"])
def read_appointment(appointment_id):
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    appointment = guards.get_appointment(appointment_id)
    return object_response(views.appointment_view(appointment))


@bp.route("/selection-appointments", methods=["GET"])
def list_appointments():
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    rows = by_created(list(db.selection_appointments.values()))
    for field in ("show_id", "exhibitor_id", "state"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    round_index = request.args.get("round_index")
    if round_index:
        if not re_int(round_index):
            validate.bad("round_index must be an integer")
        wanted = int(round_index)
        rows = [r for r in rows if r["round_index"] == wanted]
    return list_response([views.appointment_view(r) for r in rows], limit, offset)


@bp.route("/selection-appointments/<appointment_id>/exercise", methods=["POST"])
def exercise_appointment(appointment_id):
    body = validate.body()
    expected_show_version = validate.integer(body, "expected_show_version", minimum=0)
    requested_sqft = validate.integer(body, "requested_sqft", minimum=1)
    premium = validate.boolean(body, "premium_placement_requested", default=False)
    booth_ids = validate.id_list(body, "booth_ids", required=False)

    ctx = authenticate((EXHIBITOR, SALES_REP))
    known = db.selection_appointments.get(appointment_id)
    if known is not None:
        ctx.enforce_scope(known["exhibitor_id"])
    booths = guards.get_booths(booth_ids) if booth_ids else []
    appointment = guards.get_appointment(appointment_id)

    show = guards.get_show(appointment["show_id"])
    guards.require_show_status(show, ("SPACE_SELECTION",))
    guards.require_appointment_state(appointment, ("ACTIVE",))
    guards.reject_merged_booths(booths)
    guards.check_show_version(show, expected_show_version)

    exhibitor = guards.get_exhibitor(appointment["exhibitor_id"])
    guards.require_exhibitor_active(exhibitor)
    guards.reject_frozen_floor(show)

    for booth in booths:
        if booth["show_id"] != appointment["show_id"]:
            raise ApiError("ERR_APPOINTMENT_EXHIBITOR_MISMATCH",
                           "the appointment does not belong to the show being claimed")
    guards.require_booths_in_show(booths, show["id"])
    guards.require_booths_available(booths)
    if not booths:
        chosen = calc.select_booth(show["id"], requested_sqft, premium)
        if chosen is None:
            raise ApiError("ERR_NO_ELIGIBLE_BOOTH",
                           "no booth on this floor satisfies the request")
        booths = [chosen]
    guards.reject_duplicate_active_contract(show["id"], exhibitor["id"])

    start = parse_dt(appointment["window_start"])
    end = parse_dt(appointment["window_end"])
    current = now()
    if current < start or current >= end:
        raise ApiError("ERR_APPOINTMENT_WINDOW_CLOSED",
                       "the desk window for this appointment is not open")

    contract = services.open_space_contract(show, exhibitor, requested_sqft,
                                            premium, booths)
    appointment["state"] = "EXERCISED"
    touch(appointment)
    touch(show)
    return created(views.space_contract_view(contract))
