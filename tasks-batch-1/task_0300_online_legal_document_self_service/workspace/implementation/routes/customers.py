"""Customer routes."""

from flask import Blueprint

import constants
import validators
from common import base_entity, get_or_404, serialize
from db import store
from middleware import get_json_body, roles
from response import object_response

bp = Blueprint("customers", __name__)


@bp.route("/legal/customers", methods=["POST"])
@roles("Customer", "PlatformAdmin")
def create_customer():
    body = get_json_body()
    email = validators.require_string(body, "email")
    full_name = validators.require_string(body, "full_name")
    state = validators.require_enum(body, "state_of_residence", constants.STATE_CODES)

    ent = base_entity()
    ent.update({
        "email": email,
        "full_name": full_name,
        "state_of_residence": state,
    })
    store.customers[ent["id"]] = ent
    return object_response(serialize(ent), 201)


@bp.route("/legal/customers/<cid>", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def get_customer(cid):
    ent = get_or_404(store.customers, cid)
    return object_response(serialize(ent), 200)
