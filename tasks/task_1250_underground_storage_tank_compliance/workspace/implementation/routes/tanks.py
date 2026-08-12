"""TankSystem inventory, lifecycle, and test-schedule projection
(PRD 3.1, 3.2)."""
from flask import Blueprint

from authz import FACILITY_OWNER, READ_ROLES, check_facility_ownership, require_roles
from calc import project_test_schedule
from cascades import close_tank_cascade
from db import store
from errors import (
    critical_deficiency_open, duplicate_tank_tag, facility_not_active,
    invalid_request, mode_not_allowed, open_release_on_tank, tank_not_found,
)
from respond import success
from routes.facilities import get_facility_or_404
from serialize import ser_tank
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, paginate,
    qparam, req_enum, req_instant, req_int, req_str, sorted_by_creation, touch,
)
from timeutil import fmt_dt

bp = Blueprint("tank_systems", __name__)

SUBSTANCES = ["GASOLINE", "DIESEL", "KEROSENE", "USED_OIL"]
CONSTRUCTIONS = ["STEEL", "FRP", "COMPOSITE"]
PIPING_TYPES = ["PRESSURIZED", "SUCTION", "GRAVITY"]
DETECTION_MODES = ["INTERSTITIAL_MONITORING", "ATG_INVENTORY", "MANUAL_GAUGING"]
CLOSURE_TYPES = ["TEMPORARY", "PERMANENT"]
MANUAL_GAUGING_MAX_CAPACITY = 2000


def get_tank_or_404(tank_id):
    return get_or_404(store.tank_systems, tank_id, tank_not_found)


@bp.route("/tank-systems", methods=["POST"])
def create_tank():
    uid, _ = require_roles([FACILITY_OWNER])
    data = json_body()
    check_closed(data, {"facility_id", "tank_tag", "substance", "capacity_gallons",
                        "installed_on", "tank_construction", "piping_type",
                        "release_detection_mode"})
    facility_id = req_str(data, "facility_id")
    tank_tag = req_str(data, "tank_tag")
    substance = req_enum(data, "substance", SUBSTANCES)
    capacity = req_int(data, "capacity_gallons")
    installed_on = req_instant(data, "installed_on")
    construction = req_enum(data, "tank_construction", CONSTRUCTIONS)
    piping = req_enum(data, "piping_type", PIPING_TYPES)
    mode = req_enum(data, "release_detection_mode", DETECTION_MODES)

    fac = get_facility_or_404(facility_id)
    check_facility_ownership(uid, fac)
    if mode == "MANUAL_GAUGING" and capacity > MANUAL_GAUGING_MAX_CAPACITY:
        raise mode_not_allowed()
    if any(t["facility_id"] == facility_id and t["tank_tag"] == tank_tag
           for t in store.tank_systems.values()):
        raise duplicate_tank_tag()

    t = {
        "id": new_id(),
        "_seq": next(store.seq),
        "facility_id": facility_id,
        "tank_tag": tank_tag,
        "substance": substance,
        "capacity_gallons": capacity,
        "installed_on": installed_on,
        "tank_construction": construction,
        "piping_type": piping,
        "release_detection_mode": mode,
        "status": "REGISTERED",
    }
    t.update(new_common_fields())
    store.tank_systems[t["id"]] = t
    return success(ser_tank(t), status=201)


@bp.route("/tank-systems", methods=["GET"])
def list_tanks():
    require_roles(READ_ROLES)
    facility_id = qparam("facility_id")
    status = qparam("status")
    items = store.tank_systems.values()
    if facility_id is not None:
        items = [t for t in items if t["facility_id"] == facility_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_tank(t) for t in page], response_type="array", pagination=pagination)


@bp.route("/tank-systems/<tank_id>", methods=["GET"])
def get_tank(tank_id):
    require_roles(READ_ROLES)
    return success(ser_tank(get_tank_or_404(tank_id)))


@bp.route("/tank-systems/<tank_id>/test-schedule", methods=["GET"])
def test_schedule(tank_id):
    require_roles(READ_ROLES)
    t = get_tank_or_404(tank_id)
    items = project_test_schedule(t)
    return success({
        "tank_system_id": t["id"],
        "items": [{"test_type": i["test_type"], "due_at": fmt_dt(i["due_at"])}
                  for i in items],
    })


@bp.route("/tank-systems/<tank_id>/place-in-service", methods=["POST"])
def place_in_service(tank_id):
    uid, _ = require_roles([FACILITY_OWNER])
    t = get_tank_or_404(tank_id)
    fac = get_facility_or_404(t["facility_id"])
    check_facility_ownership(uid, fac)
    if fac["status"] != "ACTIVE":
        raise facility_not_active()
    if t["status"] != "REGISTERED":
        raise invalid_tank_state_for_service()
    t["status"] = "IN_SERVICE"
    touch(t)
    return success(ser_tank(t))


def invalid_tank_state_for_service():
    from errors import tank_not_in_service
    return tank_not_in_service("Tank must be REGISTERED to place in service")


@bp.route("/tank-systems/<tank_id>/close", methods=["POST"])
def close_tank(tank_id):
    uid, _ = require_roles([FACILITY_OWNER])
    data = json_body()
    check_closed(data, {"closure_type"})
    t = get_tank_or_404(tank_id)
    fac = get_facility_or_404(t["facility_id"])
    check_facility_ownership(uid, fac)
    closure_type = req_enum(data, "closure_type", CLOSURE_TYPES)
    if closure_type == "TEMPORARY":
        if t["status"] != "IN_SERVICE":
            raise invalid_tank_state_for_close("TEMPORARY closure requires status IN_SERVICE")
        close_tank_cascade(t, "TEMPORARILY_CLOSED")
    else:  # PERMANENT
        if t["status"] not in ("IN_SERVICE", "TEMPORARILY_CLOSED"):
            raise invalid_tank_state_for_close(
                "PERMANENT closure requires status IN_SERVICE or TEMPORARILY_CLOSED")
        close_tank_cascade(t, "PERMANENTLY_CLOSED")
    return success(ser_tank(t))


def invalid_tank_state_for_close(msg):
    from errors import tank_not_in_service
    return tank_not_in_service(msg)


@bp.route("/tank-systems/<tank_id>/return-to-service", methods=["POST"])
def return_to_service(tank_id):
    uid, _ = require_roles([FACILITY_OWNER])
    t = get_tank_or_404(tank_id)
    fac = get_facility_or_404(t["facility_id"])
    check_facility_ownership(uid, fac)
    if t["status"] != "TEMPORARILY_CLOSED":
        raise invalid_tank_state_for_close("return-to-service requires status TEMPORARILY_CLOSED")
    # Gate 1: an open CRITICAL deficiency blocks (CORRECTED / RE_TEST_SCHEDULED
    # do not — the correction is applied, verification pending).
    for d in store.deficiencies.values():
        if (d["tank_system_id"] == tank_id and d["severity"] == "CRITICAL"
                and d["status"] in ("OPEN", "CORRECTION_ORDERED", "ESCALATED")):
            raise critical_deficiency_open()
    # Gate 2: an open release on the tank blocks.
    for r in store.release_events.values():
        if (r["tank_system_id"] == tank_id
                and r["status"] in ("SUSPECTED", "CONFIRMED", "CLEANUP_IN_PROGRESS")):
            raise open_release_on_tank()
    t["status"] = "IN_SERVICE"
    touch(t)
    return success(ser_tank(t))
