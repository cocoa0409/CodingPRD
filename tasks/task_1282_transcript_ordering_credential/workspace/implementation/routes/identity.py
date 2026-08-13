"""IdentityVerification endpoints."""
import secrets
import string
from datetime import timedelta

from flask import Blueprint, request

from db import DB, new_id, logical_now_iso, parse_iso
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    IDV_METHODS,
    _cancel_order_internal,
    advance_order_ready,
    blocking_hold_exists,
    emit_audit,
    get_idv,
    get_order,
    idvs_of_order,
    logical_now,
    order_blocks_on_hold,
    ref_lookup,
    ser_idv,
    sorted_created,
    touch,
)
from util import as_enum, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("identity", __name__)

READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]
_ALPHABET = string.ascii_letters + string.digits


def _mint_token():
    return "".join(secrets.choice(_ALPHABET) for _ in range(32))


@bp.post("/registrar/identity-verifications")
def start_idv():
    user_id, role = auth(["Student"])
    data = body()
    reject_unknown_fields(data, {"student_id", "order_id", "method"})
    student_id = required(data, "student_id")
    order_id = required(data, "order_id")
    method = as_enum(required(data, "method"), "method", IDV_METHODS)
    ref_lookup("students", student_id, "Student")
    order = ref_lookup("orders", order_id, "TranscriptOrder")

    now = logical_now()
    rec = {
        "id": new_id(),
        "student_id": student_id,
        "order_id": order_id,
        "method": method,
        "status": "PENDING",
        "verification_token": _mint_token(),
        "expires_at": None,
        "created_at": logical_now_iso(),
    }
    rec["expires_at"] = _iso(now + timedelta(hours=72))
    DB["identity_verifications"][rec["id"]] = rec

    # Cascade: a bound order sitting in SUBMITTED moves to IDENTITY_PENDING.
    if order["fulfillment_status"] == "SUBMITTED":
        order["fulfillment_status"] = "IDENTITY_PENDING"
        touch(order)

    return ok(ser_idv(rec), status=201)


def _iso(dt):
    from db import to_iso_ms

    return to_iso_ms(dt)


@bp.get("/registrar/identity-verifications/<vid>")
def get_one_idv(vid):
    auth(READ_ROLES)
    return ok(ser_idv(get_idv(vid)))


@bp.get("/registrar/students/<sid>/identity-verifications")
def list_student_idvs(sid):
    auth(READ_ROLES)
    from services import get_student

    get_student(sid)
    limit, offset = pagination_args()
    items = [
        v
        for v in DB["identity_verifications"].values()
        if v["student_id"] == sid
    ]
    st = request.args.get("status")
    if st is not None:
        items = [v for v in items if v["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_idv(v) for v in page], total, limit, offset)


@bp.get("/registrar/orders/<oid>/identity-verifications")
def list_order_idvs(oid):
    auth(READ_ROLES)
    get_order(oid)
    limit, offset = pagination_args()
    items = idvs_of_order(oid)
    st = request.args.get("status")
    if st is not None:
        items = [v for v in items if v["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_idv(v) for v in page], total, limit, offset)


@bp.post("/registrar/identity-verifications/<vid>/confirm")
def confirm_idv(vid):
    user_id, role = auth(["Student"])
    rec = get_idv(vid)
    data = body()
    reject_unknown_fields(data, {"verification_token"})
    token = required(data, "verification_token")
    if not isinstance(token, str):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "verification_token must be a string"
        )
    # PRD 3.4: a confirm attempted after expiry is ERR_VERIFICATION_EXPIRED,
    # which outranks the generic not-PENDING state check for EXPIRED records.
    if rec["status"] == "EXPIRED" or logical_now() >= parse_iso(rec["expires_at"]):
        raise ApiError(
            "ERR_VERIFICATION_EXPIRED", 422, "IdentityVerification has expired"
        )
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "IdentityVerification is not PENDING")
    if rec["verification_token"] != token:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "verification_token does not match"
        )
    rec["status"] = "VERIFIED"
    emit_audit("IdentityVerification", rec["id"], role, user_id, "IDENTITY_VERIFIED")

    # Cascade: bound order leaves IDENTITY_PENDING.
    order = DB["orders"].get(rec["order_id"])
    if order is not None and order["fulfillment_status"] == "IDENTITY_PENDING":
        if order_blocks_on_hold(order):
            order["fulfillment_status"] = "HOLD_CHECK"
            touch(order)
        else:
            advance_order_ready(order)
    return ok(ser_idv(rec))


@bp.post("/registrar/identity-verifications/<vid>/reject")
def reject_idv(vid):
    user_id, role = auth(["RegistrarReviewer"])
    rec = get_idv(vid)
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "IdentityVerification is not PENDING")
    rec["status"] = "REJECTED"
    emit_audit("IdentityVerification", rec["id"], role, user_id, "IDENTITY_REJECTED")

    # Cascade: bound order in IDENTITY_PENDING is cancelled.
    order = DB["orders"].get(rec["order_id"])
    if order is not None and order["fulfillment_status"] == "IDENTITY_PENDING":
        _cancel_order_internal(order)
    return ok(ser_idv(rec))
