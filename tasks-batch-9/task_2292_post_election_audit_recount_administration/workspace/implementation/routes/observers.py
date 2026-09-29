"""ObserverCredential endpoints."""

from flask import Blueprint

from db import db, dt_of, insert, iso, touch
from errors import fail
from middleware import (
    ROLE_AUDIT_MANAGER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_ELECTIONS_DIRECTOR,
    guard,
)
from routes.common import list_endpoint, lookup, single
from services import calc
from validate import body, req_dt, req_enum, req_str

bp = Blueprint("observers", __name__)

PARTY_AFFILIATIONS = ("DEM", "REP", "UNAFFILIATED", "PRESS")
CREDENTIAL_STATUSES = ("ACTIVE", "REVOKED")
READ_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_CANDIDATE_REPRESENTATIVE,
)


@bp.post("/observer-credentials")
@guard([ROLE_ELECTIONS_DIRECTOR])
def create_observer_credential():
    data = body()
    election_id = req_str(data, "election_id", 1, None)
    organization_name = req_str(data, "organization_name", 1, None)
    party_affiliation = req_enum(data, "party_affiliation", PARTY_AFFILIATIONS)
    room_code = req_str(data, "room_code", 1, None)
    access_start_at = req_dt(data, "access_start_at")
    access_end_at = req_dt(data, "access_end_at")

    lookup("elections", election_id)

    if access_start_at >= access_end_at:
        fail("ERR_INVALID_TIME_WINDOW")

    overlapping = 0
    for other in db.observer_credentials.values():
        if other["status"] != "ACTIVE":
            continue
        if other["room_code"] != room_code:
            continue
        other_start = dt_of(other["access_start_at"])
        other_end = dt_of(other["access_end_at"])
        if access_start_at < other_end and other_start < access_end_at:
            overlapping += 1
    if overlapping >= calc.OBSERVER_ROOM_CAPACITY:
        fail("ERR_OBSERVER_ROOM_CAPACITY_EXCEEDED")

    row = insert(
        "observer_credentials",
        {
            "election_id": election_id,
            "organization_name": organization_name,
            "party_affiliation": party_affiliation,
            "room_code": room_code,
            "access_start_at": iso(access_start_at),
            "access_end_at": iso(access_end_at),
            "status": "ACTIVE",
            "revoked_reason": None,
        },
    )
    return single(row, 201)


@bp.get("/observer-credentials")
@guard(READ_ROLES)
def list_observer_credentials():
    return list_endpoint(
        "observer_credentials",
        {
            "election_id": ("election_id", None),
            "room_code": ("room_code", None),
            "status": ("status", CREDENTIAL_STATUSES),
        },
    )


@bp.get("/observer-credentials/<credential_id>")
@guard(READ_ROLES)
def get_observer_credential(credential_id):
    return single(lookup("observer_credentials", credential_id))


@bp.post("/observer-credentials/<credential_id>/revoke")
@guard([ROLE_ELECTIONS_DIRECTOR])
def revoke_observer_credential(credential_id):
    data = body()
    revoked_reason = req_str(data, "revoked_reason", 1, None)

    row = lookup("observer_credentials", credential_id)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_CREDENTIAL_STATE")

    row["status"] = "REVOKED"
    row["revoked_reason"] = revoked_reason
    touch(row)
    return single(row)
