"""Agency endpoints (PRD 3.1)."""

from flask import Blueprint

from core.envelope import object_response
from core.pipeline import authorize, req_str
from core.serialize import agency as serialize_agency
from core.store import new_row

bp = Blueprint("agencies", __name__)


@bp.route("/api/agencies", methods=["POST"])
def create_agency():
    ctx = authorize("LicensingCoordinator", "CarrierAdmin")
    name = req_str(ctx.body, "name")
    resident_state_code = req_str(ctx.body, "resident_state_code")
    row = new_row("agencies", {
        "name": name,
        "resident_state_code": resident_state_code,
    })
    return object_response(serialize_agency(row), 201)
