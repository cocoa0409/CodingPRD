from flask import Blueprint, request

from db import store, base_record
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_DUPLICATE,
    ERR_REFERENTIAL_MISMATCH,
)
from middleware import auth, require_roles
from response import ok_obj, ok_list, parse_pagination, paged
from services import CRAFTS, append_slot
from validators import body, req_str, req_enum, req_int

bp = Blueprint("boards", __name__)


def _get_board(board_id):
    b = store.boards.get(board_id)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ExtraBoard '%s' not found." % board_id)
    return b


@bp.post("/api/extra-boards")
def create_board():
    data = body()
    board_code = req_str(data, "board_code")
    craft = req_enum(data, "craft", CRAFTS)
    terminal = req_str(data, "terminal")
    guaranteed_slots = req_int(data, "guaranteed_slots", min_value=0)
    _, role = auth()
    require_roles(role, ("CrewManager",))
    if any(b["board_code"] == board_code for b in store.boards.values()):
        raise ApiError(ERR_DUPLICATE, 409, "board_code already exists.")
    rec = base_record()
    rec.update({
        "board_code": board_code,
        "craft": craft,
        "terminal": terminal,
        "guaranteed_slots": guaranteed_slots,
    })
    store.boards[rec["id"]] = rec
    return ok_obj(rec, 201)


@bp.get("/api/extra-boards/<board_id>")
def get_board(board_id):
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller"))
    return ok_obj(_get_board(board_id))


@bp.get("/api/extra-boards/<board_id>/slots")
def list_board_slots(board_id):
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller"))
    _get_board(board_id)
    rows = [s for s in store.slots.values() if s["board_id"] == board_id]
    slot_status = request.args.get("slot_status")
    if slot_status is not None:
        rows = [s for s in rows if s["slot_status"] == slot_status]
    # Board slots are listed ordered by standing_position (PRD §3.1);
    # VACATED slots (position released -> None) sort last.
    rows.sort(key=lambda s: (
        s["standing_position"] is None,
        s["standing_position"] if s["standing_position"] is not None else 0,
        s["created_at"],
        s["_seq"],
    ))
    limit, offset = parse_pagination(request.args)
    total = len(rows)
    return ok_list(rows[offset:offset + limit], total, limit, offset)


@bp.post("/api/extra-boards/<board_id>/slots")
def create_slot(board_id):
    data = body()
    employee_id = req_str(data, "employee_id")
    _, role = auth()
    require_roles(role, ("CrewManager",))
    board = _get_board(board_id)
    emp = store.employees.get(employee_id)
    if emp is None:
        raise ApiError(
            ERR_REFERENTIAL_MISMATCH, 422,
            "employee_id does not reference an existing Employee.",
        )
    if emp["craft"] != board["craft"]:
        raise ApiError(
            ERR_REFERENTIAL_MISMATCH, 422,
            "Employee craft does not match the board craft.",
        )
    if any(
        s["board_id"] == board_id
        and s["employee_id"] == employee_id
        and s["slot_status"] in ("ACTIVE", "FROZEN")
        for s in store.slots.values()
    ):
        raise ApiError(
            ERR_DUPLICATE, 409,
            "Employee already holds an ACTIVE or FROZEN slot on this board.",
        )
    slot = append_slot(board_id, employee_id)
    return ok_obj(slot, 201)


@bp.get("/api/extra-board-slots")
def list_slots():
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller"))
    rows = list(store.slots.values())
    board_id = request.args.get("board_id")
    if board_id is not None:
        rows = [s for s in rows if s["board_id"] == board_id]
    employee_id = request.args.get("employee_id")
    if employee_id is not None:
        rows = [s for s in rows if s["employee_id"] == employee_id]
    slot_status = request.args.get("slot_status")
    if slot_status is not None:
        rows = [s for s in rows if s["slot_status"] == slot_status]
    return paged(rows, request.args)


@bp.get("/api/extra-board-slots/<slot_id>")
def get_slot(slot_id):
    _, role = auth()
    require_roles(role, ("CrewManager", "CrewCaller"))
    slot = store.slots.get(slot_id)
    if slot is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ExtraBoardSlot '%s' not found." % slot_id)
    return ok_obj(slot)
