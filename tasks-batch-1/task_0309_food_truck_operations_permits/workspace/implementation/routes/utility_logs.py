"""UtilityLog endpoints (PRD §3.8). Append-only: id + created_at only."""

from flask import request, Blueprint

import errors
import serializers
import services
from db import db
from clock import now_iso
from errors import err
from helpers import (get_body, require_str, require_fk, require_enum,
                     require_number, get_pagination, paginate)
from lookups import get_utility_log, get_truck
from middleware import require_user_context, require_role, require_truck_ownership
from response import ok_object, ok_array

bp = Blueprint("utility_logs", __name__)

WRITE_ROLES = {"OperatorTruck", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}
UTILITIES = {"PROPANE", "GENERATOR"}


@bp.post("/utility-logs")
def create_utility_log():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    # FK existence (priority 4) before other well-formedness (priority 5).
    truck_id = require_fk(body, "truck_id")
    get_truck(truck_id)
    require_truck_ownership(user_id, role, truck_id)
    utility = require_enum(body, "utility", UTILITIES)

    propane_psi_after = None
    generator_delta_hours = None
    if utility == "PROPANE":
        # PROPANE must carry propane_psi_after; generator field ignored.
        propane_psi_after = require_number(body, "propane_psi_after", minimum=0)
    else:
        # GENERATOR must carry generator_delta_hours; propane field ignored.
        generator_delta_hours = require_number(body, "generator_delta_hours", minimum=0)

    rec = db.new_record({
        "truck_id": truck_id,
        "utility": utility,
        "propane_psi_after": propane_psi_after,
        "generator_delta_hours": generator_delta_hours,
        "logged_at": now_iso(),
    }, common_fields=False)
    db.utility_logs[rec["id"]] = rec

    truck = db.trucks.get(truck_id)
    if utility == "PROPANE":
        truck["propane_psi"] = propane_psi_after
    else:
        truck["generator_runtime_hours"] = truck["generator_runtime_hours"] + generator_delta_hours
    services.recompute_operability(truck)

    return ok_object(serializers.utility_log(rec), 201)


@bp.get("/utility-logs")
def list_utility_logs():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.utility_logs.values())
    truck_id = request.args.get("truck_id")
    if truck_id is not None:
        records = [r for r in records if r["truck_id"] == truck_id]
    utility = request.args.get("utility")
    if utility is not None:
        records = [r for r in records if r["utility"] == utility]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.utility_log(r) for r in window], limit, offset, total)


@bp.get("/utility-logs/<log_id>")
def get_utility_log_route(log_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_utility_log(log_id)
    return ok_object(serializers.utility_log(rec))
