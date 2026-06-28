"""FeeSchedule endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db, stamp_create
from errors import err
from helpers import check_enum, get_json_body, require_fields, serialize
from middleware import require_roles
from response import success
from services.lookups import get_fee_schedule

bp = Blueprint("fee_schedules", __name__)

TIER_CODES = {"STANDARD", "PREMIUM", "HEAVY_DUTY"}


def serialize_fee_schedule(fs):
    return serialize(fs)


def _require_int_cents(body, field):
    val = body.get(field)
    if val is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    if not isinstance(val, int) or isinstance(val, bool) or val < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be a non-negative integer" % field)
    return val


@bp.route("/fee-schedules", methods=["POST"])
@require_roles("OpsAdmin")
def create_fee_schedule():
    body = get_json_body()
    require_fields(body, ["tier_code", "base_fee_cents", "vin_history_fee_cents",
                          "per_mile_dispatch_cents"])
    check_enum(body["tier_code"], TIER_CODES, "tier_code")
    base_fee = _require_int_cents(body, "base_fee_cents")
    vin_fee = _require_int_cents(body, "vin_history_fee_cents")
    per_mile = _require_int_cents(body, "per_mile_dispatch_cents")

    effective = body.get("effective", True)
    if effective is None:
        effective = True
    if not isinstance(effective, bool):
        raise err("ERR_INVALID_REQUEST", "effective must be a boolean")

    fs = {
        "tier_code": body["tier_code"],
        "base_fee_cents": base_fee,
        "vin_history_fee_cents": vin_fee,
        "per_mile_dispatch_cents": per_mile,
        "effective": effective,
    }
    stamp_create(fs)
    db.fee_schedules[fs["id"]] = fs
    return success(serialize_fee_schedule(fs), status=201)


@bp.route("/fee-schedules/<fee_schedule_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def get_fee_schedule_ep(fee_schedule_id):
    fs = get_fee_schedule(fee_schedule_id)
    return success(serialize_fee_schedule(fs), status=200)
