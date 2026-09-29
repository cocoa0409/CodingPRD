from flask import Blueprint

import constants as C
import validators as V
from auth import authorize, current_role, current_user
from domain import (
    apply_changes, cert_effective_at, certification_posture, serialize_certification,
    suspend_agent,
)
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import as_dt, db, new_record, now_stamp, ordered, require

bp = Blueprint("certifications", __name__)

CERT_WRITE_ROLES = [C.ROLE_STATION_MANAGER, C.ROLE_SUBCONTRACTOR_ADMIN]
REVOKE_ROLES = [C.ROLE_SAFETY_OFFICER, C.ROLE_STATION_MANAGER]


@bp.post("/certifications")
def create_certification():
    authorize(CERT_WRITE_ROLES)
    payload = V.body()

    agent_id = V.req_string(payload, "agent_id")
    station_id = V.req_string(payload, "station_id")
    cert_type = V.req_enum(payload, "cert_type", C.CERT_TYPES)
    issued_at = V.req_datetime(payload, "issued_at")
    expires_at = V.req_datetime(payload, "expires_at")
    if as_dt(expires_at) <= as_dt(issued_at):
        raise ApiError("ERR_INVALID_REQUEST", "expires_at must be strictly after issued_at.")

    agent = require(db.agents, agent_id, "Agent")
    station = require(db.stations, station_id, "Station")

    if station["id"] != agent["station_id"]:
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")

    if current_role() == C.ROLE_SUBCONTRACTOR_ADMIN:
        if agent["subcontractor_id"] != current_user():
            raise ApiError("ERR_OWNERSHIP_VIOLATION")

    cert = new_record("Certification", {
        "agent_id": agent["id"],
        "station_id": station["id"],
        "cert_type": cert_type,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "status": "VALID",
        "currency_state": "LAPSED",
        "revoked_at": None,
        "revoked_reason": None,
    })
    db.certifications[cert["id"]] = cert

    posture = certification_posture(agent)
    apply_changes(agent, {"certification_posture": posture})
    if agent["status"] == "SUSPENDED" and cert_type == "RAMP_SAFETY" \
            and station["id"] == agent["station_id"] and cert_effective_at(cert, db.clock):
        apply_changes(agent, {"status": "ACTIVE"})

    return respond_object(serialize_certification(cert), 201)


@bp.get("/certifications/<certification_id>")
def read_certification(certification_id):
    authorize(C.ALL_ROLES)
    cert = require(db.certifications, certification_id, "Certification")
    return respond_object(serialize_certification(cert))


@bp.get("/certifications")
def list_certifications():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.certifications.values(), {
        "agent_id": "agent_id",
        "station_id": "station_id",
        "cert_type": "cert_type",
        "status": "status",
    })
    return paginate(ordered(records), serialize_certification)


@bp.post("/certifications/<certification_id>/revoke")
def revoke_certification(certification_id):
    authorize(REVOKE_ROLES)
    cert = require(db.certifications, certification_id, "Certification")
    payload = V.body()
    reason = V.req_string(payload, "reason")

    if cert["status"] != "VALID":
        raise ApiError("ERR_INVALID_STATE")

    agent = db.agents.get(cert["agent_id"])
    was_effective_ramp = (
        agent is not None
        and cert["cert_type"] == "RAMP_SAFETY"
        and cert["station_id"] == agent["station_id"]
        and cert_effective_at(cert, db.clock)
    )

    apply_changes(cert, {
        "status": "REVOKED",
        "revoked_at": now_stamp(),
        "revoked_reason": reason,
        "currency_state": "REVOKED",
    })

    if agent is not None:
        posture = certification_posture(agent)
        apply_changes(agent, {"certification_posture": posture})
        if was_effective_ramp and posture == "LAPSED" and agent["status"] == "ACTIVE":
            suspend_agent(agent)

    return respond_object(serialize_certification(cert))
