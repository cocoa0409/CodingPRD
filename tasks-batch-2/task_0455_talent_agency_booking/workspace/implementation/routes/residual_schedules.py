"""ResidualSchedule endpoints and lifecycle (PRD §3.9)."""
from flask import Blueprint, request

from db import db, lock
from errors import ApiError
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    touch,
    public,
    get_json_body,
    require_str,
    require_int,
    lookup,
    paginate,
)
from services.calc import residual_amount_cents

bp = Blueprint("residual_schedules", __name__)


@bp.route("/residual-schedules", methods=["POST"])
def create_residual_schedule():
    _, role = get_identity()
    require_role(role, {"Agent"})
    body = get_json_body()
    payment_id = require_str(body, "payment_id")
    booking_id = require_str(body, "booking_id")
    period_index = require_int(body, "period_index", minimum=1)
    with lock:
        lookup("Payment", payment_id)
        booking = lookup("Booking", booking_id)
        talent = lookup("Talent", booking["talent_id"])
        call = lookup("CastingCall", booking["casting_call_id"])
        amount = residual_amount_cents(
            talent["union_status"],
            booking["gross_fee_cents"],
            call["media_type"],
            period_index,
        )
        record = mint_common({
            "payment_id": payment_id,
            "booking_id": booking_id,
            "period_index": period_index,
            "residual_amount_cents": amount,
            "status": "DUE",
        })
        db.residual_schedules[record["id"]] = record
        return object_response(public(record), status=201)


@bp.route("/residual-schedules", methods=["GET"])
def list_residual_schedules():
    _, role = get_identity()
    require_role(role, {"Agent", "Talent"})
    with lock:
        items = list(db.residual_schedules.values())
        for field in ("payment_id", "booking_id", "status"):
            val = request.args.get(field)
            if val is not None:
                items = [r for r in items if r[field] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/residual-schedules/<sched_id>", methods=["GET"])
def get_residual_schedule(sched_id):
    _, role = get_identity()
    require_role(role, {"Agent", "Talent"})
    with lock:
        record = lookup("ResidualSchedule", sched_id)
        return object_response(public(record), status=200)


@bp.route("/residual-schedules/<sched_id>/pay", methods=["POST"])
def pay_residual_schedule(sched_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        sched = lookup("ResidualSchedule", sched_id)
        if sched["status"] != "DUE":
            raise ApiError("ERR_INVALID_STATE")
        if sched["residual_amount_cents"] <= 0:
            raise ApiError("ERR_NO_RESIDUAL_DUE")
        sched["status"] = "PAID"
        touch(sched)
        return object_response(public(sched), status=200)


@bp.route("/residual-schedules/<sched_id>/void", methods=["POST"])
def void_residual_schedule(sched_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        sched = lookup("ResidualSchedule", sched_id)
        if sched["status"] != "DUE":
            raise ApiError("ERR_INVALID_STATE")
        sched["status"] = "VOID"
        touch(sched)
        return object_response(public(sched), status=200)
