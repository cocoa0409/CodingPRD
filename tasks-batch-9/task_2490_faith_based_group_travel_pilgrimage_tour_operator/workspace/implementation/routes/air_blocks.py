"""Air blocks and the cyclic carrier negotiation (PRD section 3.6)."""

import re

from flask import Blueprint

import core
import response
from db import db, lock
from errors import err
from middleware import (ROLE_AIR_DESK_AGENT, ROLE_FINANCE_CONTROLLER, ROLE_PROGRAM_MANAGER,
                        authorize)
from validate import (apply_filters, body_of, opt_datetime, opt_int, pagination, req_datetime,
                      req_enum, req_id, req_int, req_str)

bp = Blueprint("air_blocks", __name__)

READ_ROLES = (ROLE_AIR_DESK_AGENT, ROLE_PROGRAM_MANAGER, ROLE_FINANCE_CONTROLLER)
CARRIER_RE = re.compile(r"^[A-Z0-9]{2}$")


def _load(air_block_id):
    row = db.air_blocks.get(air_block_id)
    if row is None:
        err("ERR_AIR_BLOCK_NOT_FOUND", "Air block %s does not exist." % air_block_id)
    return row


@bp.route("/air-blocks", methods=["POST"])
def create_air_block():
    authorize((ROLE_AIR_DESK_AGENT,))
    body = body_of()
    with lock:
        departure_id = req_id(body, "departure_id")
        carrier_code = req_str(body, "carrier_code", 2, 2)
        if not CARRIER_RE.match(carrier_code):
            err("ERR_INVALID_REQUEST",
                "carrier_code must be exactly two uppercase alphanumeric characters.")
        seats_held = req_int(body, "seats_held", 1, 400)
        name_change_deadline_utc = req_datetime(body, "name_change_deadline_utc")
        deposit_deadline_utc = req_datetime(body, "deposit_deadline_utc")

        departure = db.departures.get(departure_id)
        if departure is None:
            err("ERR_DEPARTURE_NOT_FOUND", "Departure %s does not exist." % departure_id)
        core.refresh_posture(departure)
        if departure["status"] not in ("PLANNING", "OPEN_FOR_SALE"):
            err("ERR_DEPARTURE_INVALID_STATE",
                "An air block can only be opened on a PLANNING or OPEN_FOR_SALE departure.")

        row = core.base_row()
        row.update({
            "departure_id": departure_id,
            "carrier_code": carrier_code,
            "seats_held": seats_held,
            "offered_fare_cents": 0,
            "countered_fare_cents": None,
            "contracted_fare_cents": None,
            "negotiation_round": 0,
            "name_change_deadline_utc": response.iso_ms(name_change_deadline_utc),
            "deposit_deadline_utc": response.iso_ms(deposit_deadline_utc),
            "seats_assigned": 0,
            "status": "DRAFT",
        })
        db.air_blocks[row["id"]] = row
        return response.ok(core.serialize_air_block(row), 201)


@bp.route("/air-blocks/<air_block_id>", methods=["GET"])
def get_air_block(air_block_id):
    authorize(READ_ROLES)
    with lock:
        row = _load(air_block_id)
        return response.ok(core.serialize_air_block(row))


@bp.route("/air-blocks", methods=["GET"])
def list_air_blocks():
    authorize(READ_ROLES)
    with lock:
        limit, offset = pagination()
        rows = core.order_rows(list(db.air_blocks.values()))
        rows = apply_filters(rows, {
            "departure_id": "departure_id",
            "status": "status",
        })
        page, total = core.paginate(rows, limit, offset)
        return response.ok_list([core.serialize_air_block(r) for r in page],
                                limit, offset, total)


@bp.route("/air-blocks/<air_block_id>/negotiation-rounds", methods=["POST"])
def negotiation_round(air_block_id):
    authorize((ROLE_AIR_DESK_AGENT,))
    body = body_of()
    with lock:
        block = _load(air_block_id)
        party = req_enum(body, "party", core.NEGOTIATION_PARTIES)
        fare_cents = req_int(body, "fare_cents", 0)
        name_change_deadline_utc = opt_datetime(body, "name_change_deadline_utc", None)
        requested_seats = opt_int(body, "requested_seats", 1, 400)

        core.guard_air_block_deadline(block)
        if block["status"] not in ("DRAFT", "OFFERED", "COUNTERED"):
            err("ERR_AIR_BLOCK_INVALID_STATE",
                "A %s block admits no negotiation round." % block["status"])

        if party == "CARRIER_OFFER":
            if block["status"] not in ("DRAFT", "COUNTERED"):
                err("ERR_AIR_BLOCK_INVALID_STATE",
                    "A carrier offer is accepted only from DRAFT or COUNTERED.")
            block["status"] = "OFFERED"
            block["offered_fare_cents"] = fare_cents
            block["negotiation_round"] = block["negotiation_round"] + 1
            if name_change_deadline_utc is not None:
                block["name_change_deadline_utc"] = response.iso_ms(name_change_deadline_utc)
        else:
            if block["status"] != "OFFERED":
                err("ERR_AIR_BLOCK_INVALID_STATE",
                    "An operator counter is accepted only from OFFERED.")
            if fare_cents >= block["offered_fare_cents"]:
                err("ERR_AIR_BLOCK_INVALID_STATE",
                    "A counter must be strictly below the standing offered fare.")
            block["status"] = "COUNTERED"
            block["countered_fare_cents"] = fare_cents
            if requested_seats is not None:
                block["seats_held"] = requested_seats

        core.touch(block)
        return response.ok(core.serialize_air_block(block))


@bp.route("/air-blocks/<air_block_id>/confirm", methods=["POST"])
def confirm_air_block(air_block_id):
    authorize((ROLE_AIR_DESK_AGENT,))
    with lock:
        block = _load(air_block_id)
        core.guard_air_block_deadline(block)
        if block["status"] != "OFFERED":
            err("ERR_AIR_BLOCK_INVALID_STATE", "Only an OFFERED block can be confirmed.")
        if core.clock_now() > core.as_dt(block["deposit_deadline_utc"]):
            err("ERR_AIR_BLOCK_INVALID_STATE", "The deposit deadline has passed.")
        for other in core.air_blocks_of_departure(block["departure_id"]):
            if other["id"] != block["id"] and other["status"] == "CONFIRMED":
                err("ERR_AIR_BLOCK_INVALID_STATE",
                    "The departure already holds a CONFIRMED block.")

        block["status"] = "CONFIRMED"
        block["contracted_fare_cents"] = block["offered_fare_cents"]
        core.touch(block)
        return response.ok(core.serialize_air_block(block))
