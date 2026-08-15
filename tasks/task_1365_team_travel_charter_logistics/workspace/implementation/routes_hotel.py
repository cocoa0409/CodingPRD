"""HotelBlock and RoomAssignment routes."""
from flask import Blueprint, g

import calc
import util
from util import (
    ApiError,
    apply_filters,
    body,
    check_version,
    finalize_trip,
    invalid,
    paginate,
    req_date,
    req_int,
    req_str,
    req_version,
    opt_bool,
    opt_int,
    opt_str,
    require_role,
    resolve_block,
    resolve_member,
    resolve_room,
    resolve_team,
    resolve_trip,
    team_member_read_guard,
)
from envelope import ok, ok_list
from state import STORE, bump, clock_now, fmt_ts, new_resource, public, parse_date

bp = Blueprint("hotel", __name__)


def trip_not_terminal(trip):
    if trip["posture"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_TRIP_ALREADY_TERMINAL", 409, "Trip already CLOSED or CANCELLED")


def trip_must_be_draft(trip):
    trip_not_terminal(trip)
    if trip["posture"] != "DRAFT":
        raise ApiError("ERR_TRIP_NOT_DRAFT", 409, "Operation requires trip posture DRAFT")


def cutoff_passed(block):
    cutoff = parse_date(block["cutoff_date"])
    if cutoff is None:
        return False
    return clock_now().date() > cutoff


# ---------------------------------------------------------------------------
# Hotel blocks
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/hotel-blocks", methods=["POST"])
def create_block(teamId, tripId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    data = body()
    hotel_code = req_str(data, "hotel_code")
    room_count = req_int(data, "room_count")
    rate = req_int(data, "rate_cents_per_night")
    check_in_raw, _ci = req_date(data, "check_in_date")
    night_count = req_int(data, "night_count")
    cutoff_raw, _co = req_date(data, "cutoff_date")
    attrition = opt_int(data, "attrition_allowance_pct", 10)
    trip_must_be_draft(trip)
    block = new_resource()
    block.update(
        {
            "trip_id": trip["id"],
            "hotel_code": hotel_code,
            "room_count": room_count,
            "rate_cents_per_night": rate,
            "check_in_date": check_in_raw,
            "night_count": night_count,
            "cutoff_date": cutoff_raw,
            "rooms_released": 0,
            "posture": "HOLDING",
            "attrition_allowance_pct": attrition,
            "_kind": "block",
            "_attrition_penalty_cents": 0,
            "_attrition_at": None,
            "_locked_at": None,
        }
    )
    STORE["blocks"][block["id"]] = block
    finalize_trip(trip, enumerated=True)
    return ok(public(block), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/hotel-blocks", methods=["GET"])
def list_blocks(teamId, tripId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    items = calc.trip_blocks(trip)
    page, total, limit, offset = paginate(items)
    return ok_list([public(b) for b in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>", methods=["GET"])
def get_block(teamId, tripId, blockId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    return ok(public(block), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/lock", methods=["POST"])
def lock_block(teamId, tripId, blockId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    data = body()
    expected = req_version(data, "expected_block_version")
    check_version(block, expected)
    trip_not_terminal(trip)
    if block["posture"] != "NAME_LIST_DUE":
        raise ApiError(
            "ERR_BLOCK_NOT_NAME_LIST_DUE", 409, "Hotel block must be in NAME_LIST_DUE posture"
        )
    # State-machine preconditions (priority 6).
    members = calc.in_members(trip)
    blocks = calc.trip_blocks(trip)
    block_ids = {b["id"] for b in blocks}
    trip_non_cancelled = [
        r
        for r in STORE["rooms"].values()
        if r["hotel_block_id"] in block_ids and r["status"] != "CANCELLED"
    ]
    for m in members:
        if m["requires_single_room"]:
            ok_single = any(
                r["member_id"] == m["id"] and r.get("roommate_member_id") is None
                for r in trip_non_cancelled
            )
            if not ok_single:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "Single-room member lacks a roommate-free assignment",
                )
        covered = any(r["member_id"] == m["id"] for r in trip_non_cancelled)
        if not covered:
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Every IN member requires a non-CANCELLED room assignment",
            )
    block_non_cancelled = [
        r
        for r in calc.block_rooms(block)
        if r["status"] != "CANCELLED"
    ]
    attrition_floor = calc.allowed_slippage_rooms(block)
    if len(block_non_cancelled) < block["room_count"] - block["rooms_released"] - attrition_floor:
        raise ApiError("ERR_INVALID_STATE", 409, "Room assignment count below attrition floor")
    # Hotel cutoff (priority 13).
    if cutoff_passed(block):
        raise ApiError("ERR_CUTOFF_PASSED", 409, "Hotel cutoff_date has passed; room names locked")
    block["posture"] = "LOCKED"
    block["_locked_at"] = fmt_ts(clock_now())
    bump(block)
    amount = (block["room_count"] - block["rooms_released"]) * block["rate_cents_per_night"] * block["night_count"]
    calc.log_financial_event(trip, fmt_ts(clock_now()), amount)
    finalize_trip(trip, enumerated=True)
    return ok(public(block), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/release", methods=["POST"])
def release_block(teamId, tripId, blockId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    data = body()
    rooms_to_release = req_int(data, "rooms_to_release")
    trip_not_terminal(trip)
    if block["posture"] not in ("HOLDING", "NAME_LIST_DUE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Only HOLDING or NAME_LIST_DUE blocks may be released")
    if any(r["status"] == "CHECKED_IN" for r in calc.block_rooms(block)):
        raise ApiError("ERR_INVALID_STATE", 409, "Cannot release with a CHECKED_IN room assignment")
    if rooms_to_release < 1:
        raise invalid("rooms_to_release must be at least 1")
    occupied = calc.occupied_rooms(block)
    available = block["room_count"] - block["rooms_released"] - occupied
    if rooms_to_release > available:
        raise invalid("rooms_to_release exceeds releasable rooms")
    if rooms_to_release == available:
        # Full release closes the block.
        block["rooms_released"] = block["room_count"] - occupied
        block["posture"] = "CLOSED"
        bump(block)
        for r in calc.block_rooms(block):
            if r["status"] in ("RESERVED", "CONFIRMED"):
                r["status"] = "CANCELLED"
                bump(r)
    else:
        block["rooms_released"] += rooms_to_release
        bump(block)
        # Partial release may expose attrition.
        if block["posture"] in ("HOLDING", "NAME_LIST_DUE"):
            penalty = calc.attrition_penalty_cents(block)
            if penalty > 0:
                block["posture"] = "ATTRITION_EXPOSED"
                block["_attrition_penalty_cents"] = penalty
                block["_attrition_at"] = fmt_ts(clock_now())
                calc.log_financial_event(trip, fmt_ts(clock_now()), penalty)
                bump(block)
    finalize_trip(trip)
    return ok(public(block), 200)


# ---------------------------------------------------------------------------
# Room assignments
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/rooms", methods=["POST"])
def create_room(teamId, tripId, blockId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    data = body()
    member_id = req_str(data, "member_id")
    roommate_id = opt_str(data, "roommate_member_id", None)
    room_label = req_str(data, "room_label")
    smoking = opt_bool(data, "smoking_pref", False)
    trip_not_terminal(trip)
    if block["posture"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Hotel block is CLOSED")
    member = resolve_member(trip, member_id)
    roommate = None
    if roommate_id is not None:
        roommate = resolve_member(trip, roommate_id)
    # Hotel cutoff guards room creation (priority 13).
    if cutoff_passed(block):
        raise ApiError("ERR_CUTOFF_PASSED", 409, "Hotel cutoff_date has passed; room names locked")
    room = new_resource()
    room.update(
        {
            "hotel_block_id": block["id"],
            "member_id": member["id"],
            "roommate_member_id": roommate["id"] if roommate else None,
            "room_label": room_label,
            "smoking_pref": smoking,
            "status": "RESERVED",
            "confirmed_at": None,
            "_kind": "room",
        }
    )
    STORE["rooms"][room["id"]] = room
    return ok(public(room), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/rooms", methods=["GET"])
def list_rooms(teamId, tripId, blockId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    items = calc.block_rooms(block)
    if g.user_role == "TeamMember":
        items = [
            r
            for r in items
            if r["member_id"] == g.user_id or r.get("roommate_member_id") == g.user_id
        ]
    items = apply_filters(items, ["member_id", "roommate_member_id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(r) for r in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/rooms", methods=["GET"])
def list_rooms_by_member(teamId, tripId, memberId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    if g.user_role == "TeamMember":
        util.check_team_member_owns(member["id"])
    block_ids = {b["id"] for b in calc.trip_blocks(trip)}
    items = [
        r
        for r in STORE["rooms"].values()
        if r["hotel_block_id"] in block_ids
        and (r["member_id"] == member["id"] or r.get("roommate_member_id") == member["id"])
    ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total, limit, offset = paginate(items)
    return ok_list([public(r) for r in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/rooms/<roomId>", methods=["GET"])
def get_room(teamId, tripId, blockId, roomId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    room = resolve_room(block, roomId)
    team_member_read_guard(room)
    return ok(public(room), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/rooms/<roomId>/confirm",
    methods=["POST"],
)
def confirm_room(teamId, tripId, blockId, roomId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    room = resolve_room(block, roomId)
    body()
    trip_not_terminal(trip)
    if room["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Room assignment must be RESERVED to confirm")
    member = STORE["members"][room["member_id"]]
    # Roommate compatibility (priority 10) before cutoff (priority 13).
    roommate_id = room.get("roommate_member_id")
    if member["requires_single_room"] and roommate_id is not None:
        raise ApiError(
            "ERR_ROOMMATE_INCOMPATIBLE",
            409,
            "requires_single_room member may never be assigned a roommate",
        )
    if roommate_id is not None:
        roommate = STORE["members"][roommate_id]
        if roommate["status"] != "IN":
            raise ApiError(
                "ERR_ROOMMATE_INCOMPATIBLE", 409, "Roommate status is not IN"
            )
        if roommate["requires_single_room"]:
            raise ApiError(
                "ERR_ROOMMATE_INCOMPATIBLE",
                409,
                "Roommate is flagged requires_single_room",
            )
        if calc.ROOM_GROUP.get(roommate["party_role"]) != calc.ROOM_GROUP.get(member["party_role"]):
            raise ApiError(
                "ERR_ROOMMATE_INCOMPATIBLE", 409, "Roommate party_role group incompatible"
            )
    # Hotel cutoff (priority 13).
    if cutoff_passed(block):
        raise ApiError("ERR_CUTOFF_PASSED", 409, "Hotel cutoff_date has passed; room names locked")
    # Referenced-target state (priority 15): member must be IN.
    if member["status"] != "IN":
        raise ApiError("ERR_MEMBER_NOT_IN", 409, "Referenced member status is not IN")
    room["status"] = "CONFIRMED"
    room["confirmed_at"] = fmt_ts(clock_now())
    bump(room)
    return ok(public(room), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/rooms/<roomId>/checkin",
    methods=["POST"],
)
def checkin_room(teamId, tripId, blockId, roomId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    room = resolve_room(block, roomId)
    body()
    trip_not_terminal(trip)
    if room["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Room assignment must be CONFIRMED to check in")
    if block["posture"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Hotel block must be LOCKED to check in")
    room["status"] = "CHECKED_IN"
    bump(room)
    return ok(public(room), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/rooms/<roomId>/checkout",
    methods=["POST"],
)
def checkout_room(teamId, tripId, blockId, roomId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    room = resolve_room(block, roomId)
    body()
    trip_not_terminal(trip)
    if room["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Room assignment must be CHECKED_IN to check out")
    room["status"] = "CHECKED_OUT"
    bump(room)
    return ok(public(room), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/hotel-blocks/<blockId>/rooms/<roomId>/cancel",
    methods=["POST"],
)
def cancel_room(teamId, tripId, blockId, roomId):
    require_role("TravelCoordinator")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    block = resolve_block(trip, blockId)
    room = resolve_room(block, roomId)
    body()
    trip_not_terminal(trip)
    if room["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Only RESERVED or CONFIRMED assignments may be cancelled")
    room["status"] = "CANCELLED"
    bump(room)
    return ok(public(room), 200)
