from flask import Blueprint

import store
from common import (ApiError, authorize, ok_object, serialize, get_body,
                    require_str, optional_str, require_landlord_owner)

bp = Blueprint("landlords", __name__)


@bp.post("/api/landlords")
def create_landlord():
    uid, role = authorize(["PlatformAdmin"])
    body = get_body()
    company_name = require_str(body, "company_name")
    email = require_str(body, "email")
    contact_name = optional_str(body, "contact_name")
    l = store.base_fields()
    l.update({
        "company_name": company_name,
        "email": email,
        "contact_name": contact_name,
    })
    store.landlords[l["id"]] = l
    return ok_object(serialize(l), 201)


@bp.get("/api/landlords/<landlord_id>")
def get_landlord(landlord_id):
    uid, role = authorize(["PlatformAdmin", "Landlord"])
    l = store.landlords.get(landlord_id)
    if l is None:
        raise ApiError("ERR_LANDLORD_NOT_FOUND", "landlord not found")
    require_landlord_owner(role, uid, l["id"])
    return ok_object(serialize(l))
