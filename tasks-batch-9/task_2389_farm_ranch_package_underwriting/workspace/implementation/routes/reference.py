"""Reference data: producers, inspectors, catastrophe capacity pools, clock."""

from flask import Blueprint

import services
from auth import ADMIN, ALL_ROLES, authenticate
from db import fmt_datetime, new_row, parse_datetime, store, touch
from errors import ApiError
from response import created, ok, ok_list, paginate
from validation import enum_filter, field, pagination, read_body, str_filter, validate

bp = Blueprint("reference", __name__)

APPOINTMENT_STATUSES = ("ACTIVE", "SUSPENDED")
INSPECTOR_STATUSES = ("ACTIVE", "INACTIVE")
PERILS = ("HAIL", "WIND", "WILDFIRE")
POOL_STATUSES = ("OPEN", "FROZEN")


# ------------------------------------------------------------------- producers

@bp.route("/agents", methods=["POST"])
def create_agent():
    authenticate(ADMIN)
    body = validate(read_body(), [
        field("agency_name", "string", required=True, minlen=1, maxlen=120),
        field("license_state", "string", required=True, minlen=2, maxlen=2, pattern=r"^[A-Z]{2}$"),
        field("appointment_status", "string", enum=APPOINTMENT_STATUSES),
        field("authority_limit_cents", "int", ge=0),
    ])
    row = new_row(
        agency_name=body["agency_name"],
        license_state=body["license_state"],
        appointment_status=body.get("appointment_status", "ACTIVE"),
        authority_limit_cents=body.get("authority_limit_cents", 5000000),
    )
    store.agents[row["id"]] = row
    return created(row)


@bp.route("/agents/<agent_id>", methods=["PATCH"])
def patch_agent(agent_id):
    authenticate(ADMIN)
    body = validate(read_body(), [
        field("appointment_status", "string", enum=APPOINTMENT_STATUSES),
        field("authority_limit_cents", "int", ge=0),
    ])
    row = services.require(store.agents, agent_id, "ERR_AGENT_NOT_FOUND")
    if "appointment_status" in body:
        row["appointment_status"] = body["appointment_status"]
    if "authority_limit_cents" in body:
        row["authority_limit_cents"] = body["authority_limit_cents"]
    touch(row)
    return ok(row)


@bp.route("/agents/<agent_id>", methods=["GET"])
def get_agent(agent_id):
    authenticate(*ALL_ROLES)
    return ok(services.require(store.agents, agent_id, "ERR_AGENT_NOT_FOUND"))


# ------------------------------------------------------------------ inspectors

@bp.route("/inspectors", methods=["POST"])
def create_inspector():
    authenticate(ADMIN)
    body = validate(read_body(), [
        field("full_name", "string", required=True, minlen=1, maxlen=120),
        field("region_code", "string", required=True, minlen=1, maxlen=12),
        field("status", "string", enum=INSPECTOR_STATUSES),
        field("daily_capacity_minutes", "int", ge=30),
    ])
    row = new_row(
        full_name=body["full_name"],
        region_code=body["region_code"],
        status=body.get("status", "ACTIVE"),
        daily_capacity_minutes=body.get("daily_capacity_minutes", 480),
    )
    store.inspectors[row["id"]] = row
    return created(row)


@bp.route("/inspectors/<inspector_id>", methods=["PATCH"])
def patch_inspector(inspector_id):
    authenticate(ADMIN)
    body = validate(read_body(), [
        field("status", "string", enum=INSPECTOR_STATUSES),
        field("daily_capacity_minutes", "int", ge=30),
    ])
    row = services.require(store.inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    if "status" in body:
        row["status"] = body["status"]
    if "daily_capacity_minutes" in body:
        row["daily_capacity_minutes"] = body["daily_capacity_minutes"]
    touch(row)
    return ok(row)


@bp.route("/inspectors/<inspector_id>", methods=["GET"])
def get_inspector(inspector_id):
    authenticate(*ALL_ROLES)
    return ok(services.require(store.inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND"))


# ------------------------------------------------------- catastrophe capacity

@bp.route("/cat-capacity-pools", methods=["POST"])
def create_pool():
    authenticate(ADMIN)
    body = validate(read_body(), [
        field("zone_code", "string", required=True, minlen=1, maxlen=24),
        field("peril", "string", required=True, enum=PERILS),
        field("participation_pct", "number", required=True, gt=0, le=1, max_dp=4),
        field("total_capacity_cents", "int", required=True, gt=0),
        field("status", "string", enum=POOL_STATUSES),
    ])
    if services.pool_for(body["zone_code"], body["peril"]) is not None:
        raise ApiError("ERR_DUPLICATE_POOL")
    row = new_row(
        zone_code=body["zone_code"],
        peril=body["peril"],
        participation_pct=body["participation_pct"],
        total_capacity_cents=body["total_capacity_cents"],
        reserved_cents=0,
        committed_cents=0,
        available_cents=body["total_capacity_cents"],
        status=body.get("status", "OPEN"),
    )
    store.pools[row["id"]] = row
    return created(row)


@bp.route("/cat-capacity-pools/<pool_id>", methods=["GET"])
def get_pool(pool_id):
    authenticate(*ALL_ROLES)
    return ok(services.require(store.pools, pool_id, "ERR_CAT_POOL_NOT_FOUND"))


@bp.route("/cat-capacity-pools", methods=["GET"])
def list_pools():
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    zone_code = str_filter("zone_code")
    peril = enum_filter("peril", PERILS)
    status = enum_filter("status", POOL_STATUSES)
    rows = [
        p for p in store.pools.values()
        if (zone_code is None or p["zone_code"] == zone_code)
        and (peril is None or p["peril"] == peril)
        and (status is None or p["status"] == status)
    ]
    from db import by_created
    window, total = paginate(by_created(rows), limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/cat-capacity-pools/<pool_id>", methods=["PATCH"])
def patch_pool(pool_id):
    authenticate(ADMIN)
    body = validate(read_body(), [
        field("expected_pool_version", "int", required=True, ge=1),
        field("total_capacity_cents", "int", gt=0),
        field("status", "string", enum=POOL_STATUSES),
    ])
    pool = services.require(store.pools, pool_id, "ERR_CAT_POOL_NOT_FOUND")
    if body["expected_pool_version"] != pool["version"]:
        raise ApiError("ERR_STALE_POOL_VERSION")
    if "total_capacity_cents" in body:
        pool["total_capacity_cents"] = body["total_capacity_cents"]
    if "status" in body:
        pool["status"] = body["status"]
    services.recompute_pool(pool)
    return ok(pool)


# ----------------------------------------------------------------- logical clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = validate(read_body(), [field("current_utc", "datetime", required=True)])
    parsed = parse_datetime(body["current_utc"])
    store.clock = parsed
    store.clock_raw = body["current_utc"]
    return ok({"current_utc": body["current_utc"]})
