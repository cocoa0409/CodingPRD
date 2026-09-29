"""Test-driving logical clock endpoints."""

from flask import Blueprint

from db import db, iso
from response import ok
from validate import auth, body, req_datetime

bp = Blueprint("clock", __name__)

ALL_ROLES = (
    "FacilityAdministrator",
    "ComplianceOfficer",
    "RegistrationClerk",
    "EmergencyPhysician",
    "HospitalTransferCoordinator",
    "PayerRepresentative",
    "IDREntity",
)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(*ALL_ROLES)
    data = body()
    current_utc = req_datetime(data, "current_utc")
    # Stamps no rows and increments no version.
    db.clock = current_utc
    return ok({"current_utc": iso(db.clock)})


@bp.get("/_clock")
def read_clock():
    auth(*ALL_ROLES)
    return ok({"current_utc": iso(db.clock)})
