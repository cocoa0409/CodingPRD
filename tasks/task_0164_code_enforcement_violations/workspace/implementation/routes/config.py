"""Config / clock endpoints (PRD §3.1, §2.4)."""

from flask import Blueprint, request

from clock import clock
from db import db, common_fields, iso
from errors import err
from middleware import require_roles
from response import success, list_success
from services import serialize
from services.helpers import (
    get_body,
    pagination_params,
    paginate,
    parse_iso,
    require_enum,
    require_int,
    sort_by_created,
)

bp = Blueprint("config", __name__)

VIOLATION_CLASSES = {"MINOR", "MAJOR", "HAZARD"}


@bp.post("/fee-schedules")
@require_roles("PlatformAdmin")
def create_fee_schedule():
    body = get_body()
    require_enum(body, "violation_class", VIOLATION_CLASSES)
    base = require_int(body, "base_fine_cents")
    daily = require_int(body, "daily_accrual_cents")
    max_total = require_int(body, "max_total_cents")
    cure = require_int(body, "cure_days")

    record = common_fields(with_version=False)
    record.update({
        "violation_class": body["violation_class"],
        "base_fine_cents": base,
        "daily_accrual_cents": daily,
        "max_total_cents": max_total,
        "cure_days": cure,
    })
    db.fee_schedules[record["id"]] = record
    return success(serialize.fee_schedule_out(record), status=201)


@bp.get("/fee-schedules")
@require_roles("PlatformAdmin", "CodeOfficer", "FinanceClerk")
def list_fee_schedules():
    limit, offset = pagination_params()
    items = list(db.fee_schedules.values())
    vc = request.args.get("violation_class")
    if vc is not None:
        items = [f for f in items if f["violation_class"] == vc]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize.fee_schedule_out(f) for f in page], limit, offset, total)


@bp.post("/_clock/set")
@require_roles("PlatformAdmin")
def set_clock():
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: to_iso8601")
    dt = parse_iso(body["to_iso8601"], "to_iso8601")
    clock.set(dt)
    return success({"current_utc": iso(clock.now())}, status=200)
