"""Federation registries (officials, riders, horses) and the logical clock."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import serializers as ser
import validate as v
from auth import endpoint
from core import (
    COGGINS_VALIDITY_DAYS,
    DISCIPLINES,
    OFFICIAL_ROLES,
    db,
    fmt_dt,
    new_row,
)
from response import object_response

bp = Blueprint("registry", __name__)


@bp.post("/officials")
@endpoint("FederationOfficer")
def create_official():
    payload = v.body()
    federation_official_id = v.req_str(payload, "federation_official_id")
    full_name = v.req_str(payload, "full_name")
    license_roles = v.req_enum_array(payload, "license_roles", OFFICIAL_ROLES)
    license_level = v.req_int(payload, "license_level", minimum=1, maximum=4)
    licensed_disciplines = v.req_enum_array(payload, "licensed_disciplines", DISCIPLINES)
    license_expires_on = v.req_dt(payload, "license_expires_on")
    affiliated_trainer_name = v.opt_str(payload, "affiliated_trainer_name")

    official = new_row(
        db.officials,
        federation_official_id=federation_official_id,
        full_name=full_name,
        license_roles=license_roles,
        license_level=license_level,
        licensed_disciplines=licensed_disciplines,
        license_expires_on=license_expires_on,
        affiliated_trainer_name=affiliated_trainer_name,
        assigned_minutes=0,
    )
    return object_response(ser.ser_official(official), 201)


@bp.post("/riders")
@endpoint("FederationOfficer")
def create_rider():
    payload = v.body()
    federation_member_number = v.req_str(payload, "federation_member_number")
    full_name = v.req_str(payload, "full_name")
    membership_expires_on = v.req_dt(payload, "membership_expires_on")
    trainer_name = v.req_str(payload, "trainer_name")

    rider = new_row(
        db.riders,
        federation_member_number=federation_member_number,
        full_name=full_name,
        membership_expires_on=membership_expires_on,
        trainer_name=trainer_name,
        national_points_total=Decimal("0.0"),
        regional_points_total=0,
    )
    return object_response(ser.ser_rider(rider), 201)


@bp.post("/horses")
@endpoint("FederationOfficer")
def create_horse():
    payload = v.body()
    federation_registration_number = v.req_str(payload, "federation_registration_number")
    name = v.req_str(payload, "name")
    owner_name = v.req_str(payload, "owner_name")
    coggins_drawn_on = v.req_dt(payload, "coggins_drawn_on")

    horse = new_row(
        db.horses,
        federation_registration_number=federation_registration_number,
        name=name,
        owner_name=owner_name,
        coggins_drawn_on=coggins_drawn_on,
        coggins_expires_on=coggins_drawn_on + timedelta(days=COGGINS_VALIDITY_DAYS),
        eligibility_status="ELIGIBLE",
    )
    return object_response(ser.ser_horse(horse), 201)


@bp.post("/_clock/set_current_utc")
@endpoint("FederationOfficer")
def set_clock():
    payload = v.body()
    to_iso8601 = v.req_dt(payload, "to_iso8601")
    db.current_utc = to_iso8601
    return object_response({"current_utc": fmt_dt(db.current_utc)})
