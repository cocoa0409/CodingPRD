"""Dryer units and the capacity calendar (PRD §3.4)."""

from flask import Blueprint, request

from db import public, stamp_new, store
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import get_unit
from services.calculations import committed_bushels
from validation import get_body, req_int, req_str
from db import parse_date

bp = Blueprint("units", __name__)

READ_ROLES = {"ElevatorManager", "Grower", "IntakeTechnician", "DryerOperator", "ClaimsAdjuster"}


@bp.post("/dryer-units")
def create_unit():
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    body = get_body()
    unit_code = req_str(body, "unit_code")
    daily_capacity = req_int(body, "daily_capacity_bushels", minimum=1)
    standard_cap = req_int(body, "standard_class_cap_bushels", minimum=0)
    throughput = req_int(body, "throughput_bu_per_hour", minimum=0)
    cooldown = req_int(body, "cooldown_minutes", minimum=0)
    rec = stamp_new(
        {
            "unit_code": unit_code,
            "daily_capacity_bushels": daily_capacity,
            "standard_class_cap_bushels": standard_cap,
            "throughput_bu_per_hour": throughput,
            "cooldown_minutes": cooldown,
        }
    )
    store.units[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.get("/dryer-units/<uid>")
def get_one_unit(uid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_unit(uid)
    return success(public(rec))


@bp.get("/dryer-units/<uid>/capacity-calendar")
def capacity_calendar(uid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager", "Grower", "DryerOperator"})
    rec = get_unit(uid)
    date_str = request.args.get("date")
    if date_str is None or parse_date(date_str) is None or len(date_str) != 10:
        raise_err("ERR_INVALID_REQUEST", "Query parameter date must be a YYYY-MM-DD date")
    standard, total = committed_bushels(rec["id"], date_str)
    data = {
        "unit_id": rec["id"],
        "date": date_str,
        "daily_capacity_bushels": rec["daily_capacity_bushels"],
        "standard_committed_bushels": standard,
        "total_committed_bushels": total,
        "standard_remaining_bushels": rec["standard_class_cap_bushels"] - standard,
        "total_remaining_bushels": rec["daily_capacity_bushels"] - total,
    }
    return success(data)
