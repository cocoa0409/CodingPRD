"""Device registration and reads (PRD 3.1)."""

from flask import Blueprint

import db
import lookup
from consts import DEVICE_ROLES, MONITORING_STATES_INPUT
from db import base_record
from errors import fail
from middleware import authenticate
from routes._common import body_ref, send
from valid import body, opt_enum, req_enum, req_string

bp = Blueprint("devices", __name__)


@bp.post("/devices")
def create_device():
    authenticate("PlatformAdmin")
    payload = body()
    uplink = body_ref(payload, "primary_uplink_circuit_id", lookup.circuit)
    hostname = req_string(payload, "hostname")
    site_code = req_string(payload, "site_code")
    device_role = req_enum(payload, "device_role", DEVICE_ROLES)
    monitoring_state = opt_enum(
        payload, "monitoring_state", MONITORING_STATES_INPUT, "UNMONITORED"
    )

    for existing in db.db.devices.values():
        if existing["hostname"] == hostname:
            fail("ERR_DEVICE_HOSTNAME_DUPLICATE")

    device = base_record()
    device.update(
        {
            "hostname": hostname,
            "site_code": site_code,
            "device_role": device_role,
            "primary_uplink_circuit_id": uplink["id"] if uplink else None,
            "monitoring_state": monitoring_state,
            "operational_state": "UP",
        }
    )
    db.db.devices[device["id"]] = device
    return send(device, 201)


@bp.get("/devices/<id>")
def get_device(id):
    authenticate(
        "NocAnalyst", "NocShiftLead", "VendorManager", "CapacityPlanner", "PlatformAdmin"
    )
    return send(lookup.device(id))
