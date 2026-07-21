from flask import Blueprint, request
from db import db, new_common_fields
from errors import err
from middleware import get_caller, require_role, require_ownership
from response import object_response, array_response, parse_pagination, paginate
from validate import body, require_str
import lookups

landlords_bp = Blueprint("landlords", __name__)


@landlords_bp.post("/landlords")
def create_landlord():
    caller = get_caller()
    require_role(caller, {"Anonymous"})
    b = body()
    full_name = require_str(b, "full_name")
    email = require_str(b, "email")
    phone_number = require_str(b, "phone_number")

    if any(l["email"] == email for l in db.landlords.values()):
        raise err("ERR_VALIDATION", "email must be unique across landlords.")

    landlord = {
        **new_common_fields(),
        "full_name": full_name,
        "email": email,
        "phone_number": phone_number,
    }
    db.landlords[landlord["id"]] = landlord
    return object_response(landlord, 201)


@landlords_bp.get("/landlords/<landlord_id>")
def get_landlord(landlord_id):
    caller = get_caller()
    require_role(caller, {"Landlord", "ComplianceOfficer", "PlatformAdmin"})
    landlord = lookups.get_landlord(landlord_id)
    require_ownership(caller, landlord["id"], "Landlord")
    return object_response(landlord)


@landlords_bp.get("/landlords/<landlord_id>/properties")
def list_landlord_properties(landlord_id):
    caller = get_caller()
    require_role(caller, {"Landlord", "ComplianceOfficer", "PlatformAdmin"})
    landlord = lookups.get_landlord(landlord_id)
    require_ownership(caller, landlord["id"], "Landlord")

    limit, offset = parse_pagination(request.args)
    items = lookups.properties_for_landlord(landlord["id"])
    window, total = paginate(items, limit, offset)
    return array_response(window, 200, limit, offset, total)
