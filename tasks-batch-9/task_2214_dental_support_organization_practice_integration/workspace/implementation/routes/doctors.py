"""Doctors: the licensed clinicians whose identities back two of the five roles."""

from flask import Blueprint

import config
import db
import middleware
import payload
import support
from errors import ApiError

bp = Blueprint("doctors", __name__)


@bp.post("/doctors")
@support.transactional
def create_doctor():
    middleware.authorize([config.ROLE_DEAL_COUNSEL, config.ROLE_INTEGRATION_LEAD])
    data = payload.body()
    full_name = payload.string(data, "full_name")
    npi = payload.digits(data, "npi", 10)
    license_number = payload.string(data, "license_number")
    license_state = payload.uppercase_code(data, "license_state", 2)
    is_seller_owner = payload.boolean(data, "is_seller_owner", default=False)
    specialty = payload.enum(
        data, "specialty", config.SPECIALTIES, required=False, default="GENERAL"
    )
    for existing in db.all_rows("doctors"):
        if existing["npi"] == npi:
            raise ApiError("ERR_DUPLICATE_NPI", "That NPI is already registered.")
    row = db.insert(
        "doctors",
        {
            "full_name": full_name,
            "npi": npi,
            "license_number": license_number,
            "license_state": license_state,
            "is_seller_owner": is_seller_owner,
            "specialty": specialty,
        },
    )
    return "doctors", row, 201


@bp.get("/doctors/<doctor_id>")
def get_doctor(doctor_id):
    middleware.authorize(config.ALL_ROLES)
    row = support.load("doctors", doctor_id)
    return support.read_one("doctors", row)
