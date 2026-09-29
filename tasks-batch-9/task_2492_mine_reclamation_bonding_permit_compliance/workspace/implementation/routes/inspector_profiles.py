"""Field inspector register (PRD 3.1)."""

from flask import Blueprint

import constants as C
import serialization as ser
from db import base_row, db
from response import created_response, object_response
from routes._shared import apply_filters, collection_filtered, paged
from validation import authorize, enum_field, get_body, lookup, str_field

bp = Blueprint("inspector_profiles", __name__)

LIST_FILTERS = [
    ("region", "region", None),
    ("certification_level", "certification_level", C.CERTIFICATION_LEVELS),
]


@bp.post("/mining/inspector-profiles")
def create_profile():
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    full_name = str_field(body, "full_name")
    certification_level = enum_field(body, "certification_level", C.CERTIFICATION_LEVELS)
    region = str_field(body, "region")

    row = base_row()
    row.update(
        {
            "full_name": full_name,
            "certification_level": certification_level,
            "region": region,
        }
    )
    db.inspector_profiles[row["id"]] = row
    return created_response(ser.inspector_profile_out(row))


@bp.get("/mining/inspector-profiles/<profile_id>")
def get_profile(profile_id):
    authorize(C.ROLES_INSPECTOR_PROFILE_READ)
    row = lookup(db.inspector_profiles, profile_id, "ERR_INSPECTOR_PROFILE_NOT_FOUND")
    return object_response(ser.inspector_profile_out(row))


@bp.get("/mining/inspector-profiles")
def list_profiles():
    authorize(C.ROLES_INSPECTOR_PROFILE_READ)
    return collection_filtered(
        db.inspector_profiles.values(), LIST_FILTERS, ser.inspector_profile_out
    )


@bp.get("/mining/inspector-profiles/<profile_id>/inspections")
def profile_inspections(profile_id):
    authorize(C.ROLES_INSPECTOR_PROFILE_READ)
    lookup(db.inspector_profiles, profile_id, "ERR_INSPECTOR_PROFILE_NOT_FOUND")
    rows = [i for i in db.inspections.values() if i["inspector_id"] == profile_id]
    rows = apply_filters(rows, [("status", "status", C.INSPECTION_STATUSES)])
    return paged(rows, ser.inspection_out)
