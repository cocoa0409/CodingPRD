"""Voucher endpoints: estimate, issue, dispute, adjust (OCC-guarded)."""
from flask import Blueprint, request

from db import STORE, logical_now
from domain import ser_voucher, touch
from errors import (
    ApiError,
    ERR_BOOKING_NOT_WRAPPED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_STALE_VOUCHER_VERSION,
    ERR_VALIDATION,
    ERR_VOUCHER_INVALID_STATE,
    ERR_VOUCHER_NOT_FOUND,
)
from middleware import ALL_ROLES, auth, body
from response import ok_list, ok_obj, paginate
from services import compute_voucher_estimate, compute_voucher_final, eject_voucher_from_open_batch

bp = Blueprint("vouchers", __name__)


def get_voucher(vid):
    v = STORE.vouchers.get(vid)
    if v is None:
        raise ApiError(ERR_VOUCHER_NOT_FOUND, 404, "Voucher not found")
    return v


@bp.get("/central-casting/vouchers")
def list_vouchers():
    auth(ALL_ROLES)
    rows = sorted(STORE.vouchers.values(), key=lambda v: v["_seq"])
    for param in ("booking_id", "payroll_batch_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [v for v in rows if v.get(param) == value]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_voucher(v) for v in page], total, limit, offset)


@bp.get("/central-casting/vouchers/<vid>")
def get_voucher_route(vid):
    auth(ALL_ROLES)
    return ok_obj(ser_voucher(get_voucher(vid)))


@bp.get("/central-casting/vouchers/<vid>/estimate")
def estimate_voucher(vid):
    auth(ALL_ROLES)
    v = get_voucher(vid)
    if v["status"] == "PAID":
        raise ApiError(
            ERR_VOUCHER_INVALID_STATE, 409, "Estimates are available only before PAID"
        )
    return ok_obj(compute_voucher_estimate(v))


@bp.post("/central-casting/vouchers/<vid>/issue")
def issue_voucher(vid):
    user_id, _ = auth(["CastingAssociate"])
    v = get_voucher(vid)
    if v["status"] != "DRAFT":
        raise ApiError(ERR_VOUCHER_INVALID_STATE, 409, "Only a DRAFT voucher can be issued")
    booking = STORE.bookings[v["booking_id"]]
    if booking["status"] != "WRAPPED":
        raise ApiError(ERR_BOOKING_NOT_WRAPPED, 409, "Voucher issue requires a WRAPPED booking")
    compute_voucher_final(v)
    v["issued_by_user_id"] = user_id
    v["issued_at"] = logical_now()
    v["status"] = "ISSUED"
    touch(v)
    return ok_obj(ser_voucher(v))


@bp.post("/central-casting/vouchers/<vid>/dispute")
def dispute_voucher(vid):
    user_id, _ = auth(["BackgroundActor"])
    body()  # optional reason accepted, not persisted
    v = get_voucher(vid)
    booking = STORE.bookings[v["booking_id"]]
    if booking["actor_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "Caller does not own this voucher's booking")
    if v["status"] != "ISSUED":
        raise ApiError(ERR_VOUCHER_INVALID_STATE, 409, "Only an ISSUED voucher can be disputed")
    eject_voucher_from_open_batch(v)
    v["status"] = "DISPUTED"
    touch(v)
    return ok_obj(ser_voucher(v))


@bp.post("/central-casting/vouchers/<vid>/adjust")
def adjust_voucher(vid):
    user_id, _ = auth(["CastingAssociate"])
    data = body()
    v = get_voucher(vid)
    expected = data.get("expected_voucher_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_VALIDATION, 400, "expected_voucher_version is required")
    if v["status"] not in ("ISSUED", "DISPUTED", "REJECTED"):
        raise ApiError(
            ERR_VOUCHER_INVALID_STATE,
            409,
            "Adjust requires the voucher ISSUED, DISPUTED, or REJECTED",
        )
    if expected != v["version"]:
        raise ApiError(
            ERR_STALE_VOUCHER_VERSION,
            412,
            "expected_voucher_version does not match the voucher's current version",
        )
    compute_voucher_final(v)
    v["adjusted_by_user_id"] = user_id
    v["issued_at"] = logical_now()  # re-issue timestamp
    v["status"] = "ISSUED"
    touch(v)
    return ok_obj(ser_voucher(v))
