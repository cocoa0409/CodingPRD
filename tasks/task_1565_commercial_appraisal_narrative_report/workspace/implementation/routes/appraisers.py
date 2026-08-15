from flask import Blueprint

import response
from db import store, new_rec, touch, serialize
from errors import ApiError, ERR_INVALID_STATE
from middleware import auth, require_role, get_body, req_str, req_enum
from services import domain

bp = Blueprint("appraisers", __name__)

DESIGNATIONS = ("TRAINEE", "CERTIFIED_GENERAL", "MAI")
LICENSE_STATUSES = ("ACTIVE", "SUSPENDED", "EXPIRED")
ALLOWED_LICENSE_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "EXPIRED"),
    ("SUSPENDED", "EXPIRED"),
    ("EXPIRED", "ACTIVE"),
}


@bp.post("/appraisers")
def create_appraiser():
    _, role = auth()
    require_role(role, {"EngagementManager"})
    body = get_body()
    full_name = req_str(body, "full_name")
    designation = req_enum(body, "designation", DESIGNATIONS)
    rec = new_rec(
        {"full_name": full_name, "designation": designation, "license_status": "ACTIVE"}
    )
    store.appraisers[rec["id"]] = rec
    return response.success(serialize(rec), status=201)


@bp.get("/appraisers/<appraiserId>")
def get_appraiser(appraiserId):
    auth()
    rec = domain.get_appraiser(appraiserId)
    return response.success(serialize(rec))


@bp.post("/appraisers/<appraiserId>/license_status")
def set_license_status(appraiserId):
    _, role = auth()
    require_role(role, {"EngagementManager"})
    rec = domain.get_appraiser(appraiserId)
    body = get_body()
    status = req_enum(body, "status", LICENSE_STATUSES)
    if (rec["license_status"], status) not in ALLOWED_LICENSE_TRANSITIONS:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            f"License status cannot move from {rec['license_status']} to {status}",
        )
    rec["license_status"] = status
    touch(rec)
    return response.success(serialize(rec))
