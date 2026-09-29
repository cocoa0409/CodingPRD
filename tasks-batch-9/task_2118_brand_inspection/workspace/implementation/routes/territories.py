"""Inspection districts."""

from flask import Blueprint

from db import base_row, db, insert
from errors import ApiError
from middleware import endpoint
from response import object_response
from routes import lookup
from validation import body, req_int, req_state_code, req_str

bp = Blueprint("territories", __name__)


@bp.post("/territories")
@endpoint("BoardAdmin")
def create_territory():
    payload = body()
    territory_code = req_str(payload, "territory_code")
    state_code = req_state_code(payload, "state_code")
    travel_surcharge_cents = req_int(payload, "travel_surcharge_cents", minimum=0)
    impound_capacity_head = req_int(payload, "impound_capacity_head", minimum=1)

    for existing in db.territories.values():
        if existing["territory_code"] == territory_code:
            raise ApiError("ERR_DUPLICATE_TERRITORY_CODE", "territory_code is already on file.")

    row = base_row()
    row.update(
        {
            "territory_code": territory_code,
            "state_code": state_code,
            "travel_surcharge_cents": travel_surcharge_cents,
            "impound_capacity_head": impound_capacity_head,
            "impound_current_head": 0,
            "intake_status": "OPEN",
        }
    )
    insert(db.territories, row)
    return object_response(row, 201)


@bp.get("/territories/<territory_id>")
@endpoint("BoardAdmin", "FieldInspector", "BrandRecorder", "FeeAdministrator")
def read_territory(territory_id):
    return object_response(lookup.territory(territory_id))
