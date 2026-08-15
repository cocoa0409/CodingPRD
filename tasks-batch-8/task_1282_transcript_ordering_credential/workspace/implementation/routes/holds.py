"""Hold endpoints."""
from flask import Blueprint, request

from db import DB, new_id, logical_now_iso
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    BLOCKING_SCOPES,
    HOLD_TYPES,
    emit_audit,
    get_hold,
    get_student,
    logical_now,
    reevaluate_hold_check_orders,
    ref_lookup,
    ser_hold,
    sorted_created,
    stamp,
    touch,
    blocking_hold_exists,
)
from util import as_enum, as_int, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("holds", __name__)

PLACE_ROLES = ["BursarOffice", "LibraryOffice", "RegistrarAdmin"]
READ_ROLES = [
    "RegistrarAdmin",
    "RegistrarOperator",
    "RegistrarReviewer",
    "BursarOffice",
    "LibraryOffice",
    "Student",
]
RELEASE_ROLES = ["BursarOffice", "LibraryOffice", "RegistrarAdmin"]

# Which office role may place / release which hold_type (PRD 3.2).
OFFICE_FOR_TYPE = {
    "FINANCIAL": "BursarOffice",
    "LIBRARY": "LibraryOffice",
    "REGISTRAR": "RegistrarAdmin",
    "DISCIPLINARY": "RegistrarAdmin",
}


@bp.post("/registrar/holds")
def place_hold():
    user_id, role = auth(PLACE_ROLES)
    data = body()
    reject_unknown_fields(data, {"student_id", "hold_type", "blocking_scope", "amount_cents"})
    student_id = required(data, "student_id")
    hold_type = as_enum(required(data, "hold_type"), "hold_type", HOLD_TYPES)
    blocking_scope = as_enum(
        required(data, "blocking_scope"), "blocking_scope", BLOCKING_SCOPES
    )
    amount_cents = data.get("amount_cents", 0)
    amount_cents = as_int(amount_cents, "amount_cents")
    if amount_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be >= 0")

    # Referenced FK existence (body-supplied).
    ref_lookup("students", student_id, "Student")

    # Office segregation: hold_type must be placed by its owning office.
    if OFFICE_FOR_TYPE[hold_type] != role:
        raise ApiError(
            "ERR_HOLD_OFFICE_MISMATCH",
            403,
            f"{hold_type} holds are placed only by {OFFICE_FOR_TYPE[hold_type]}",
        )

    rec = {
        "id": new_id(),
        "student_id": student_id,
        "hold_type": hold_type,
        "status": "ACTIVE",
        "blocking_scope": blocking_scope,
        "amount_cents": amount_cents,
        "placed_at": logical_now_iso(),
        "released_at": None,
    }
    stamp(rec)
    DB["holds"][rec["id"]] = rec

    # Cascade: SUBMITTED OFFICIAL orders on this student move to HOLD_CHECK when
    # this hold blocks them.
    if blocking_scope in ("ALL", "OFFICIAL"):
        for order in DB["orders"].values():
            if (
                order["student_id"] == student_id
                and order["fulfillment_status"] == "SUBMITTED"
                and order["order_kind"] == "OFFICIAL"
            ):
                order["fulfillment_status"] = "HOLD_CHECK"
                touch(order)

    return ok(ser_hold(rec), status=201)


@bp.get("/registrar/holds")
def list_holds():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["holds"].values())
    sid = request.args.get("student_id")
    if sid is not None:
        items = [h for h in items if h["student_id"] == sid]
    ht = request.args.get("hold_type")
    if ht is not None:
        items = [h for h in items if h["hold_type"] == ht]
    st = request.args.get("status")
    if st is not None:
        items = [h for h in items if h["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_hold(h) for h in page], total, limit, offset)


@bp.get("/registrar/students/<sid>/holds")
def list_student_holds(sid):
    auth(READ_ROLES)
    student = get_student(sid)
    limit, offset = pagination_args()
    items = [h for h in DB["holds"].values() if h["student_id"] == student["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [h for h in items if h["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_hold(h) for h in page], total, limit, offset)


@bp.get("/registrar/holds/<hid>")
def get_one_hold(hid):
    auth(READ_ROLES)
    return ok(ser_hold(get_hold(hid)))


@bp.post("/registrar/holds/<hid>/release")
def release_hold(hid):
    user_id, role = auth(RELEASE_ROLES)
    hold = get_hold(hid)
    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Hold is not ACTIVE")
    # Office segregation on release.
    if OFFICE_FOR_TYPE[hold["hold_type"]] != role:
        raise ApiError(
            "ERR_HOLD_OFFICE_MISMATCH",
            403,
            f"{hold['hold_type']} holds are released only by {OFFICE_FOR_TYPE[hold['hold_type']]}",
        )
    hold["status"] = "RELEASED"
    hold["released_at"] = logical_now_iso()
    touch(hold)
    emit_audit("Hold", hold["id"], role, user_id, "HOLD_RELEASED")
    # Depth-3 cascade: HOLD_CHECK orders on this student may now advance,
    # fanning their PENDING line items out to QUEUED.
    reevaluate_hold_check_orders(hold["student_id"])
    return ok(ser_hold(hold))
