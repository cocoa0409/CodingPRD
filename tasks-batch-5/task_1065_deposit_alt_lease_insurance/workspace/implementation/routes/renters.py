from flask import Blueprint
from db import db, new_common_fields
from errors import err
from middleware import get_caller, require_role
from response import object_response
from validate import body, require_str

renters_bp = Blueprint("renters", __name__)


@renters_bp.post("/renters")
def create_renter():
    caller = get_caller()
    require_role(caller, {"Anonymous"})
    b = body()
    full_name = require_str(b, "full_name")
    email = require_str(b, "email")
    phone_number = require_str(b, "phone_number")

    if any(r["email"] == email for r in db.renters.values()):
        raise err("ERR_VALIDATION", "email must be unique across renters.")

    renter = {
        **new_common_fields(),
        "full_name": full_name,
        "email": email,
        "phone_number": phone_number,
    }
    db.renters[renter["id"]] = renter
    return object_response(renter, 201)
