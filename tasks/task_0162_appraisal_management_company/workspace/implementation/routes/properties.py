"""Property endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
from services import serialize, validate

bp = Blueprint("properties", __name__)


@bp.route("/amc/properties", methods=["POST"])
def create_property():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "LenderUser"})
    data = validate.body()

    street = validate.require_str(data, "street_address")
    state_code = validate.require_str(data, "state_code")
    if not (len(state_code) == 2 and state_code.isupper() and state_code.isalpha()):
        raise errors.invalid_request("state_code must be a 2-letter uppercase code.")

    prior = data.get("prior_appraised_value_cents")
    if prior is not None:
        if isinstance(prior, bool) or not isinstance(prior, int):
            raise errors.invalid_request("prior_appraised_value_cents must be an integer or null.")

    prop = {
        "street_address": street,
        "state_code": state_code,
        "prior_appraised_value_cents": prior,
    }
    db.stamp_create(prop)
    db.properties[prop["id"]] = prop
    return response.ok_object(serialize.public(prop), 201)


@bp.route("/amc/properties/<pid>", methods=["GET"])
def get_property(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "LenderUser"})
    prop = db.properties.get(pid)
    if prop is None:
        raise errors.not_found("Property not found.")
    return response.ok_object(serialize.public(prop), 200)
