"""GroupBlock: create / get / list / close (PRD §3.2)."""
from flask import Blueprint

import calc
import db
import helpers as H
import serialize as S
from errors import err
from middleware import authenticate, require_role
from response import success, success_list

bp = Blueprint("group_blocks", __name__)

NON_GUEST = {"RevenueManager", "FrontDeskAgent", "NightAuditor"}


@bp.route("/pms/group-blocks", methods=["POST"])
def create_group_block():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = H.get_json_body()
    H.require_fields(
        body,
        ["hotel_id", "room_type_id", "rate_plan_id", "block_name", "arrival_date", "departure_date", "cutoff_date", "blocked_rooms"],
    )
    H.resolve_fk(body, "hotel_id")
    H.resolve_fk(body, "room_type_id")
    H.resolve_fk(body, "rate_plan_id")
    block_name = H.require_str(body, "block_name")
    arrival_date = H.require_date(body, "arrival_date")
    departure_date = H.require_date(body, "departure_date")
    cutoff_date = H.require_date(body, "cutoff_date")
    if calc.parse_date(departure_date) <= calc.parse_date(arrival_date):
        raise err("ERR_INVALID_REQUEST", "departure_date must be strictly after arrival_date")
    blocked_rooms = H.require_int(body, "blocked_rooms", min_value=1)

    gb = {
        "hotel_id": body["hotel_id"],
        "room_type_id": body["room_type_id"],
        "rate_plan_id": body["rate_plan_id"],
        "block_name": block_name,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "cutoff_date": cutoff_date,
        "blocked_rooms": blocked_rooms,
        "washed_rooms": 0,
        "status": "OPEN",
    }
    db.stamp_create(gb)
    db.group_blocks[gb["id"]] = gb
    return success(S.group_block_out(gb), status=201)


@bp.route("/pms/group-blocks/<resource_id>", methods=["GET"])
def get_group_block(resource_id):
    _, role = authenticate()
    require_role(role, NON_GUEST)
    gb = H.get_or_404(db.group_blocks, resource_id)
    return success(S.group_block_out(gb), status=200)


@bp.route("/pms/group-blocks", methods=["GET"])
def list_group_blocks():
    _, role = authenticate()
    require_role(role, NON_GUEST)
    items, limit, offset, total = H.filter_and_paginate(
        db.group_blocks,
        S.group_block_out,
        {
            "hotel_id": H.qparam("hotel_id"),
            "room_type_id": H.qparam("room_type_id"),
            "rate_plan_id": H.qparam("rate_plan_id"),
            "status": H.qparam("status"),
        },
    )
    return success_list(items, limit, offset, total)


@bp.route("/pms/group-blocks/<resource_id>/close", methods=["POST"])
def close_group_block(resource_id):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    gb = H.get_or_404(db.group_blocks, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["expected_group_block_version"])
    expected = H.require_int(body, "expected_group_block_version")
    # transition validity (OPEN or WASHED -> CLOSED)
    if gb["status"] not in ("OPEN", "WASHED"):
        raise err("ERR_INVALID_STATE", "Group block is not in a closable state")
    if expected != gb["version"]:
        raise err("ERR_STALE_VERSION", "expected_group_block_version does not match")
    # No HELD reservation may still be attached.
    for rv in db.reservations.values():
        if rv["group_block_id"] == gb["id"] and rv["status"] == "HELD":
            raise err("ERR_BLOCK_HAS_PENDING_PICKUPS", "Block still has a HELD reservation attached")
    gb["status"] = "CLOSED"
    db.touch(gb)
    return success(S.group_block_out(gb), status=200)
