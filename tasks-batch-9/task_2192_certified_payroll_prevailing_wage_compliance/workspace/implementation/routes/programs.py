"""Apprenticeship programs."""

from flask import Blueprint

import db
import serializers as s
import validators as v
from auth import authenticate
from response import created, ok

bp = Blueprint("programs", __name__)

PROGRAM_STATUSES = ("REGISTERED", "PROVISIONAL", "LAPSED")


def get_program(program_id):
    return v.lookup(db.apprentice_programs, program_id, "ERR_PROGRAM_NOT_FOUND")


@bp.route("/apprentice-programs", methods=["POST"])
def create_program():
    authenticate(["PortalAdmin"])
    payload = v.body()
    registration_number = v.req_string(payload, "registration_number", min_len=1)
    sponsor_name = v.req_string(payload, "sponsor_name", min_len=1)
    trade_code = v.req_string(payload, "trade_code", min_len=2, max_len=12, upper=True)
    registration_status = v.opt_enum(
        payload, "registration_status", PROGRAM_STATUSES, default="REGISTERED"
    )
    allowed = v.req_int(
        payload, "allowed_apprentice_hours_per_100_journey", minimum=1, maximum=100
    )
    period_count = v.req_int(payload, "period_count", minimum=1, maximum=8)

    v.unique_or_reject(
        db.apprentice_programs,
        lambda r: r["registration_number"] == registration_number,
        "registration_number must be unique across all programs.",
    )

    row = db.base_row()
    row.update(
        {
            "registration_number": registration_number,
            "sponsor_name": sponsor_name,
            "trade_code": trade_code,
            "registration_status": registration_status,
            "allowed_apprentice_hours_per_100_journey": allowed,
            "period_count": period_count,
        }
    )
    db.apprentice_programs[row["id"]] = row
    return created(s.program(row))


@bp.route("/apprentice-programs/<program_id>", methods=["PATCH"])
def update_program(program_id):
    authenticate(["PortalAdmin"])
    program = get_program(program_id)
    payload = v.body()
    registration_status = v.req_enum(payload, "registration_status", PROGRAM_STATUSES)
    program["registration_status"] = registration_status
    db.touch(program)
    return ok(s.program(program))
