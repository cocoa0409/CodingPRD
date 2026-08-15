"""Property endpoints (PRD §3.1)."""
from flask import Blueprint, request

from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public
from validate import get_body, req_int, req_str, require_body_ref

bp = Blueprint("properties", __name__)


@bp.post("/pm/properties")
def create_property():
    authorized(["ManagerAdmin"])
    body = get_body()
    fields = {
        "name": req_str(body, "name"),
        "address": req_str(body, "address"),
        "jurisdiction_profile_id": req_str(body, "jurisdiction_profile_id"),
        "key_charge_cents": req_int(body, "key_charge_cents", non_negative=True),
        "fob_charge_cents": req_int(body, "fob_charge_cents", non_negative=True),
        "lock_change_cents": req_int(body, "lock_change_cents", non_negative=True),
    }
    require_body_ref("jurisdiction_profiles", fields["jurisdiction_profile_id"],
                     "jurisdiction_profile_id")
    rec = new_record("properties", fields)
    return success_object(public(rec), status=201)


@bp.get("/pm/properties/<rid>")
def get_property(rid):
    return get_one("properties", rid)


@bp.get("/pm/properties")
def list_properties():
    return list_response("properties", {
        "jurisdiction_profile_id": request.args.get("jurisdiction_profile_id"),
    })
