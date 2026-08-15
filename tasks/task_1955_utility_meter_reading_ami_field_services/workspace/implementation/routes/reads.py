"""MeterRead endpoints: list/get plus BillingLiaison validate/reject."""
from flask import Blueprint, request

from db import db, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION,
)
from middleware import require_roles, ALL_ROLES, body, req_str
from response import success, list_response, created_sorted
from serializers import ser_read

bp = Blueprint("reads", __name__)


def get_read(rid):
    r = db.reads.get(rid)
    if not r:
        raise ApiError(ERR_NOT_FOUND, "MeterRead not found", 404)
    return r


@bp.route("/reads", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.reads.values())
    for param in ("service_account_id", "meter_id", "route_stop_id",
                  "read_status", "supersedes_read_id"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r[param] == val]
    return list_response([ser_read(r) for r in created_sorted(items)])


@bp.route("/reads/<rid>", methods=["GET"])
def get_one(rid):
    require_roles(*ALL_ROLES)
    return success(ser_read(get_read(rid)), code=200)


@bp.route("/reads/<rid>/validate", methods=["POST"])
def validate(rid):
    require_roles("BillingLiaison")
    read = get_read(rid)
    if read["read_status"] != "PROVISIONAL":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Read is not PROVISIONAL", 409)
    read["read_status"] = "VALIDATED"
    touch(read)
    # account streak reset on any actual read validated
    account = db.accounts.get(read["service_account_id"])
    if account and account["estimated_read_streak"] != 0:
        account["estimated_read_streak"] = 0
        touch(account)
    # complete supersede chains: reads this read superseded (they point at it)
    for other in db.reads.values():
        if other["supersedes_read_id"] == read["id"] and other["read_status"] in (
            "VALIDATED", "ESTIMATED",
        ):
            other["read_status"] = "SUPERSEDED"
            touch(other)
    # owning stop resolves when this read is its current read
    stop = db.stops.get(read.get("route_stop_id") or "")
    if stop and stop["current_read_id"] == read["id"] and stop["stop_status"] == "READ_CAPTURED":
        stop["stop_status"] = "VALIDATED"
        touch(stop)
    return success(ser_read(read), code=200)


@bp.route("/reads/<rid>/reject", methods=["POST"])
def reject(rid):
    require_roles("BillingLiaison")
    data = body()
    reason = req_str(data, "rejection_reason")
    read = get_read(rid)
    if read["read_status"] != "PROVISIONAL":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Read is not PROVISIONAL", 409)
    read["read_status"] = "REJECTED"
    read["rejection_reason"] = reason
    touch(read)
    stop = db.stops.get(read.get("route_stop_id") or "")
    if stop and stop["current_read_id"] == read["id"] and stop["stop_status"] == "READ_CAPTURED":
        stop["stop_status"] = "NO_READ_PENDING"
        stop["no_read_reason"] = "READ_REJECTED"
        stop["current_read_id"] = None
        touch(stop)
    return success(ser_read(read), code=200)
