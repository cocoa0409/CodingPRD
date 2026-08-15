"""RouteStop endpoints: read capture, mark-no-read, skip-hazard, estimates."""
from flask import Blueprint, request

from db import db, stamp_new, touch, now_dt
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_FORBIDDEN_FOR_ROLE, ERR_NOT_ASSIGNED_TECHNICIAN, ERR_STALE_VERSION,
    ERR_STOP_NOT_ACTIONABLE, ERR_ROUTE_NOT_IN_PROGRESS, ERR_READ_WINDOW_NOT_OPEN,
    ERR_ACTIVE_HAZARD_BLOCKS_READ, ERR_SKIP_REQUIRES_ACTIVE_HAZARD,
    ERR_READ_OUTSIDE_WINDOW, ERR_READ_ROLLBACK, ERR_METER_NOT_INSTALLED_AT_ACCOUNT,
    ERR_ESTIMATE_CAP_REACHED, ERR_INSUFFICIENT_READ_HISTORY,
)
from middleware import (
    require_roles, ALL_ROLES, body, req_str, req_int, req_dt, opt_bool,
)
from response import success, list_response, created_sorted
from serializers import ser_stop, ser_read, account_last_validated
from services.cascades import create_read, suspect_meter, non_terminal_investigation_for_meter
from services import estimates
from util import parse_dt, parse_date

bp = Blueprint("stops", __name__)

CAPTURE_ALLOWED = ("PENDING", "NO_READ_PENDING", "READ_CAPTURED", "ESTIMATED")


def get_stop(sid):
    s = db.stops.get(sid)
    if not s:
        raise ApiError(ERR_NOT_FOUND, "RouteStop not found", 404)
    return s


@bp.route("/route-stops", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.stops.values())
    for param in ("route_id", "service_account_id", "billing_cycle_period_id",
                  "stop_status", "hazard_flag_id", "current_read_id"):
        val = request.args.get(param)
        if val is not None:
            items = [s for s in items if s[param] == val]
    return list_response([ser_stop(s) for s in created_sorted(items)])


@bp.route("/route-stops/<sid>", methods=["GET"])
def get_one(sid):
    require_roles(*ALL_ROLES)
    return success(ser_stop(get_stop(sid)), code=200)


@bp.route("/route-stops/<sid>/reads", methods=["POST"])
def capture(sid):
    uid, role = require_roles("FieldTechnician", "MeterOpsAdmin")
    data = body()
    correction = opt_bool(data, "correction", default=False)
    # correction mode is reserved to MeterOpsAdmin; admins may capture only in
    # correction mode.
    if role == "FieldTechnician" and correction:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE, "correction=true is reserved to MeterOpsAdmin", 403
        )
    if role == "MeterOpsAdmin" and not correction:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            "MeterOpsAdmin may capture reads only with correction=true",
            403,
        )
    meter_id = req_str(data, "meter_id")
    read_value = req_int(data, "read_value", minimum=0)
    read_at = req_dt(data, "read_at")
    expected = data.get("expected_route_stop_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_route_stop_version is required", 400)
    tamper_indication = opt_bool(data, "tamper_indication", default=False)

    stop = get_stop(sid)
    route = db.routes.get(stop["route_id"])
    account = db.accounts.get(stop["service_account_id"])
    period = db.periods.get(stop["billing_cycle_period_id"])

    # ownership (field operations)
    if role == "FieldTechnician" and route and route["technician_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_TECHNICIAN,
            "Caller is not the assigned technician on this route",
            403,
        )
    meter = db.meters.get(meter_id)
    if not meter:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, "Meter not found", 404)
    # OCC
    if expected != stop["version"]:
        raise ApiError(ERR_STALE_VERSION, "RouteStop version does not match", 412)
    # stop actionability precedes the generic/route gates
    if stop["stop_status"] not in CAPTURE_ALLOWED:
        raise ApiError(
            ERR_STOP_NOT_ACTIONABLE,
            "Stop is not in a capture-able state",
            409,
        )
    if not route or route["route_status"] != "IN_PROGRESS":
        raise ApiError(ERR_ROUTE_NOT_IN_PROGRESS, "Route is not IN_PROGRESS", 409)
    if not period or period["period_status"] != "WINDOW_OPEN":
        raise ApiError(ERR_READ_WINDOW_NOT_OPEN, "Period read window is not open", 409)
    # hazard safety screen
    active_hazard = any(
        h["service_account_id"] == stop["service_account_id"] and h["flag_status"] == "ACTIVE"
        for h in db.hazards.values()
    )
    if active_hazard and not route["two_person_crew"]:
        raise ApiError(
            ERR_ACTIVE_HAZARD_BLOCKS_READ,
            "An ACTIVE hazard flag blocks read capture on this account",
            422,
        )
    # read window containment (both ends inclusive, date granularity)
    if not (
        parse_date(period["read_window_open_date"])
        <= parse_dt(read_at).date()
        <= parse_date(period["read_window_close_date"])
    ):
        raise ApiError(ERR_READ_OUTSIDE_WINDOW, "read_at is outside the read window", 422)
    # register rollback
    last_value, _ = account_last_validated(stop["service_account_id"])
    if last_value is not None and read_value < last_value:
        raise ApiError(
            ERR_READ_ROLLBACK,
            "read_value is below the account's last validated read value",
            422,
        )
    # meter must be the account's installed meter
    current_meter_id = next(
        (m["id"] for m in db.meters.values()
         if m["installed_service_account_id"] == stop["service_account_id"]
         and m["meter_status"] == "IN_SERVICE"),
        None,
    )
    if meter_id != current_meter_id:
        raise ApiError(
            ERR_METER_NOT_INSTALLED_AT_ACCOUNT,
            "meter_id is not the account's installed meter",
            409,
        )

    prior_status = stop["stop_status"]
    prior_read = db.reads.get(stop["current_read_id"]) if stop["current_read_id"] else None
    rec = create_read(
        route_stop_id=stop["id"],
        service_account_id=stop["service_account_id"],
        meter_id=meter_id,
        read_value=read_value,
        read_at=read_at,
        read_source="HANDHELD",
        read_status="PROVISIONAL",
        tamper_indication=tamper_indication,
    )
    if prior_status == "READ_CAPTURED" and prior_read and prior_read["read_status"] == "PROVISIONAL":
        prior_read["read_status"] = "SUPERSEDED"
        prior_read["supersedes_read_id"] = rec["id"]
        touch(prior_read)
    elif prior_status == "ESTIMATED" and prior_read and prior_read["read_status"] == "ESTIMATED":
        prior_read["read_status"] = "SUPERSEDED"
        prior_read["supersedes_read_id"] = rec["id"]
        touch(prior_read)
        if account and account["estimated_read_streak"] > 0:
            account["estimated_read_streak"] -= 1
            touch(account)
    stop["stop_status"] = "READ_CAPTURED"
    stop["current_read_id"] = rec["id"]
    touch(stop)

    # tamper cascade
    if tamper_indication:
        existing = non_terminal_investigation_for_meter(meter_id)
        if existing is None:
            inv = {
                "service_account_id": stop["service_account_id"],
                "meter_id": meter_id,
                "indication_type": "TAMPER_FLAG",
                "investigation_status": "OPEN",
                "opened_by_user_id": "system",
                "closed_by_user_id": None,
                "triggering_read_id": rec["id"],
                "exchange_work_order_id": None,
                "theft_window_months": None,
                "monthly_estimated_kwh": None,
                "backbill_cents": None,
                "evidence_notes": [],
            }
            stamp_new(inv)
            db.investigations[inv["id"]] = inv
            suspect_meter(meter)
    return success(ser_read(rec), code=201)


@bp.route("/route-stops/<sid>/mark-no-read", methods=["POST"])
def mark_no_read(sid):
    uid, _role = require_roles("FieldTechnician")
    data = body()
    reason = req_str(data, "no_read_reason")
    stop = get_stop(sid)
    route = db.routes.get(stop["route_id"])
    if route and route["technician_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_TECHNICIAN,
            "Caller is not the assigned technician on this route",
            403,
        )
    if stop["stop_status"] != "PENDING":
        raise ApiError(ERR_STOP_NOT_ACTIONABLE, "Stop is not PENDING", 409)
    if not route or route["route_status"] != "IN_PROGRESS":
        raise ApiError(ERR_ROUTE_NOT_IN_PROGRESS, "Route is not IN_PROGRESS", 409)
    stop["stop_status"] = "NO_READ_PENDING"
    stop["no_read_reason"] = reason
    touch(stop)
    return success(ser_stop(stop), code=200)


@bp.route("/route-stops/<sid>/skip-hazard", methods=["POST"])
def skip_hazard(sid):
    uid, _role = require_roles("FieldTechnician")
    data = body()
    flag_id = req_str(data, "hazard_flag_id")
    stop = get_stop(sid)
    route = db.routes.get(stop["route_id"])
    if route and route["technician_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_TECHNICIAN,
            "Caller is not the assigned technician on this route",
            403,
        )
    flag = db.hazards.get(flag_id)
    if not flag:
        raise ApiError(ERR_REFERENCED_ENTITY_NOT_FOUND, "HazardFlag not found", 404)
    if stop["stop_status"] != "PENDING":
        raise ApiError(ERR_STOP_NOT_ACTIONABLE, "Stop is not PENDING", 409)
    if not route or route["route_status"] != "IN_PROGRESS":
        raise ApiError(ERR_ROUTE_NOT_IN_PROGRESS, "Route is not IN_PROGRESS", 409)
    if flag["flag_status"] != "ACTIVE" or flag["service_account_id"] != stop["service_account_id"]:
        raise ApiError(
            ERR_SKIP_REQUIRES_ACTIVE_HAZARD,
            "Cited flag is not an ACTIVE hazard flag on this stop's account",
            409,
        )
    stop["stop_status"] = "SKIPPED_HAZARD"
    stop["hazard_flag_id"] = flag_id
    touch(stop)
    return success(ser_stop(stop), code=200)


@bp.route("/route-stops/<sid>/generate-estimate", methods=["POST"])
def generate_estimate(sid):
    require_roles("BillingLiaison")
    stop = get_stop(sid)
    account = db.accounts.get(stop["service_account_id"])
    period = db.periods.get(stop["billing_cycle_period_id"])
    if stop["stop_status"] != "NO_READ_PENDING":
        raise ApiError(ERR_STOP_NOT_ACTIONABLE, "Stop is not NO_READ_PENDING", 409)
    if not period or period["period_status"] not in ("WINDOW_OPEN", "WINDOW_CLOSED"):
        raise ApiError(
            ERR_READ_WINDOW_NOT_OPEN,
            "Period must be WINDOW_OPEN or WINDOW_CLOSED for estimation",
            409,
        )
    if account["estimated_read_streak"] >= estimates.MAX_CONSECUTIVE_ESTIMATES:
        raise ApiError(
            ERR_ESTIMATE_CAP_REACHED,
            "Account has reached the consecutive-estimate cap",
            409,
        )
    if estimates.trailing_history_count(account["id"], now_dt()) < estimates.MIN_TRAILING_VALIDATED_READS:
        raise ApiError(
            ERR_INSUFFICIENT_READ_HISTORY,
            "Fewer than two trailing-365-day VALIDATED reads on the account",
            409,
        )
    value, method_used = estimates.estimate_value(account, period)
    estimate_read_at = period["read_window_close_date"] + "T00:00:00.000Z"
    rec = create_read(
        route_stop_id=stop["id"],
        service_account_id=stop["service_account_id"],
        meter_id=next(
            (m["id"] for m in db.meters.values()
             if m["installed_service_account_id"] == stop["service_account_id"]
             and m["meter_status"] == "IN_SERVICE"),
            None,
        ),
        read_value=value,
        read_at=estimate_read_at,
        read_source="ESTIMATE",
        read_status="ESTIMATED",
        estimation_method=method_used,
    )
    stop["stop_status"] = "ESTIMATED"
    stop["current_read_id"] = rec["id"]
    touch(stop)
    account["estimated_read_streak"] += 1
    touch(account)
    return success(ser_read(rec), code=201)
