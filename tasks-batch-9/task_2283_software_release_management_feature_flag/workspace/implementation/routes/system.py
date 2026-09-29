"""Logical clock and environment registration."""

from flask import Blueprint

import db
import validate as v
from db import iso, make, store
from errors import fail
from middleware import ANY, authenticate
from response import object_response

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    body = v.get_body()
    moment = v.req_dt(body, "to_iso8601")
    db.set_clock(moment)
    return object_response({"current_utc": iso(db.now())})


@bp.post("/environments")
def create_environment():
    authenticate(("PlatformAdmin",))
    body = v.get_body()
    name = v.req_str(body, "name", allow_blank=False)
    tier = v.req_enum(body, "tier", ("DEV", "STAGING", "PROD"))
    start_hour = v.req_int(body, "deploy_window_start_hour_utc", minimum=0, maximum=23)
    end_hour = v.req_int(body, "deploy_window_end_hour_utc", minimum=1, maximum=24)
    if end_hour <= start_hour:
        v.bad("deploy_window_end_hour_utc must be strictly greater than deploy_window_start_hour_utc")
    cooldown = v.opt_int(body, "cooldown_minutes", default=30, minimum=0)
    blackout_start = v.opt_dt(body, "blackout_start_at")
    blackout_end = v.opt_dt(body, "blackout_end_at")
    regulated = v.opt_bool(body, "requires_compliance_evidence", default=False)

    for existing in store.environments.values():
        if existing["name"] == name:
            fail("ERR_INVALID_REQUEST", "Environment name '%s' already exists" % name)

    env = make(
        "environments",
        {
            "name": name,
            "tier": tier,
            "cooldown_minutes": cooldown,
            "deploy_window_start_hour_utc": start_hour,
            "deploy_window_end_hour_utc": end_hour,
            "blackout_start_at": blackout_start,
            "blackout_end_at": blackout_end,
            "requires_compliance_evidence": regulated,
            "active_deployment_count": 0,
            "last_deployment_end_at": None,
        },
    )
    return object_response(db.public(env), 201)


@bp.get("/environments/<environment_id>")
def read_environment(environment_id):
    authenticate(ANY)
    env = db.get_environment(environment_id)
    return object_response(db.public(env))
