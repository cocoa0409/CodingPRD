"""RehearsalSlot endpoints."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_id, next_seq
from errors import (
    ERR_SLOT_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_CONTRACT_NOT_REHEARSABLE,
    ERR_SLOT_NOT_RECORDABLE,
    ERR_SLOT_NOT_CANCELLABLE,
    ERR_REHEARSAL_OVERLAP,
    ApiError,
    conflict,
)
from middleware import (
    require_roles,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import REHEARSAL_TURNOVER
from util import req, check_unknown, new_record, mutate, public_view, hours_between

bp = Blueprint("rehearsal_slots", __name__)

CREATE_FIELDS = {"contract_id", "stage_name", "start_time", "end_time"}
OUTCOMES = {"ATTENDED", "NO_SHOW"}


def load_slot(sid):
    return load(store.slots, sid, ERR_SLOT_NOT_FOUND, "rehearsal slot")


@bp.route("/rehearsal-slots", methods=["POST"])
def create_slot():
    require_roles("CastDirector")
    body = get_body()
    if isinstance(body.get("contract_id"), str):
        load(store.contracts, body["contract_id"], ERR_CONTRACT_NOT_FOUND, "cast contract")
    check_unknown(body, CREATE_FIELDS)
    contract_id = req(body, "contract_id", "str")
    stage_name = req(body, "stage_name", "str")
    start = req(body, "start_time", "dt")
    end = req(body, "end_time", "dt")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_time must be > start_time")

    contract = store.contracts[contract_id]
    if contract["status"] not in ("ACCEPTED", "REHEARSING"):
        raise conflict(
            ERR_CONTRACT_NOT_REHEARSABLE, "slot creation requires contract ACCEPTED or REHEARSING"
        )
    # Buffered overlap: each slot occupies [start, end + 15min) on its stage.
    new_start, new_end = start, end + REHEARSAL_TURNOVER
    for other in store.slots.values():
        if other["stage_name"] != stage_name:
            continue
        if other["status"] not in ("SCHEDULED", "ATTENDED"):
            continue
        ex_start, ex_end = other["start_time"], other["end_time"] + REHEARSAL_TURNOVER
        if new_start < ex_end and ex_start < new_end:
            raise conflict(ERR_REHEARSAL_OVERLAP, "stage is occupied in that window")

    slot = new_record()
    slot.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "contract_id": contract_id,
            "stage_name": stage_name,
            "start_time": start,
            "end_time": end,
            "status": "SCHEDULED",
            "hours_credit": Decimal(0),
        }
    )
    store.slots[slot["id"]] = slot
    return obj_response(public_view(slot), 201)


@bp.route("/rehearsal-slots", methods=["GET"])
def list_slots():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.slots),
        [("contract_id", "contract_id"), ("stage_name", "stage_name"), ("status", "status")],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(s) for s in page], limit, offset, total)


@bp.route("/rehearsal-slots/<sid>", methods=["GET"])
def get_slot(sid):
    require_roles()
    return obj_response(public_view(load_slot(sid)))


@bp.route("/rehearsal-slots/<sid>/record-attendance", methods=["POST"])
def record_attendance(sid):
    require_roles("CastDirector")
    slot = load_slot(sid)
    body = get_body()
    check_unknown(body, {"outcome"})
    outcome = req(body, "outcome", "enum", enum=OUTCOMES)
    if slot["status"] != "SCHEDULED":
        raise conflict(ERR_SLOT_NOT_RECORDABLE, "record-attendance requires SCHEDULED")
    if outcome == "ATTENDED":
        credit = hours_between(slot["start_time"], slot["end_time"])
        mutate(slot, status="ATTENDED", hours_credit=credit)
        contract = store.contracts[slot["contract_id"]]
        changes = {
            "completed_rehearsal_hours": contract["completed_rehearsal_hours"] + credit
        }
        if contract["status"] == "ACCEPTED":
            changes["status"] = "REHEARSING"
        mutate(contract, **changes)
    else:  # NO_SHOW
        mutate(slot, status="NO_SHOW")
    return obj_response(public_view(slot))


@bp.route("/rehearsal-slots/<sid>/cancel", methods=["POST"])
def cancel_slot(sid):
    require_roles("CastDirector")
    slot = load_slot(sid)
    check_unknown(get_body(), set())
    if slot["status"] != "SCHEDULED":
        raise conflict(ERR_SLOT_NOT_CANCELLABLE, "cancel requires SCHEDULED")
    mutate(slot, status="CANCELLED")
    return obj_response(public_view(slot))
