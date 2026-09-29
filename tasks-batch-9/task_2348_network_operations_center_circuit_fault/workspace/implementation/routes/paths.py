"""Application paths, availability reporting and per-path failover reads."""

from flask import Blueprint

import db
import derive
import lookup
from consts import AVAILABILITY_BASES, FAILOVER_STATES, LEG_GROUPS, PROTECTION_SCHEMES, SERVICE_TIERS
from db import base_record, rows
from errors import fail
from middleware import authenticate
from routes._common import send, send_data, send_list
from serialize import jsonable
from valid import body, opt_int, q_enum, q_ts, req_enum, req_string

bp = Blueprint("paths", __name__)


@bp.post("/application-paths")
def create_path():
    authenticate("PlatformAdmin")
    payload = body()
    name = req_string(payload, "name")
    service_tier = req_enum(payload, "service_tier", SERVICE_TIERS)
    protection_scheme = req_enum(payload, "protection_scheme", PROTECTION_SCHEMES)
    min_surviving_legs = opt_int(payload, "min_surviving_legs", 1, 1, 2)

    path = base_record()
    path.update(
        {
            "name": name,
            "service_tier": service_tier,
            "protection_scheme": protection_scheme,
            "min_surviving_legs": min_surviving_legs,
            "posture": "PROTECTED",
            "active_leg_count": 0,
            "healthy_leg_count": 0,
            "monitored_segment_count": 0,
        }
    )
    db.db.paths[path["id"]] = path
    return send(path, 201)


@bp.get("/application-paths/<id>")
def get_path(id):
    authenticate(
        "NocAnalyst", "NocShiftLead", "VendorManager", "CapacityPlanner", "PlatformAdmin"
    )
    return send(lookup.path(id))


@bp.get("/application-paths/<id>/availability")
def path_availability(id):
    authenticate("NocAnalyst", "NocShiftLead", "VendorManager", "PlatformAdmin")
    path = lookup.path(id)
    window_from = q_ts("from_iso8601", required=True)
    window_to = q_ts("to_iso8601", required=True)
    basis = q_enum("basis", AVAILABILITY_BASES)
    if basis is None:
        fail("ERR_INVALID_REQUEST", "basis is required.")
    if not window_to > window_from:
        fail("ERR_TIMESTAMP_RANGE_INVALID")
    report = derive.availability_report(path, window_from, window_to, basis)
    return send_data(jsonable(report))


@bp.get("/application-paths/<id>/failover-tests")
def list_path_failover_tests(id):
    authenticate("NocAnalyst", "NocShiftLead", "VendorManager", "PlatformAdmin")
    path = lookup.path(id)
    state = q_enum("state", FAILOVER_STATES)
    tested_leg_group = q_enum("tested_leg_group", LEG_GROUPS)
    result = [
        test
        for test in rows(db.db.failover_tests)
        if test["application_path_id"] == path["id"]
        and (state is None or test["state"] == state)
        and (tested_leg_group is None or test["tested_leg_group"] == tested_leg_group)
    ]
    return send_list(result)
