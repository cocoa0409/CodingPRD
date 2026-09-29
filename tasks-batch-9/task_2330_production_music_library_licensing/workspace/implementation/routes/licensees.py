"""Licensee endpoints."""

from flask import Blueprint

from db import DB
from middleware import body, req_enum, req_int, req_string, require_role
from response import object_response
from routes.common import LICENSEE_TYPES, PREFIX, guard_licensee
from services.derive import lookup, serialize_licensee

bp = Blueprint("licensees", __name__)


@bp.post(PREFIX + "/licensees")
def create_licensee():
    data = body()
    legal_name = req_string(data, "legal_name", allow_empty=False)
    licensee_type = req_enum(data, "licensee_type", LICENSEE_TYPES)
    credit_limit = req_int(data, "credit_limit_cents", 0, None)
    require_role("LicensingAgent")

    row = DB.new_row()
    row.update(
        {
            "legal_name": legal_name,
            "licensee_type": licensee_type,
            "credit_limit_cents": credit_limit,
        }
    )
    DB.licensees[row["id"]] = row
    return object_response(serialize_licensee(row), 201)


@bp.get(PREFIX + "/licensees/<licensee_id>")
def get_licensee(licensee_id):
    row = lookup("licensees", licensee_id)
    require_role("LicensingAgent", "RightsManager", "RoyaltyAccountant", "Licensee")
    guard_licensee(row["id"])
    return object_response(serialize_licensee(row))
