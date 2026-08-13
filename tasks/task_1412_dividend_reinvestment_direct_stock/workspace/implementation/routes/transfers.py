"""Transfer instruction endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ADMIN, ANY_ROLE, PARTICIPANT, auth, check_ownership
from response import ok
from services import (
    TRANSFER_STATUSES,
    TRANSFER_TYPES,
    execute_transfer,
    filter_enum,
    get_enrollment,
    get_plan,
    get_transfer,
    list_response,
    ser_transfer,
    stamp,
    touch,
)
from util import as_enum, as_pos_int, as_decimal, body, required, round4

bp = Blueprint("transfers", __name__)


def _recipient_error(msg):
    return ApiError("ERR_RECIPIENT_NOT_ENROLLED", 422, msg)


@bp.post("/enrollments/<enrollment_id>/transfers")
def create_transfer(enrollment_id):
    user_id, role = auth(PARTICIPANT)
    source = get_enrollment(enrollment_id)
    check_ownership(source["participant_id"], user_id, role)
    data = body()
    transfer_type = as_enum(
        required(data, "transfer_type"), "transfer_type", TRANSFER_TYPES
    )
    quantity = round4(as_decimal(required(data, "quantity"), "quantity"))
    if quantity <= 0:
        raise ApiError("ERR_VALIDATION", 400, "quantity must be > 0")
    plan = get_plan(source["plan_id"])
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    if source["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment is not ACTIVE"
        )
    # Sufficient-shares check (repeated at execution time).
    if quantity > source["share_balance"]:
        raise ApiError(
            "ERR_INSUFFICIENT_SHARES",
            422,
            "Transfer quantity exceeds source enrollment share_balance",
        )
    recipient_id = data.get("recipient_enrollment_id")
    recipient_name = data.get("recipient_name")
    recipient_address = data.get("recipient_address")
    if transfer_type == "TRANSFER":
        if recipient_id is None:
            raise _recipient_error(
                "recipient_enrollment_id is required for TRANSFER"
            )
        if recipient_name is not None or recipient_address is not None:
            raise _recipient_error(
                "recipient_name/recipient_address must be null for TRANSFER"
            )
        recipient = DB["enrollments"].get(recipient_id)
        if (
            recipient is None
            or recipient["plan_id"] != source["plan_id"]
            or recipient["status"] != "ACTIVE"
        ):
            raise _recipient_error(
                "Recipient enrollment is missing, in another plan, or not "
                "ACTIVE"
            )
    else:  # GIFT
        if recipient_id is not None:
            raise _recipient_error(
                "recipient_enrollment_id must be null for GIFT"
            )
        if (
            not isinstance(recipient_name, str)
            or not recipient_name
            or not isinstance(recipient_address, str)
            or not recipient_address
        ):
            raise _recipient_error(
                "recipient_name and recipient_address are required for GIFT"
            )
    rec = {
        "id": new_id(),
        "source_enrollment_id": enrollment_id,
        "recipient_enrollment_id": (
            recipient_id if transfer_type == "TRANSFER" else None
        ),
        "transfer_type": transfer_type,
        "quantity": quantity,
        "recipient_name": recipient_name if transfer_type == "GIFT" else None,
        "recipient_address": (
            recipient_address if transfer_type == "GIFT" else None
        ),
        "status": "SUBMITTED",
        "fmv_per_share_cents": None,
        "executed_at": None,
    }
    stamp(rec)
    DB["transfers"][rec["id"]] = rec
    return ok(ser_transfer(rec), status=201)


@bp.get("/transfer-instructions/<tid>")
def get_one_transfer(tid):
    user_id, role = auth(ANY_ROLE)
    t = get_transfer(tid)
    source = get_enrollment(t["source_enrollment_id"])
    check_ownership(source["participant_id"], user_id, role)
    return ok(ser_transfer(t))


@bp.get("/transfer-instructions")
def list_transfers():
    auth(ADMIN)
    items = list(DB["transfers"].values())
    recipient_id = request.args.get("recipient_enrollment_id")
    if recipient_id is not None:
        items = [t for t in items if t["recipient_enrollment_id"] == recipient_id]
    source_id = request.args.get("source_enrollment_id")
    if source_id is not None:
        items = [t for t in items if t["source_enrollment_id"] == source_id]
    items = filter_enum(
        items, request.args.get("status"), "status", TRANSFER_STATUSES, "status"
    )
    return list_response(items, ser_transfer)


@bp.post("/transfer-instructions/<tid>/execute")
def execute_transfer_route(tid):
    auth(ADMIN)
    t = get_transfer(tid)
    data = body()
    fmv = as_pos_int(
        required(data, "fmv_per_share_cents"), "fmv_per_share_cents"
    )
    if t["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Instruction is not SUBMITTED")
    source = get_enrollment(t["source_enrollment_id"])
    plan = get_plan(source["plan_id"])
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", 409, "Plan is not ACTIVE")
    if source["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE", 409, "Source enrollment is not ACTIVE"
        )
    if t["quantity"] > source["share_balance"]:
        raise ApiError(
            "ERR_INSUFFICIENT_SHARES",
            422,
            "Transfer quantity exceeds source enrollment share_balance",
        )
    if t["transfer_type"] == "TRANSFER":
        recipient = DB["enrollments"].get(t["recipient_enrollment_id"])
        if (
            recipient is None
            or recipient["plan_id"] != source["plan_id"]
            or recipient["status"] != "ACTIVE"
        ):
            raise _recipient_error(
                "Recipient enrollment is missing, in another plan, or not "
                "ACTIVE"
            )
    execute_transfer(t, fmv)
    return ok(ser_transfer(t))


@bp.post("/transfer-instructions/<tid>/cancel")
def cancel_transfer(tid):
    user_id, role = auth(PARTICIPANT)
    t = get_transfer(tid)
    source = get_enrollment(t["source_enrollment_id"])
    check_ownership(source["participant_id"], user_id, role)
    if t["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Instruction is not SUBMITTED")
    t["status"] = "CANCELLED"
    touch(t)
    return ok(ser_transfer(t))
