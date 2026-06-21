"""Meter CRUD + assign/retire (PRD §3.1, §3.2)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success, list_success
from services.common import (
    get_json_body, require_fields, serialize, parse_iso,
    pagination_params, paginate, sort_by_creation,
)

meters_bp = Blueprint("meters", __name__)


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap. None 'to' means open-ended (+inf)."""
    # overlap iff a_from < b_to and a_to > b_from (strict), with None = infinity.
    left_ok = (b_to is None) or (a_from < b_to)
    right_ok = (a_to is None) or (a_to > b_from)
    return left_ok and right_ok


@meters_bp.route("/meters", methods=["POST"])
@require_roles("PropertyManager")
def create_meter():
    body = get_json_body()
    require_fields(body, "property_id", "utility_id", "serial_number")

    property_id = body["property_id"]
    if property_id not in db.properties:
        raise ApiError("ERR_NOT_FOUND", "Property not found")
    utility_id = body["utility_id"]
    if utility_id not in db.utilities:
        raise ApiError("ERR_NOT_FOUND", "Utility not found")

    serial_number = body["serial_number"]
    if not isinstance(serial_number, str) or not serial_number.strip():
        raise ApiError("ERR_INVALID_REQUEST", "serial_number must be a non-empty string")

    # Serial unique per property.
    for m in db.meters.values():
        if m["property_id"] == property_id and m["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_SERIAL", "serial_number already in use")

    record = {
        "property_id": property_id,
        "utility_id": utility_id,
        "serial_number": serial_number,
        "assigned_unit_id": None,
        "assignment_effective_from": None,
        "assignment_effective_to": None,
        "last_validated_reading": 0,
        "status": "UNASSIGNED",
        # internal: list of {unit_id, utility_id, from, to} for overlap checks
        "_assignments": [],
    }
    db.stamp_create(record)
    db.meters[record["id"]] = record
    return success(serialize(record), status=201)


@meters_bp.route("/meters/<meter_id>", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Auditor")
def get_meter(meter_id):
    record = db.meters.get(meter_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", "Meter not found")
    return success(serialize(record), status=200)


@meters_bp.route("/meters", methods=["GET"])
@require_roles("PropertyManager", "MeterTech", "Auditor")
def list_meters():
    property_id = request.args.get("property_id")
    utility_id = request.args.get("utility_id")
    assigned_unit_id = request.args.get("assigned_unit_id")
    status = request.args.get("status")
    items = list(db.meters.values())
    if property_id is not None:
        items = [m for m in items if m["property_id"] == property_id]
    if utility_id is not None:
        items = [m for m in items if m["utility_id"] == utility_id]
    if assigned_unit_id is not None:
        items = [m for m in items if m["assigned_unit_id"] == assigned_unit_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = sort_by_creation(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return list_success([serialize(m) for m in page], limit, offset, total)


@meters_bp.route("/meters/<meter_id>/assign", methods=["POST"])
@require_roles("PropertyManager")
def assign_meter(meter_id):
    meter = db.meters.get(meter_id)
    if meter is None:
        raise ApiError("ERR_NOT_FOUND", "Meter not found")

    body = get_json_body()
    require_fields(body, "unit_id", "effective_from")

    # State: only UNASSIGNED or ASSIGNED may assign/re-assign.
    if meter["status"] not in ("UNASSIGNED", "ASSIGNED"):
        raise ApiError("ERR_INVALID_STATE", "Meter cannot be assigned from its current state")

    unit_id = body["unit_id"]
    unit = db.units.get(unit_id)
    if unit is None or unit["status"] == "ARCHIVED":
        raise ApiError("ERR_UNIT_NOT_FOUND", "Target unit not found or archived")

    eff_from = parse_iso(body["effective_from"], "effective_from")
    eff_to = None
    if body.get("effective_to") is not None:
        eff_to = parse_iso(body["effective_to"], "effective_to")
        if eff_to <= eff_from:
            raise ApiError("ERR_INVALID_REQUEST", "effective_to must be after effective_from")

    if meter["status"] == "UNASSIGNED":
        # Overlap vs any OTHER meter assignment of the SAME Unit + SAME Utility.
        for other in db.meters.values():
            if other["id"] == meter_id:
                continue
            if other["utility_id"] != meter["utility_id"]:
                continue
            for w in other.get("_assignments", []):
                if w["unit_id"] != unit_id:
                    continue
                if _windows_overlap(eff_from, eff_to, w["from"], w["to"]):
                    raise ApiError("ERR_METER_ASSIGNMENT_OVERLAP", "Assignment window overlaps")
        # Also vs this meter's own prior windows for the same unit+utility.
        for w in meter.get("_assignments", []):
            if w["unit_id"] != unit_id:
                continue
            if _windows_overlap(eff_from, eff_to, w["from"], w["to"]):
                raise ApiError("ERR_METER_ASSIGNMENT_OVERLAP", "Assignment window overlaps")
    else:
        # ASSIGNED -> re-assign: must not overlap this meter's existing window.
        cur_from = meter["assignment_effective_from"]
        cur_to = meter["assignment_effective_to"]
        cur_from_dt = parse_iso(cur_from, "current_from") if cur_from else None
        cur_to_dt = parse_iso(cur_to, "current_to") if cur_to else None
        if cur_from_dt is not None and _windows_overlap(eff_from, eff_to, cur_from_dt, cur_to_dt):
            raise ApiError("ERR_METER_ASSIGNMENT_OVERLAP", "Assignment window overlaps")
        # Close prior open-ended window at the new effective_from.
        if cur_to_dt is None and cur_from_dt is not None:
            # Update the stored prior window record.
            for w in meter["_assignments"]:
                if w["from"] == cur_from_dt and w["to"] is None and w["unit_id"] == meter["assigned_unit_id"]:
                    w["to"] = eff_from
                    break

    # Record new window.
    meter["_assignments"].append({
        "unit_id": unit_id,
        "from": eff_from,
        "to": eff_to,
    })
    meter["assigned_unit_id"] = unit_id
    meter["assignment_effective_from"] = body["effective_from"]
    meter["assignment_effective_to"] = body.get("effective_to")
    meter["status"] = "ASSIGNED"
    db.touch(meter)
    return success(serialize(meter), status=200)


@meters_bp.route("/meters/<meter_id>/retire", methods=["POST"])
@require_roles("PropertyManager")
def retire_meter(meter_id):
    meter = db.meters.get(meter_id)
    if meter is None:
        raise ApiError("ERR_NOT_FOUND", "Meter not found")

    if meter["status"] not in ("UNASSIGNED", "ASSIGNED"):
        raise ApiError("ERR_INVALID_STATE", "Meter cannot be retired from its current state")

    if meter["status"] == "ASSIGNED":
        # No read in SUBMITTED/RE_READ_REQUESTED tied to an OPEN cycle.
        for read in db.meter_reads.values():
            if read["meter_id"] != meter_id:
                continue
            if read["status"] not in ("SUBMITTED", "RE_READ_REQUESTED"):
                continue
            cycle = _matching_open_cycle(read)
            if cycle is not None:
                raise ApiError("ERR_METER_HAS_PENDING_READS", "Meter has pending reads")

    meter["status"] = "RETIRED"
    db.touch(meter)
    return success(serialize(meter), status=200)


def _matching_open_cycle(read):
    meter = db.meters.get(read["meter_id"])
    if meter is None:
        return None
    for cycle in db.billing_cycles.values():
        if (cycle["property_id"] == read["property_id"]
                and cycle["utility_id"] == meter["utility_id"]
                and cycle["period_label"] == read["period_label"]
                and cycle["status"] == "OPEN"):
            return cycle
    return None
