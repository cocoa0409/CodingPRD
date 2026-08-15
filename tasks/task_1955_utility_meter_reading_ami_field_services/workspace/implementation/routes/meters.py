"""Meter endpoints including install, retire, and AMI head-end ingestion."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION, ERR_DUPLICATE_SERIAL_NUMBER,
    ERR_ACCOUNT_HAS_INSTALLED_METER, ERR_ACCOUNT_NOT_ACTIVE,
    ERR_METER_NOT_AMI, ERR_READ_ROLLBACK,
)
from middleware import require_roles, ALL_ROLES, body, req_str, req_enum, req_int, req_dt
from response import success, list_response, created_sorted
from serializers import ser_meter, ser_read, account_current_meter_id, account_last_validated
from services.cascades import create_read

bp = Blueprint("meters", __name__)


def get_meter(mid):
    m = db.meters.get(mid)
    if not m:
        raise ApiError(ERR_NOT_FOUND, "Meter not found", 404)
    return m


@bp.route("/meters", methods=["POST"])
def create():
    require_roles("MeterOpsAdmin")
    data = body()
    serial_number = req_str(data, "serial_number")
    meter_type = req_enum(data, "meter_type", ("HANDHELD", "AMI"))
    if any(m["serial_number"] == serial_number for m in db.meters.values()):
        raise ApiError(ERR_DUPLICATE_SERIAL_NUMBER, "serial_number already exists", 409)
    rec = {
        "serial_number": serial_number,
        "meter_type": meter_type,
        "meter_status": "IN_STOCK",
        "endpoint_comms_status": "COMMUNICATING" if meter_type == "AMI" else "NOT_APPLICABLE",
        "tamper_status": "NONE",
        "installed_service_account_id": None,
        "consecutive_missed_days": 0,
        "non_communicating_since": None,
    }
    stamp_new(rec)
    db.meters[rec["id"]] = rec
    return success(ser_meter(rec), code=201)


@bp.route("/meters", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.meters.values())
    for param in ("meter_status", "endpoint_comms_status", "tamper_status",
                  "installed_service_account_id"):
        val = request.args.get(param)
        if val is not None:
            items = [m for m in items if m[param] == val]
    return list_response([ser_meter(m) for m in created_sorted(items)])


@bp.route("/meters/<mid>", methods=["GET"])
def get_one(mid):
    require_roles(*ALL_ROLES)
    return success(ser_meter(get_meter(mid)), code=200)


@bp.route("/meters/<mid>/install", methods=["POST"])
def install(mid):
    require_roles("MeterOpsAdmin")
    data = body()
    account_id = req_str(data, "service_account_id")
    m = get_meter(mid)
    account = db.accounts.get(account_id)
    if not account:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, "ServiceAccount not found", 404)
    if m["meter_status"] != "IN_STOCK":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Meter is not IN_STOCK", 409)
    if account_current_meter_id(account_id) is not None:
        raise ApiError(
            ERR_ACCOUNT_HAS_INSTALLED_METER,
            "Account already has an IN_SERVICE meter",
            409,
        )
    if account["account_status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, "Account is not ACTIVE", 409)
    m["meter_status"] = "IN_SERVICE"
    m["installed_service_account_id"] = account_id
    touch(m)
    return success(ser_meter(m), code=200)


@bp.route("/meters/<mid>/retire", methods=["POST"])
def retire(mid):
    require_roles("MeterOpsAdmin")
    m = get_meter(mid)
    if m["meter_status"] not in ("IN_STOCK", "REMOVED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Meter can be retired only from IN_STOCK or REMOVED",
            409,
        )
    m["meter_status"] = "RETIRED"
    touch(m)
    return success(ser_meter(m), code=200)


@bp.route("/meters/<mid>/ami-reads", methods=["POST"])
def ami_reads(mid):
    require_roles("MeterOpsAdmin")
    data = body()
    read_value = req_int(data, "read_value", minimum=0)
    read_at = req_dt(data, "read_at")
    m = get_meter(mid)
    if m["meter_status"] != "IN_SERVICE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Meter is not IN_SERVICE", 409)
    account_id = m["installed_service_account_id"]
    last_value, _last_at = account_last_validated(account_id) if account_id else (None, None)
    if last_value is not None and read_value < last_value:
        raise ApiError(
            ERR_READ_ROLLBACK,
            "read_value is below the account's last validated read value",
            422,
        )
    if m["meter_type"] != "AMI":
        raise ApiError(ERR_METER_NOT_AMI, "AMI ingestion requires an AMI meter", 422)
    rec = create_read(
        route_stop_id=None,
        service_account_id=account_id,
        meter_id=m["id"],
        read_value=read_value,
        read_at=read_at,
        read_source="AMI_REMOTE",
        read_status="VALIDATED",
    )
    # comms recovery on ingestion while IN_SERVICE
    if m["endpoint_comms_status"] in ("DEGRADED", "NON_COMMUNICATING", "FAILED") \
            or m["consecutive_missed_days"] != 0 \
            or m["non_communicating_since"] is not None:
        m["endpoint_comms_status"] = "COMMUNICATING"
        m["consecutive_missed_days"] = 0
        m["non_communicating_since"] = None
        touch(m)
    return success(ser_read(rec), code=201)
