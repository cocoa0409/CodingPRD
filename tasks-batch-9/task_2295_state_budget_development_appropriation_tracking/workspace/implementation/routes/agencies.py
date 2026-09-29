"""Agencies (PRD 3.1)."""

from flask import Blueprint

import auth
import db
import response
from errors import fail
from services import constants as C
from services import core
from validators import body_json, read_enum, read_str

bp = Blueprint("agencies", __name__)


@bp.post("/fiscal/agencies")
def create_agency():
    auth.authenticate((auth.SYSTEM_ADMIN,))
    body = body_json()
    agency_code = read_str(body, "agency_code", min_len=1, max_len=12)
    name = read_str(body, "name", min_len=1, max_len=200)
    agency_type = read_enum(body, "agency_type", C.AGENCY_TYPES)

    for existing in db.agencies.values():
        if existing["agency_code"] == agency_code:
            fail("ERR_DUPLICATE_CODE", "agency_code '%s' is already registered." % agency_code)

    row = db.new_row()
    row.update(
        {
            "agency_code": agency_code,
            "name": name,
            "agency_type": agency_type,
            "federal_compliance_flag": "CLEAR",
        }
    )
    db.agencies[row["id"]] = row
    return response.created(db.serialize(row))


@bp.get("/fiscal/agencies/<agency_id>")
def read_agency(agency_id):
    auth.authenticate(auth.ANY_ROLE)
    row = core.get_agency(agency_id)
    return response.ok(db.serialize(row))
