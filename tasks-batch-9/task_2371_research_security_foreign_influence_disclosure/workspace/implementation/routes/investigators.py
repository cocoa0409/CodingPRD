"""Investigator registration and reads (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import db
import response
import util
import validate
from errors import ApiError
from middleware import (SYSTEM_ADMIN, require, require_any)
from routes.common import must_exist, render_list
from services import derive, enums as E, present

bp = Blueprint("investigators", __name__)


@bp.post("/investigators")
def create_investigator():
    require(SYSTEM_ADMIN)
    data = validate.body()

    full_name = validate.req_string(data, "full_name")
    email = validate.req_string(data, "email")
    appointment_type = validate.req_enum(data, "appointment_type",
                                         E.APPOINTMENT_TYPES)
    home_department = validate.req_string(data, "home_department")
    base = validate.opt_decimal(data, "institutional_base_effort_pct",
                                minimum=0, maximum=100,
                                default=Decimal("100"))

    for existing in db.investigators.values():
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL",
                           "Email '%s' is already on file." % email)

    record = db.base_record()
    record.update({
        "full_name": full_name,
        "email": email,
        "appointment_type": appointment_type,
        "home_department": home_department,
        "institutional_base_effort_pct": base,
        "committed_effort_pct": Decimal("0"),
        "outside_effort_pct": Decimal("0"),
        "total_commitment_pct": base,
        "overcommitment_pct": Decimal("0"),
        "risk_score": 0,
        "substantiated_incident_count": 0,
        "material_discrepancy_count": 0,
        "training_compliant": True,
        "disclosure_posture": "CLEAR",
    })
    db.investigators[record["id"]] = record
    return response.object_response(present.investigator(record), 201)


@bp.get("/investigators/<investigator_id>")
def read_investigator(investigator_id):
    require_any()
    record = must_exist("investigator", investigator_id)
    return response.object_response(present.investigator(record))


@bp.get("/investigators")
def list_investigators():
    require_any()
    appointment_type = validate.filter_enum("appointment_type",
                                            E.APPOINTMENT_TYPES)
    posture = validate.filter_enum("disclosure_posture", E.DISCLOSURE_POSTURES)

    rows = []
    for record in db.ordered(db.investigators.values()):
        derive.compute_investigator(record)
        if appointment_type and record["appointment_type"] != appointment_type:
            continue
        if posture and record["disclosure_posture"] != posture:
            continue
        rows.append(record)
    return render_list(rows, present.investigator)
