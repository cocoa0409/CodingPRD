"""SpareReservation endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    err_validation, err_not_found, err_state_transition, err_interval_in_past,
    err_spare_reservation_conflict, err_no_compatible_spare, err_outside_window,
)
from services.common import (
    body, require_string, require_number, require_enum, optional_string,
    optional_number, parse_datetime_field, parse_pagination, paginate,
    get_spare_unit, get_spare_reservation, get_work_order, intervals_overlap,
)
from services.calculations import select_spare_unit

bp = Blueprint("spare_reservations", __name__)

UNIT_TYPES = {"SPARE_TRANSFORMER", "MOBILE_SUBSTATION"}


def spare_reservation_view(r):
    return {
        "id": r["id"],
        "spare_unit_id": r["spare_unit_id"],
        "work_order_id": r.get("work_order_id"),
        "unit_type": r["unit_type"],
        "required_mva": r["required_mva"],
        "required_voltage_kv": r["required_voltage_kv"],
        "preferred_impedance_pct": r.get("preferred_impedance_pct"),
        "site_location": r.get("site_location"),
        "start_ts": r["start_ts"],
        "end_ts": r["end_ts"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _recompute_unit_status(unit_id):
    """Recompute unit status: AVAILABLE when no ACTIVE reservations, else RESERVED."""
    unit = db.spare_units[unit_id]
    if unit["status"] == "DECOMMISSIONED":
        return
    has_active = any(
        r["spare_unit_id"] == unit_id and r["status"] == "ACTIVE"
        for r in db.spare_reservations.values()
    )
    if unit["status"] == "DEPLOYED":
        # Only recompute after return/cancel
        pass
    else:
        unit["status"] = "RESERVED" if has_active else "AVAILABLE"
    db.touch(unit)


@bp.post("/spare-reservations")
def create_spare_reservation():
    actor = get_actor()
    require_roles(actor, ["OutageCoordinator"])
    payload = body()
    unit_type = require_enum(payload, "unit_type", UNIT_TYPES)
    required_mva = require_number(payload, "required_mva")
    required_voltage_kv = require_number(payload, "required_voltage_kv")
    start_ts = parse_datetime_field(payload, "start_ts", required=True)
    end_ts = parse_datetime_field(payload, "end_ts", required=True)
    spare_unit_id = optional_string(payload, "spare_unit_id")
    preferred_impedance_pct = optional_number(payload, "preferred_impedance_pct")
    site_location = optional_string(payload, "site_location")
    work_order_id = optional_string(payload, "work_order_id")

    # Validate end > start
    if end_ts <= start_ts:
        raise err_validation("end_ts must be strictly after start_ts")

    # Interval in past check
    now = db.now_dt()
    if start_ts <= now:
        raise err_interval_in_past()

    # FK: work_order_id if provided
    if work_order_id is not None:
        get_work_order(work_order_id)

    if spare_unit_id is not None:
        # Explicit unit selection
        unit = get_spare_unit(spare_unit_id)
        if unit["unit_type"] != unit_type:
            raise err_validation("spare_unit_id unit_type does not match requested unit_type")

        # Check overlap with existing ACTIVE reservations on this unit
        for r in db.spare_reservations.values():
            if r["spare_unit_id"] != spare_unit_id:
                continue
            if r["status"] != "ACTIVE":
                continue
            r_start = db._parse_iso(r["start_ts"])
            r_end = db._parse_iso(r["end_ts"])
            if intervals_overlap(start_ts, end_ts, r_start, r_end):
                raise err_spare_reservation_conflict()
    else:
        # Selector path
        unit = select_spare_unit(
            unit_type, required_mva, required_voltage_kv, start_ts, end_ts,
            preferred_impedance_pct, site_location,
        )
        if unit is None:
            raise err_no_compatible_spare()
        spare_unit_id = unit["id"]

    ent = {
        "id": db.new_id(),
        "spare_unit_id": spare_unit_id,
        "work_order_id": work_order_id,
        "unit_type": unit_type,
        "required_mva": required_mva,
        "required_voltage_kv": required_voltage_kv,
        "preferred_impedance_pct": preferred_impedance_pct,
        "site_location": site_location,
        "start_ts": db._format_iso(start_ts),
        "end_ts": db._format_iso(end_ts),
        "status": "ACTIVE",
    }
    db.stamp_new(ent)
    db.spare_reservations[ent["id"]] = ent

    # Unit AVAILABLE -> RESERVED
    unit = db.spare_units[spare_unit_id]
    if unit["status"] in ("AVAILABLE", "RESERVED"):
        unit["status"] = "RESERVED"
        db.touch(unit)

    return success_object(spare_reservation_view(ent), status=201)


@bp.get("/spare-reservations")
def list_spare_reservations():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.spare_reservations.values())
    spare_unit_id = request.args.get("spare_unit_id")
    if spare_unit_id:
        items = [r for r in items if r["spare_unit_id"] == spare_unit_id]
    work_order_id = request.args.get("work_order_id")
    if work_order_id:
        items = [r for r in items if r.get("work_order_id") == work_order_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([spare_reservation_view(r) for r in page], limit, offset, total)


@bp.get("/spare-reservations/<id>")
def get_spare_reservation_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    r = get_spare_reservation(id)
    return success_object(spare_reservation_view(r))


@bp.post("/spare-reservations/<id>/cancel")
def cancel_spare_reservation(id):
    actor = get_actor()
    require_roles(actor, ["OutageCoordinator"])
    r = get_spare_reservation(id)
    if r["status"] != "ACTIVE":
        raise err_state_transition("Reservation is not ACTIVE")
    # Cannot cancel a deployed reservation
    unit = db.spare_units[r["spare_unit_id"]]
    if unit["status"] == "DEPLOYED":
        raise err_state_transition("Cannot cancel a deployed reservation; return it instead")
    r["status"] = "CANCELLED"
    db.touch(r)
    _recompute_unit_status(r["spare_unit_id"])
    return success_object(spare_reservation_view(r))


@bp.post("/spare-reservations/<id>/deploy")
def deploy_spare_reservation(id):
    actor = get_actor()
    require_roles(actor, ["OutageCoordinator"])
    r = get_spare_reservation(id)
    if r["status"] != "ACTIVE":
        raise err_state_transition("Reservation is not ACTIVE")
    unit = db.spare_units[r["spare_unit_id"]]
    if unit["status"] != "RESERVED":
        raise err_state_transition("Unit is not RESERVED")
    # Clock must be within [start_ts, end_ts)
    now = db.now_dt()
    start = db._parse_iso(r["start_ts"])
    end = db._parse_iso(r["end_ts"])
    if not (start <= now < end):
        raise err_outside_window()
    unit["status"] = "DEPLOYED"
    db.touch(unit)
    return success_object(spare_reservation_view(r))


@bp.post("/spare-reservations/<id>/return")
def return_spare_reservation(id):
    actor = get_actor()
    require_roles(actor, ["OutageCoordinator"])
    r = get_spare_reservation(id)
    if r["status"] != "ACTIVE":
        raise err_state_transition("Reservation is not ACTIVE")
    unit = db.spare_units[r["spare_unit_id"]]
    if unit["status"] != "DEPLOYED":
        raise err_state_transition("Unit is not DEPLOYED under this reservation")
    r["status"] = "FULFILLED"
    db.touch(r)
    # Recompute unit status
    has_active = any(
        res["spare_unit_id"] == r["spare_unit_id"] and res["status"] == "ACTIVE"
        for res in db.spare_reservations.values()
    )
    unit["status"] = "RESERVED" if has_active else "AVAILABLE"
    db.touch(unit)
    return success_object(spare_reservation_view(r))
