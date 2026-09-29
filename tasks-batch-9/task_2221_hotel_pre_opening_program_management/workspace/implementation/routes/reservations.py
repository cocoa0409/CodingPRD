"""Reservation block endpoints (PRD §3.8)."""
from flask import Blueprint

import clock
import db
import guards
import repo
import response
import tx
import validate as v
from db import db as store
from errors import ApiError
from middleware import ALL_ROLES, require
from services import derive

bp = Blueprint("reservations", __name__)


@bp.post("/pre-opening/reservation-blocks")
@require("CommercialDirector")
def create_block():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    account_name = v.req_str(body, "account_name", 1, 120)
    arrival_raw, arrival_date = v.req_date(body, "arrival_date")
    night_count = v.req_int(body, "night_count", minimum=1, maximum=30)
    room_count = v.req_int(body, "room_count", minimum=1)
    rate_cents = v.req_int(body, "rate_cents", minimum=0)
    expected_version = v.req_int(body, "expected_program_version", minimum=1)

    program = repo.get_program(program_id)
    guards.ensure_not_stabilized(program)
    if program["commercial_state"] != "BOOKING_OPEN":
        raise ApiError("ERR_BOOKING_NOT_OPEN")
    if program["version"] != expected_version:
        raise ApiError("ERR_STALE_PROGRAM_VERSION")
    guards.ensure_not_frozen(program)
    if arrival_date < clock.today():
        raise ApiError("ERR_ARRIVAL_DATE_IN_PAST")

    room_nights = room_count * night_count
    if program["committed_room_nights"] + room_nights > program["room_night_ceiling"]:
        raise ApiError("ERR_ROOM_NIGHT_CEILING_EXCEEDED")
    projected = program["contingency_liability_cents"]
    if derive.is_pre_opening(program, arrival_raw):
        projected += derive.contingency_for(program, room_count, night_count, "ACCEPTED")
    if projected > program["contingency_liability_cap_cents"]:
        raise ApiError("ERR_CONTINGENCY_LIABILITY_EXCEEDED")

    ts = db.stamp()
    block = {
        "id": db.new_id(),
        "program_id": program_id,
        "account_name": account_name,
        "arrival_date": arrival_raw,
        "night_count": night_count,
        "room_count": room_count,
        "rate_cents": rate_cents,
        "room_nights": room_nights,
        "revenue_cents": room_nights * rate_cents,
        "is_pre_opening": False,
        "contingency_cents": 0,
        "state": "ACCEPTED",
        "at_risk_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.reservation_blocks[block["id"]] = block
    derive.reconcile(program)
    tx.commit(program["id"])
    return response.created(repo.serialize(block))


@bp.get("/pre-opening/programs/<program_id>/reservation-blocks")
@require(*ALL_ROLES)
def list_blocks(program_id):
    program = repo.get_program(program_id)
    state = v.q_enum("state", repo.BLOCK_STATES)
    is_pre_opening = v.q_bool("is_pre_opening")
    items = repo.blocks_of(program["id"])
    if state:
        items = [b for b in items if b["state"] == state]
    if is_pre_opening is not None:
        items = [b for b in items if bool(b["is_pre_opening"]) == is_pre_opening]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.post("/pre-opening/reservation-blocks/<block_id>/guarantee")
@require("CommercialDirector")
def guarantee_block(block_id):
    block = repo.get_block(block_id)
    program = repo.get_program(block["program_id"])
    guards.ensure_not_stabilized(program)
    if block["state"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_RESERVATION_STATE",
                       "Only an ACCEPTED block may be guaranteed.")
    if program["commercial_state"] != "BOOKING_OPEN":
        raise ApiError("ERR_BOOKING_NOT_OPEN")
    guards.ensure_not_frozen(program)

    block["state"] = "GUARANTEED"
    derive.reconcile(program)
    tx.commit()
    return response.ok(repo.serialize(block))


@bp.post("/pre-opening/reservation-blocks/<block_id>/resolve-contingency")
@require("CommercialDirector")
def resolve_contingency(block_id):
    body = v.body()
    resolution = v.req_enum(body, "resolution", ("RELOCATE", "CANCEL"))
    block = repo.get_block(block_id)
    program = repo.get_program(block["program_id"])
    guards.ensure_not_stabilized(program)
    if block["state"] != "AT_RISK":
        raise ApiError("ERR_INVALID_RESERVATION_STATE",
                       "Only an AT_RISK block may have its contingency resolved.")

    if resolution == "RELOCATE":
        # contingency_cents stays frozen at the value paid out
        block["state"] = "RELOCATED"
    else:
        block["state"] = "CANCELLED"
        block["contingency_cents"] = 0
    block["at_risk_reason"] = None
    derive.reconcile(program)
    tx.commit()
    return response.ok(repo.serialize(block))
