"""Component registration and listing (PRD 3.1)."""
from flask import Blueprint

from authz import FACILITY_OWNER, READ_ROLES, check_facility_ownership, require_roles
from db import store
from errors import component_not_found
from respond import success
from routes.facilities import get_facility_or_404
from routes.tanks import get_tank_or_404
from serialize import ser_component
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, paginate,
    qparam, req_enum, req_instant, req_str, sorted_by_creation,
)

bp = Blueprint("components", __name__)

COMPONENT_TYPES = ["SPILL_BUCKET", "OVERFILL_DEVICE", "LINE_LEAK_DETECTOR", "CATHODIC_PROTECTION"]


def get_component_or_404(comp_id):
    return get_or_404(store.components, comp_id, component_not_found)


@bp.route("/components", methods=["POST"])
def create_component():
    uid, _ = require_roles([FACILITY_OWNER])
    data = json_body()
    check_closed(data, {"tank_system_id", "component_type", "install_date", "serial_no"})
    tank_system_id = req_str(data, "tank_system_id")
    component_type = req_enum(data, "component_type", COMPONENT_TYPES)
    install_date = req_instant(data, "install_date")
    serial_no = req_str(data, "serial_no")

    tank = get_tank_or_404(tank_system_id)
    fac = get_facility_or_404(tank["facility_id"])
    check_facility_ownership(uid, fac)

    c = {
        "id": new_id(),
        "_seq": next(store.seq),
        "tank_system_id": tank_system_id,
        "component_type": component_type,
        "install_date": install_date,
        "serial_no": serial_no,
        "status": "IN_SERVICE",
    }
    c.update(new_common_fields())
    store.components[c["id"]] = c
    return success(ser_component(c), status=201)


@bp.route("/components", methods=["GET"])
def list_components():
    require_roles(READ_ROLES)
    tank_system_id = qparam("tank_system_id")
    component_type = qparam("component_type")
    status = qparam("status")
    items = store.components.values()
    if tank_system_id is not None:
        items = [c for c in items if c["tank_system_id"] == tank_system_id]
    if component_type is not None:
        items = [c for c in items if c["component_type"] == component_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_component(c) for c in page], response_type="array", pagination=pagination)


@bp.route("/components/<comp_id>", methods=["GET"])
def get_component(comp_id):
    require_roles(READ_ROLES)
    return success(ser_component(get_component_or_404(comp_id)))
