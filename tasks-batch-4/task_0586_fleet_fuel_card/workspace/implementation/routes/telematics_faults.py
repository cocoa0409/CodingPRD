"""Telematics faults and maintenance windows (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, g, request

import response
from db import base_record, db, touch
from errors import err
from middleware import (body, check_fleet, is_fleet_manager, paginate, query_enum, req_enum,
                        req_str, require_roles)
from services import serialize
from services.cascade import restore_vehicle_if_clear, vehicle_out_of_service
from services.store import (FAULT_STATUSES, MAINTENANCE_BUFFER_HOURS, SEVERITIES,
                            account_of_fault, get_fault, get_vehicle)
from util import parse_dt

bp = Blueprint("telematics_faults", __name__)

BUFFER = timedelta(hours=MAINTENANCE_BUFFER_HOURS)


def _dt_field(data, field):
    raw = data.get(field)
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        raise err("ERR_VALIDATION", "Field '%s' must be an ISO 8601 datetime string." % field)
    try:
        return raw, parse_dt(raw)
    except ValueError:
        raise err("ERR_VALIDATION", "Field '%s' must be an ISO 8601 datetime string." % field)


@bp.post("/telematics-faults")
@require_roles("TelematicsGateway")
def report_fault():
    data = body()
    vehicle_id = req_str(data, "vehicle_id")
    fault_code = req_str(data, "fault_code")
    severity = req_enum(data, "severity", SEVERITIES)
    start_raw, start = _dt_field(data, "maintenance_window_start")
    end_raw, end = _dt_field(data, "maintenance_window_end")

    # 3. Existence.
    vehicle = get_vehicle(vehicle_id)

    # 11. Interval well-formedness.
    if start is not None and end is not None and not (start < end):
        raise err("ERR_INVALID_INTERVAL",
                  "'maintenance_window_start' must be strictly earlier than "
                  "'maintenance_window_end'.")

    critical = severity == "CRITICAL"

    # 13. Maintenance overlap — the window expanded by MAINTENANCE_BUFFER_HOURS on
    # both sides must not intersect another non-CLEARED window on the same vehicle.
    # Comparison is closed: touching within the buffer collides.
    if critical and start is not None and end is not None:
        buffered_start = start - BUFFER
        buffered_end = end + BUFFER
        for other in db.telematics_faults.values():
            if other["vehicle_id"] != vehicle_id or other["status"] == "CLEARED":
                continue
            other_start = other["_window_start_dt"]
            other_end = other["_window_end_dt"]
            if other_start is None or other_end is None:
                continue
            if buffered_start <= other_end and other_start <= buffered_end:
                raise err("ERR_MAINTENANCE_OVERLAP")

    # 14. Maintenance window presence.
    if critical and (start is None or end is None):
        raise err("ERR_MISSING_MAINTENANCE_WINDOW")

    record = base_record()
    record.update({
        "vehicle_id": vehicle_id,
        "fault_code": fault_code,
        "severity": severity,
        "status": "OPEN",
        "maintenance_window_start": start_raw,
        "maintenance_window_end": end_raw,
        "_window_start_dt": start,
        "_window_end_dt": end,
    })
    db.telematics_faults[record["id"]] = record

    if critical:
        # auto-transition OPEN -> MAINTENANCE_SCHEDULED, cascade origin
        record["status"] = "MAINTENANCE_SCHEDULED"
        touch(record)
        vehicle_out_of_service(vehicle)

    return response.created(serialize.telematics_fault(record))


@bp.get("/telematics-faults/<fault_id>")
@require_roles("TelematicsGateway", "FleetManager", "ProgramAdmin")
def fetch_fault(fault_id):
    fault = get_fault(fault_id)
    check_fleet(account_of_fault(fault))
    return response.ok(serialize.telematics_fault(fault))


@bp.get("/telematics-faults")
@require_roles("TelematicsGateway", "FleetManager", "ProgramAdmin")
def list_faults():
    vehicle_filter = request.args.get("vehicle_id")
    status_filter = query_enum("status", FAULT_STATUSES)
    severity_filter = query_enum("severity", SEVERITIES)

    records = list(db.telematics_faults.values())
    if is_fleet_manager():
        records = [f for f in records if account_of_fault(f) == g.user_id]
    if vehicle_filter is not None:
        records = [f for f in records if f["vehicle_id"] == vehicle_filter]
    if status_filter is not None:
        records = [f for f in records if f["status"] == status_filter]
    if severity_filter is not None:
        records = [f for f in records if f["severity"] == severity_filter]

    page, total, limit, offset = paginate(records)
    return response.listing([serialize.telematics_fault(f) for f in page], limit, offset, total)


@bp.post("/telematics-faults/<fault_id>/complete-maintenance")
@require_roles("TelematicsGateway")
def complete_maintenance(fault_id):
    fault = get_fault(fault_id)
    if fault["status"] != "MAINTENANCE_SCHEDULED":
        raise err("ERR_INVALID_FAULT_STATE",
                  "Only a MAINTENANCE_SCHEDULED fault can be completed.")
    fault["status"] = "MAINTENANCE_COMPLETE"
    touch(fault)

    vehicle = get_vehicle(fault["vehicle_id"])
    restore_vehicle_if_clear(vehicle)
    return response.ok(serialize.telematics_fault(fault))


@bp.post("/telematics-faults/<fault_id>/clear")
@require_roles("TelematicsGateway")
def clear(fault_id):
    fault = get_fault(fault_id)
    if fault["status"] == "MAINTENANCE_COMPLETE":
        pass
    elif fault["status"] == "OPEN" and fault["severity"] != "CRITICAL":
        pass
    else:
        raise err("ERR_INVALID_FAULT_STATE",
                  "A fault can only be cleared from MAINTENANCE_COMPLETE, or from OPEN "
                  "when its severity is not CRITICAL.")
    fault["status"] = "CLEARED"
    touch(fault)
    return response.ok(serialize.telematics_fault(fault))
