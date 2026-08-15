"""PerDiemStatement endpoints: issue under a stop, list under stop/cast, pay."""

from flask import Blueprint

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_PER_DIEM_INVALID, ERR_STOP_INVALID_STATE,
                    ERR_DUPLICATE_RECORD, ERR_PER_DIEM_INVALID_STATE)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain, calc
from util import (get_body, reject_unknown, require_present, as_str,
                  as_enum, paginate)

bp = Blueprint("per_diems", __name__)


@bp.route("/stops/<stop_id>/per-diems", methods=["POST"])
def create_per_diem(stop_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    stop = db.stops.get(stop_id)
    if stop is None:
        raise err(ERR_NOT_FOUND, 404, "Stop not found")
    body = get_body()
    member = None
    if body.get("cast_member_id") is not None:
        member = (db.cast_members.get(body["cast_member_id"])
                  if isinstance(body["cast_member_id"], str) else None)
        if member is None:
            raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    reject_unknown(body, {"cast_member_id", "days_present", "travel_days"})
    member_id = as_str(require_present(body, "cast_member_id"), "cast_member_id")
    if member is None:
        member = db.cast_members.get(member_id)
        if member is None:
            raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    # Generic shape: integer types (ranges carry their own code, next).
    days = require_present(body, "days_present")
    travel = require_present(body, "travel_days")
    if isinstance(days, bool) or not isinstance(days, int) \
            or isinstance(travel, bool) or not isinstance(travel, int):
        raise err(ERR_INVALID_REQUEST, 400,
                  "days_present and travel_days must be integers")
    # Per-diem ranges (evaluated immediately after generic shape, before state):
    # 1 <= days_present <= 7 and 0 <= travel_days <= min(2, days_present).
    if not (1 <= days <= 7) or not (0 <= travel <= min(2, days)):
        raise err(ERR_PER_DIEM_INVALID, 400,
                  "days_present must be in 1..7 and travel_days <= min(2, days_present)")
    # State (priority 5): issue only while READY | PLAYING | CLOSED.
    if stop["booking_status"] not in ("READY", "PLAYING", "CLOSED"):
        raise err(ERR_STOP_INVALID_STATE, 409,
                  "Per-diems may be issued only while the stop is READY/PLAYING/CLOSED")
    # Uniqueness (priority 7): at most one statement per (stop, cast member).
    for p in domain.per_diems_of_stop(stop_id):
        if p["cast_member_id"] == member_id:
            raise err(ERR_DUPLICATE_RECORD, 422,
                      "A per-diem statement already exists for this stop and member")
    tour = db.tours[stop["tour_id"]]
    policy = tour["per_diem_policy"]
    rate = tour["per_diem_daily_cents"]
    rec = db.new_record()
    rec.update({
        "stop_id": stop_id,
        "cast_member_id": member_id,
        "days_present": days,
        "travel_days": travel,
        "policy_snapshot": policy,          # snapshotted at creation
        "daily_rate_cents": rate,           # snapshotted at creation
        "total_cents": calc.calc_per_diem(policy, rate, days, travel),
        "status": "ISSUED",
    })
    db.per_diems[rec["id"]] = rec
    return success(db.serialize("per_diem", rec), 201)


@bp.route("/stops/<stop_id>/per-diems", methods=["GET"])
def list_per_diems_of_stop(stop_id):
    authenticate()
    if db.stops.get(stop_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Stop not found")
    items = sorted(domain.per_diems_of_stop(stop_id), key=lambda p: p["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("per_diem", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/cast/<cast_id>/per-diems", methods=["GET"])
def list_per_diems_of_cast(cast_id):
    authenticate()
    if db.cast_members.get(cast_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    items = [p for p in db.per_diems.values() if p["cast_member_id"] == cast_id]
    items.sort(key=lambda p: p["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("per_diem", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/per-diems/<pd_id>", methods=["PUT"])
def put_per_diem(pd_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    pd = db.per_diems.get(pd_id)
    if pd is None:
        raise err(ERR_NOT_FOUND, 404, "Per-diem statement not found")
    body = get_body()
    reject_unknown(body, {"status"})
    target = as_enum(require_present(body, "status"), "status", ("ISSUED", "PAID"))
    if target != "PAID" or pd["status"] != "ISSUED":
        raise err(ERR_PER_DIEM_INVALID_STATE, 409,
                  "PAID is only reachable from ISSUED")
    pd["status"] = "PAID"
    touch(pd)
    return success(db.serialize("per_diem", pd), 200)
