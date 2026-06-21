"""Attorney routes."""

from flask import Blueprint

import constants
import validators
from common import base_entity, get_or_404, serialize
from db import store
from middleware import get_json_body, roles
from response import object_response

bp = Blueprint("attorneys", __name__)


@bp.route("/legal/attorneys", methods=["POST"])
@roles("PlatformAdmin")
def create_attorney():
    body = get_json_body()
    full_name = validators.require_string(body, "full_name")
    bar_state = validators.require_enum(body, "bar_state", constants.STATE_CODES)

    ent = base_entity()
    ent.update({
        "full_name": full_name,
        "bar_state": bar_state,
    })
    store.attorneys[ent["id"]] = ent
    return object_response(serialize(ent), 201)


@bp.route("/legal/attorneys/<aid>", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_attorney(aid):
    ent = get_or_404(store.attorneys, aid)
    return object_response(serialize(ent), 200)
