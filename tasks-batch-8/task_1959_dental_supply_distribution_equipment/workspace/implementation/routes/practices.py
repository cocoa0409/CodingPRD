"""Practice onboarding and credit hold (PRD section 3.1)."""

from flask import Blueprint

import envelope
from auth import auth_and_roles
from calc import practice_json
from db import STORES
from errors import ApiError
from util import (
    base_record,
    body,
    get_or_404,
    parse_dt,
    touch,
    v_bool,
    v_enum,
    v_int,
    v_str,
)

bp = Blueprint("practices", __name__)

PRACTICE_TIERS = {"STANDARD", "PREMIER", "ELITE"}


@bp.post("/practices")
def create_practice():
    auth_and_roles(["DistributionAdmin"])
    data = body()
    name = v_str(data, "name")
    region = v_str(data, "region")
    tier = v_enum(data, "practice_tier", PRACTICE_TIERS, required=False, default="STANDARD")
    credit_limit = v_int(data, "credit_limit_cents", min_val=0)
    sterile = v_bool(data, "sterilization_compliant", required=False, default=False)

    license_raw = data.get("regulated_license_expiry")
    license_dt = None
    if license_raw is not None:
        license_dt = parse_dt(license_raw)
        if license_dt is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "regulated_license_expiry is malformed"
            )

    record = base_record()
    record.update(
        {
            "name": name,
            "region": region,
            "practice_tier": tier,
            "credit_limit_cents": credit_limit,
            "credit_available_cents": credit_limit,
            "regulated_license_expiry": license_raw,
            "sterilization_compliant": sterile,
            "status": "ACTIVE",
            "_license_dt": license_dt,
        }
    )
    STORES["practices"][record["id"]] = record
    return envelope.success(practice_json(record), "object", 201)


@bp.get("/practices/<rid>")
def get_practice(rid):
    uid, role = auth_and_roles(["DistributionAdmin", "SalesRep", "PracticeManager"])
    practice = get_or_404("practices", rid)
    if role == "PracticeManager" and practice["id"] != uid:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "PracticeManager may only read their own practice"
        )
    return envelope.success(practice_json(practice))


@bp.post("/practices/<rid>/suspend")
def suspend_practice(rid):
    auth_and_roles(["DistributionAdmin"])
    practice = get_or_404("practices", rid)
    if practice["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Practice is not ACTIVE")
    practice["status"] = "SUSPENDED"
    touch(practice)
    return envelope.success(practice_json(practice))


@bp.post("/practices/<rid>/reinstate")
def reinstate_practice(rid):
    auth_and_roles(["DistributionAdmin"])
    practice = get_or_404("practices", rid)
    if practice["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Practice is not SUSPENDED")
    practice["status"] = "ACTIVE"
    touch(practice)
    return envelope.success(practice_json(practice))
