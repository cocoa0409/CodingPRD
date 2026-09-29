"""Brokerages and their state licences (PRD 3.1)."""

from flask import Blueprint

import auth
import serialize
import validation
from envelope import created, ok
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("brokers", __name__)

LICENSE_TYPES = ("SURPLUS_LINES", "RESIDENT_PRODUCER")


@bp.post("/brokers")
def create_broker():
    auth.require("PlatformAdmin")
    data = validation.body()
    firm_name = validation.req_str(data, "firm_name", max_len=200)
    home_state = validation.req_state_code(data, "home_state")
    rec = db.insert("brokers", {
        "firm_name": firm_name,
        "home_state": home_state,
        "status": "ACTIVE",
    })
    return created(serialize.public(rec))


@bp.get("/brokers/<rec_id>")
def get_broker(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("brokers", "broker", rec_id)
    return ok(serialize.public(rec))


@bp.post("/brokers/<rec_id>/suspend")
def suspend_broker(rec_id):
    auth.require("PlatformAdmin")
    rec = auth.path_entity("brokers", "broker", rec_id)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok(serialize.public(rec))


@bp.post("/brokers/<rec_id>/licenses")
def create_license(rec_id):
    auth.require("PlatformAdmin")
    broker = auth.path_entity("brokers", "broker", rec_id)
    data = validation.body()
    state_code = validation.req_state_code(data, "state_code")
    license_number = validation.req_str(data, "license_number")
    license_type = validation.req_enum(data, "license_type", LICENSE_TYPES)
    expires_at, expires_raw = validation.req_datetime(data, "expires_on")
    rec = db.insert("broker_licenses", {
        "broker_id": broker["id"],
        "state_code": state_code,
        "license_number": license_number,
        "license_type": license_type,
        "expires_on": expires_raw,
        "_expires_at": expires_at,
    })
    return created(serialize.broker_license(rec))


@bp.get("/brokers/<rec_id>/licenses")
def list_licenses(rec_id):
    auth.require(auth.ANY)
    broker = auth.path_entity("brokers", "broker", rec_id)
    rows = [r for r in db.all("broker_licenses")
            if r.get("broker_id") == broker["id"]]
    rows = filtered(rows, license_type=arg("license_type"),
                    state_code=arg("state_code"))
    return list_response(rows, serialize.broker_license)
