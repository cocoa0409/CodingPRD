"""Carrier registration, reads and the per-carrier compliance sweep."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (PROGRAM_ADMINISTRATOR, PROVIDER_STATUSES, ROLES_ALL,
                           authenticate, get_provider)
from services import cascades, derive

bp = Blueprint("providers", __name__)


@bp.post("/lifeline/providers")
def create_provider():
    authenticate((PROGRAM_ADMINISTRATOR,))
    body = v.get_body()
    name = v.string_field(body, "name", min_len=1, max_len=120)
    spin_id = v.string_field(body, "spin_id", pattern=r"^\d{9}$", min_len=9, max_len=9)
    study_area_code = v.string_field(body, "study_area_code", pattern=r"^\d{6}$",
                                     min_len=6, max_len=6)
    licensed = v.string_list_field(body, "licensed_state_codes",
                                   item_pattern=r"^[A-Za-z]{2}$", min_items=1)
    status = v.enum_field(body, "status", PROVIDER_STATUSES, required=False,
                          default="ACTIVE")
    enrollment_cap = v.int_field(body, "enrollment_cap", required=False, minimum=1,
                                 default=1000)

    for existing in db.db.providers.values():
        if existing["spin_id"] == spin_id:
            raise ApiError("ERR_INVALID_REQUEST",
                           "spin_id must be unique across carriers")

    row = db.base_row()
    row.update({
        "name": name,
        "spin_id": spin_id,
        "study_area_code": study_area_code,
        "licensed_state_codes": list(licensed),
        "status": status,
        "enrollment_cap": enrollment_cap,
    })
    db.db.providers[row["id"]] = row
    return response.ok(derive.provider_json(row), 201)


@bp.get("/lifeline/providers/<provider_id>")
def read_provider(provider_id):
    authenticate(ROLES_ALL)
    provider = get_provider(provider_id)
    return response.ok(derive.provider_json(provider))


@bp.post("/lifeline/providers/<provider_id>/compliance-sweep")
def compliance_sweep(provider_id):
    caller = authenticate((PROGRAM_ADMINISTRATOR,))
    provider = get_provider(provider_id)
    result = cascades.compliance_sweep(provider, caller.user_id)
    return response.ok(result)
