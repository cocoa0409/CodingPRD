"""Unit endpoints (PRD §3.1)."""
from flask import Blueprint, request

from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public
from validate import get_body, req_date, req_int, req_str, require_body_ref

bp = Blueprint("units", __name__)


@bp.post("/pm/units")
def create_unit():
    authorized(["ManagerAdmin"])
    body = get_body()
    fields = {
        "property_id": req_str(body, "property_id"),
        "unit_number": req_str(body, "unit_number"),
        "carpet_installed_on": req_date(body, "carpet_installed_on"),
        "carpet_life_years": req_int(body, "carpet_life_years", non_negative=True),
        "paint_applied_on": req_date(body, "paint_applied_on"),
        "paint_life_years": req_int(body, "paint_life_years", non_negative=True),
    }
    require_body_ref("properties", fields["property_id"], "property_id")
    # A freshly created unit reads AVAILABLE (PRD §3.1).
    fields["occupancy_status"] = "AVAILABLE"
    rec = new_record("units", fields)
    return success_object(public(rec), status=201)


@bp.get("/pm/units/<rid>")
def get_unit(rid):
    return get_one("units", rid)


@bp.get("/pm/units")
def list_units():
    return list_response("units", {"property_id": request.args.get("property_id")})
