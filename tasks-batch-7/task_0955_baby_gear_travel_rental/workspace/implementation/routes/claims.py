from flask import Blueprint

import calc
from db import bump, create_rec, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj
from serialize import ser_claim
from validate import req_enum, req_int, req_str

bp = Blueprint("claims", __name__)

SEVERITIES = ("COSMETIC", "MINOR", "MAJOR", "TOTAL_LOSS")


def _get_claim(cid):
    c = store.claims.get(cid)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Damage claim not found")
    return c


def _claim_line(claim):
    return store.lines[claim["reservation_line_id"]]


def _claim_reservation(claim):
    return store.reservations[_claim_line(claim)["reservation_id"]]


def _segregation_of_duties(claim, uid):
    if claim["filed_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Reviewer must differ from the filer")


@bp.post("/damage-claims")
def create_claim():
    uid, _ = require_roles("Inspector", "OperationsAdmin")
    b = body()
    line_id = b.get("reservation_line_id")
    if not isinstance(line_id, str) or not line_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "reservation_line_id is required")
    line = store.lines.get(line_id)
    if line is None:
        raise ApiError("ERR_LINE_NOT_FOUND", 404, "Reservation line not found")
    severity = req_enum(b, "severity", SEVERITIES)
    repair = req_int(b, "repair_cost_cents")
    if repair < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "repair_cost_cents must be >= 0")
    description = req_str(b, "description")
    if line["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Damage claims may only be filed against a RETURNED line")
    rec = create_rec(store.claims, {
        "reservation_line_id": line["id"], "severity": severity,
        "repair_cost_cents": repair, "description": description,
        "filed_by_user_id": uid, "reviewed_by_user_id": None,
        "status": "UNDER_REVIEW", "capture_amount_cents": 0})
    return ok_obj(ser_claim(rec), 201)


@bp.get("/damage-claims/<cid>")
def get_claim(cid):
    uid, role = require_roles("Customer", "Inspector", "OperationsAdmin")
    claim = _get_claim(cid)
    if role == "Customer" and _claim_reservation(claim)["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    return ok_obj(ser_claim(claim))


@bp.post("/damage-claims/<cid>/approve")
def approve_claim(cid):
    uid, _ = require_roles("OperationsAdmin")
    claim = _get_claim(cid)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW")
    line = _claim_line(claim)
    res = store.reservations[line["reservation_id"]]
    if line["status"] != "RETURNED" or res["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Approval requires a RETURNED line on a RETURNED reservation")
    _segregation_of_duties(claim, uid)
    claim["capture_amount_cents"] = calc.damage_capture_amount(claim, line)
    claim["reviewed_by_user_id"] = uid
    claim["status"] = "APPROVED"
    bump(claim)
    return ok_obj(ser_claim(claim))


@bp.post("/damage-claims/<cid>/deny")
def deny_claim(cid):
    uid, _ = require_roles("OperationsAdmin")
    claim = _get_claim(cid)
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not UNDER_REVIEW")
    _segregation_of_duties(claim, uid)
    claim["reviewed_by_user_id"] = uid
    claim["status"] = "DENIED"
    bump(claim)
    return ok_obj(ser_claim(claim))


@bp.post("/damage-claims/<cid>/dispute")
def dispute_claim(cid):
    uid, _ = require_roles("Customer")
    claim = _get_claim(cid)
    if _claim_reservation(claim)["customer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not DENIED")
    claim["status"] = "DISPUTED"
    bump(claim)
    return ok_obj(ser_claim(claim))


@bp.post("/damage-claims/<cid>/reopen")
def reopen_claim(cid):
    require_roles("OperationsAdmin")
    claim = _get_claim(cid)
    if claim["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not DISPUTED")
    claim["reviewed_by_user_id"] = None
    claim["status"] = "UNDER_REVIEW"
    bump(claim)
    return ok_obj(ser_claim(claim))
