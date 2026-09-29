"""Institution registration and reads (PRD 3.1)."""
from flask import Blueprint

from db import db, new_record, serialize
from errors import ApiError
from helpers import fetch, list_and_respond, require_usd
from middleware import (
    ALL_ROLES,
    ROLE_ANALYST,
    get_body,
    opt_enum,
    opt_str,
    req_enum,
    req_str,
    require_roles,
)
from response import object_response

institutions_bp = Blueprint("institutions", __name__)

CHARTER_TYPES = ("NATIONAL", "STATE_MEMBER", "STATE_NONMEMBER", "SAVINGS")
REGULATORS = ("OCC", "FRB", "FDIC")
CRA_RATINGS = ("OUTSTANDING", "SATISFACTORY", "NEEDS_TO_IMPROVE", "SUBSTANTIAL_NONCOMPLIANCE")
REQUIRED_REGULATOR = {
    "NATIONAL": "OCC",
    "STATE_MEMBER": "FRB",
    "STATE_NONMEMBER": "FDIC",
    "SAVINGS": "FDIC",
}
CAPITAL_FIELDS = (
    "cet1_capital_usd",
    "tier1_capital_usd",
    "total_capital_usd",
    "risk_weighted_assets_usd",
    "average_total_assets_usd",
    "total_loans_usd",
)


@institutions_bp.post("/institutions")
@require_roles(ROLE_ANALYST)
def create_institution():
    body = get_body(required=True)
    legal_name = req_str(body, "legal_name", min_len=1, max_len=160)
    charter_type = req_enum(body, "charter_type", CHARTER_TYPES)
    primary_regulator = req_enum(body, "primary_regulator", REGULATORS)
    capital = {field: require_usd(body, field, required=False) for field in CAPITAL_FIELDS}
    latest_cra_rating = opt_enum(body, "latest_cra_rating", CRA_RATINGS, default="SATISFACTORY")
    cra_exam_closed_at = opt_str(body, "cra_exam_closed_at", default=None)

    if REQUIRED_REGULATOR[charter_type] != primary_regulator:
        raise ApiError(
            "ERR_REGULATOR_CHARTER_MISMATCH",
            "a %s charter requires %s" % (charter_type, REQUIRED_REGULATOR[charter_type]),
        )

    fields = {
        "legal_name": legal_name,
        "charter_type": charter_type,
        "primary_regulator": primary_regulator,
    }
    fields.update(capital)
    fields.update(
        {
            "latest_cra_rating": latest_cra_rating,
            "cra_exam_closed_at": cra_exam_closed_at,
            "status": "ACTIVE",
            "total_deposits_usd": 0,
            "branch_count": 0,
        }
    )
    record = new_record(fields)
    db.institutions[record["id"]] = record
    return object_response(serialize(record), 201)


@institutions_bp.get("/institutions/<record_id>")
@require_roles(*ALL_ROLES)
def get_institution(record_id):
    return object_response(serialize(fetch("institutions", record_id)))


@institutions_bp.get("/institutions")
@require_roles(*ALL_ROLES)
def list_institutions():
    return list_and_respond("institutions", ("charter_type", "primary_regulator", "status"))
