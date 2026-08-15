"""Buyer registration (PRD section 3.2): the one act open to Anonymous."""

import db
from middleware import authenticate
from response import success_obj
from routes import make_blueprint
from services import ser_buyer
from util import body_json, check_shape

bp = make_blueprint("buyers")

CREATE_SPEC = {
    "full_name": {"type": "string", "required": True},
    "email": {"type": "string", "required": True},
}


@bp.post("/buyers")
def register_buyer():
    authenticate(["Anonymous"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    buyer = db.new_entity("buyers", {
        "full_name": body["full_name"],
        "email": body["email"],
    })
    return success_obj(ser_buyer(buyer), 201)
