"""Clinician registration and the live workload ledger (PRD §3.4)."""
from flask import Blueprint

import const
import validate
from common import base_record
from db import db
from errors import ApiError
from middleware import authenticate, get_clinician
from response import created, ok

bp = Blueprint("clinicians", __name__)


@bp.post("/cds/clinicians")
def register_clinician():
    authenticate((const.SYSTEM_ADMIN,))
    data = validate.body()

    full_name = validate.string(data, "full_name", required=True)
    specialty = validate.enum(data, "specialty", const.SPECIALTIES, required=True)
    roles = validate.array(data, "authorized_roles", required=True, min_len=1)
    for role in roles:
        if not isinstance(role, str) or role not in const.AUTHORIZED_ROLE_TOKENS:
            raise ApiError("ERR_INVALID_REQUEST", "authorized_roles contains an unknown role")
    npi = validate.string(data, "npi")
    credential = validate.enum(data, "credential", const.CREDENTIALS)
    employment_status = validate.enum(
        data, "employment_status", const.EMPLOYMENT_STATUSES, default="ACTIVE"
    )
    capacity = validate.integer(
        data, "review_workload_capacity_minutes",
        default=const.DEFAULT_CAPACITY_MINUTES, minimum=0,
    )

    clinician = base_record()
    clinician.update({
        "full_name": full_name,
        "npi": npi,
        "specialty": specialty,
        "credential": credential,
        "authorized_roles": list(roles),
        "employment_status": employment_status,
        "review_workload_capacity_minutes": capacity,
        "review_workload_assigned_minutes": 0,
        "review_workload_remaining_minutes": capacity,
        "open_assignment_count": 0,
    })
    db.clinicians[clinician["id"]] = clinician
    return created(clinician)


@bp.get("/cds/clinicians/<cid>")
def read_clinician(cid):
    authenticate(const.ANY_ROLE)
    return ok(get_clinician(cid))
