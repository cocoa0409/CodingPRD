"""Pen moves: booking a drover crew and walking the lot (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, enum_field, fields, path_row, reference
from clock import clock, parse_instant, render_derived, render_instant
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from routes.lots import _pen_admission
from services.lots import lot_tickets
from services.pens import recompute_pens
from store import db, get, insert_versioned, touch

bp = Blueprint("pen_moves", __name__)
ALL = config.ALL_ROLES


def _context(lot):
    consignment = get("consignments", lot["consignment_id"])
    sale_day = get("sale_days", lot["sale_day_id"])
    party = get("parties", consignment["consignor_party_id"]) if consignment else None
    return consignment, sale_day, party


@bp.post("/sale-barn/pen-moves")
def create_move():
    actor(["YardOperator"])
    data = body()
    v = fields(data, required=[
        ("lot_id", "string"),
        ("to_pen_id", "string"),
        ("crew_id", "string"),
        ("scheduled_start_at", "string"),
    ])
    start = parse_instant(v["scheduled_start_at"])
    if start is None:
        fail("ERR_INVALID_REQUEST",
             "Field 'scheduled_start_at' must be an ISO 8601 instant.")

    lot = reference("lots", v["lot_id"], "Lot")
    pen = reference("pens", v["to_pen_id"], "Pen")
    crew = reference("drover_crews", v["crew_id"], "DroverCrew")
    consignment, sale_day, party = _context(lot)
    run_gates("pen_moves.create", sale_day=sale_day, lot=lot, party=party)

    _pen_admission(lot, pen, consignment)

    # Rung 25 - the crew must be ON_DUTY at the moment of booking.
    if crew["duty_status"] != "ON_DUTY":
        fail("ERR_CREW_OFF_DUTY")

    end = start + timedelta(minutes=config.MOVE_DURATION_MINUTES)
    # Rung 26 - crew bookings must not collide, with a trailing cool-down.
    for existing in db["pen_moves"].values():
        if existing["crew_id"] != crew["id"]:
            continue
        if existing["status"] not in ("REQUESTED", "IN_PROGRESS"):
            continue
        blocked_until = existing["_scheduled_end_dt"] + timedelta(
            minutes=config.MOVE_BUFFER_MINUTES)
        if start < blocked_until and end > existing["_scheduled_start_dt"]:
            fail("ERR_CREW_MOVE_OVERLAP")

    row = insert_versioned("pen_moves", {
        "lot_id": lot["id"],
        "from_pen_id": lot.get("pen_id"),
        "to_pen_id": pen["id"],
        "crew_id": crew["id"],
        "head_moved": lot["head_count"],
        # A caller-supplied instant is echoed verbatim; its derived window end
        # is rendered in that same string's style.
        "scheduled_start_at": v["scheduled_start_at"],
        "scheduled_end_at": render_derived(end, v["scheduled_start_at"]),
        "_scheduled_start_dt": start,
        "_scheduled_end_dt": end,
        "status": "REQUESTED",
        "completed_at": None,
    })
    return ok(serialize.pen_move(row), 201)


@bp.get("/sale-barn/pen-moves/<move_id>")
def read_move(move_id):
    actor(ALL)
    return ok(serialize.pen_move(path_row("pen_moves", move_id, "PenMove")))


@bp.get("/sale-barn/pen-moves")
def list_moves():
    actor(ALL)
    rows = list(db["pen_moves"].values())
    for key in ("lot_id", "from_pen_id", "to_pen_id", "crew_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.pen_move)


@bp.post("/sale-barn/pen-moves/<move_id>/status")
def move_status(move_id):
    actor(["YardOperator"])
    move = path_row("pen_moves", move_id, "PenMove")
    data = body()
    to_status = enum_field(data, "to_status", config.PEN_MOVE_STATUSES)
    lot = get("lots", move["lot_id"])
    consignment, sale_day, party = _context(lot) if lot else (None, None, None)
    run_gates("pen_moves.status", sale_day=sale_day, lot=lot, party=party)

    legal = {
        ("REQUESTED", "IN_PROGRESS"),
        ("IN_PROGRESS", "COMPLETED"),
        ("REQUESTED", "ABORTED"),
        ("IN_PROGRESS", "ABORTED"),
    }
    if (move["status"], to_status) not in legal:
        fail("ERR_INVALID_STATE")

    if to_status == "IN_PROGRESS":
        crew = get("drover_crews", move["crew_id"])
        if crew is None or crew["duty_status"] != "ON_DUTY":
            fail("ERR_CREW_OFF_DUTY")
        move["status"] = "IN_PROGRESS"
        touch(move)
        return ok(serialize.pen_move(move))

    if to_status == "ABORTED":
        # The crew's booked window is released; no pen or lot field changes -
        # in particular the lot's pen_id is untouched.
        move["status"] = "ABORTED"
        touch(move)
        return ok(serialize.pen_move(move))

    # COMPLETED: a three-hop cascade.
    now = clock.now()
    move["status"] = "COMPLETED"
    move["completed_at"] = render_instant(now)
    touch(move)
    crew = get("drover_crews", move["crew_id"])
    if crew is not None:
        crew["last_move_completed_at"] = render_instant(now)
        touch(crew)

    from_pen_id = move.get("from_pen_id")
    if lot is not None:
        lot["pen_id"] = move["to_pen_id"]
        lot["penned_at"] = render_instant(now)
        touch(lot)
        recompute_pens(from_pen_id, move["to_pen_id"])
        for ticket in lot_tickets(lot["id"]):
            if ticket["status"] == "OPEN":
                ticket["status"] = "VOIDED"
                touch(ticket)
    return ok(serialize.pen_move(move))
