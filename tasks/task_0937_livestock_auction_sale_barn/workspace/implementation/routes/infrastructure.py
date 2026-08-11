"""Clock, parties, pens, scales and drover crews (PRD 3.1, 4)."""
from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, enum_field, path_row, require, check_min
from clock import clock, parse_instant
from envelope import ok
from errors import fail
from gates import run_gates
from money import D
from store import db, insert_versioned, touch

bp = Blueprint("infrastructure", __name__)
ALL = config.ALL_ROLES


# ------------------------------------------------------------- the clock ---
@bp.post("/sale-barn/_clock/set_current_utc")
def set_clock():
    actor(["BarnAdmin"])
    data = body()
    raw = require(data, "to_iso8601", "string")
    moment = parse_instant(raw)
    if moment is None:
        fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO 8601 instant.")
    clock.set(raw, moment)
    # Nothing is cached against the old instant: scale certification and every
    # inspection-validity comparison are derived on read.
    return ok({"current_utc": clock.current_utc_string()})


# ---------------------------------------------------------------- parties --
@bp.post("/sale-barn/parties")
def create_party():
    actor(["BarnAdmin"])
    data = body()
    legal_name = require(data, "legal_name", "string")
    party_type = enum_field(data, "party_type", config.PARTY_TYPES)
    origin_state_code = require(data, "origin_state_code", "string")
    origin_county = require(data, "origin_county", "string")
    tax_id = require(data, "tax_id", "string")
    row = insert_versioned("parties", {
        "legal_name": legal_name,
        "party_type": party_type,
        "origin_state_code": origin_state_code,
        "origin_county": origin_county,
        "tax_id": tax_id,
        "status": "ACTIVE",
    })
    return ok(serialize.party(row), 201)


@bp.get("/sale-barn/parties/<party_id>")
def read_party(party_id):
    actor(ALL)
    return ok(serialize.party(path_row("parties", party_id, "Party")))


@bp.post("/sale-barn/parties/<party_id>/status")
def party_status(party_id):
    actor(["BarnAdmin"])
    party = path_row("parties", party_id, "Party")
    data = body()
    to_status = enum_field(data, "to_status", config.PARTY_STATUSES)
    # Gate G4's single exemption: without it a suspended party could never be
    # reinstated.
    run_gates("parties.status", party=party)
    legal = {("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE")}
    if (party["status"], to_status) not in legal:
        fail("ERR_INVALID_STATE")
    party["status"] = to_status
    touch(party)
    return ok(serialize.party(party))


# ------------------------------------------------------------------- pens --
@bp.post("/sale-barn/pens")
def create_pen():
    actor(["BarnAdmin"])
    data = body()
    pen_code = require(data, "pen_code", "string")
    species_class = enum_field(data, "species_class", config.SPECIES_CLASSES)
    head_capacity = require(data, "head_capacity", "integer")
    pen_type = enum_field(data, "pen_type", config.PEN_TYPES)
    check_min(head_capacity, 1, "head_capacity")
    row = insert_versioned("pens", {
        "pen_code": pen_code,
        "species_class": species_class,
        "head_capacity": head_capacity,
        "pen_type": pen_type,
        "status": "AVAILABLE",
        "current_head": 0,
    })
    return ok(serialize.pen(row), 201)


@bp.get("/sale-barn/pens/<pen_id>")
def read_pen(pen_id):
    actor(ALL)
    return ok(serialize.pen(path_row("pens", pen_id, "Pen")))


@bp.post("/sale-barn/pens/<pen_id>/status")
def pen_status(pen_id):
    actor(["BarnAdmin"])
    pen = path_row("pens", pen_id, "Pen")
    data = body()
    to_status = enum_field(data, "to_status", config.PEN_STATUSES)
    if to_status == "OUT_OF_SERVICE":
        if pen["status"] != "AVAILABLE" or pen["current_head"] != 0:
            fail("ERR_INVALID_STATE")
    elif to_status == "AVAILABLE":
        if pen["status"] != "OUT_OF_SERVICE":
            fail("ERR_INVALID_STATE")
    else:
        # OCCUPIED is system-driven by occupancy, never requested.
        fail("ERR_INVALID_STATE")
    pen["status"] = to_status
    touch(pen)
    return ok(serialize.pen(pen))


# ----------------------------------------------------------------- scales --
@bp.post("/sale-barn/scales")
def create_scale():
    actor(["BarnAdmin"])
    data = body()
    scale_code = require(data, "scale_code", "string")
    certified_from = require(data, "certified_from", "string")
    certification_expires_on = require(data, "certification_expires_on", "string")
    max_draft_lb = require(data, "max_draft_lb", "number")
    check_min(max_draft_lb, 0, "max_draft_lb")
    row = insert_versioned("scales", {
        "scale_code": scale_code,
        "certified_from": certified_from,
        "certification_expires_on": certification_expires_on,
        # Adjudication of friction 12: max_draft_lb is recorded and reported
        # but never policed - no rung of the ladder compares a draft against
        # it, so no enforcement is invented here.
        "max_draft_lb": D(max_draft_lb),
    })
    return ok(serialize.scale(row), 201)


@bp.get("/sale-barn/scales/<scale_id>")
def read_scale(scale_id):
    actor(ALL)
    return ok(serialize.scale(path_row("scales", scale_id, "Scale")))


# ----------------------------------------------------------- drover crews --
@bp.post("/sale-barn/drover-crews")
def create_crew():
    actor(["YardOperator"])
    data = body()
    crew_code = require(data, "crew_code", "string")
    member_count = require(data, "member_count", "integer")
    check_min(member_count, 1, "member_count")
    row = insert_versioned("drover_crews", {
        "crew_code": crew_code,
        "member_count": member_count,
        "duty_status": "OFF_DUTY",
        "last_move_completed_at": None,
    })
    return ok(serialize.drover_crew(row), 201)


@bp.get("/sale-barn/drover-crews/<crew_id>")
def read_crew(crew_id):
    actor(ALL)
    return ok(serialize.drover_crew(path_row("drover_crews", crew_id, "DroverCrew")))


@bp.post("/sale-barn/drover-crews/<crew_id>/duty")
def crew_duty(crew_id):
    actor(["YardOperator"])
    crew = path_row("drover_crews", crew_id, "DroverCrew")
    data = body()
    to_status = enum_field(data, "to_status", config.CREW_DUTY_STATUSES)
    legal = {
        ("OFF_DUTY", "ON_DUTY"),
        ("ON_BREAK", "ON_DUTY"),
        ("ON_DUTY", "ON_BREAK"),
        ("ON_DUTY", "OFF_DUTY"),
        ("ON_BREAK", "OFF_DUTY"),
    }
    if (crew["duty_status"], to_status) not in legal:
        fail("ERR_INVALID_STATE")
    if to_status in ("ON_BREAK", "OFF_DUTY"):
        # A crew cannot clock down while it has a move in progress; a crew
        # going on break keeps its REQUESTED bookings.
        for move in db["pen_moves"].values():
            if move["crew_id"] == crew["id"] and move["status"] == "IN_PROGRESS":
                fail("ERR_INVALID_STATE")
    crew["duty_status"] = to_status
    touch(crew)
    return ok(serialize.drover_crew(crew))
