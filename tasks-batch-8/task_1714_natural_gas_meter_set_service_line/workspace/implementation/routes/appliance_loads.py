"""ApplianceLoad endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_FORBIDDEN_OWNER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOADS_LOCKED,
    ERR_STALE_VERSION,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    require_enum,
    require_fields,
    require_int,
    require_roles,
    spine_at_least,
)
from response import no_content, success_list, success_object
from services.calculations import counted_load_cfph
from services.domain import get_application, get_load, touch

bp = Blueprint("appliance_loads", __name__)

APPLIANCE_TYPES = (
    "FURNACE", "WATER_HEATER", "RANGE", "DRYER", "FIREPLACE",
    "STANDBY_GENERATOR", "POOL_HEATER", "OTHER",
)


def _owns(user_id, app):
    if app["builder_id"] != user_id:
        raise_error(ERR_FORBIDDEN_OWNER, "Builder does not own this application")


@bp.route("/appliance-loads", methods=["POST"])
def create_load():
    user_id, _ = require_roles("Builder")
    body = get_body()
    require_fields(body, "service_application_id", "appliance_type", "quantity", "btuh_input_rating")
    app = get_application(body["service_application_id"])
    _owns(user_id, app)
    appliance_type = require_enum(body, "appliance_type", APPLIANCE_TYPES)
    quantity = require_int(body, "quantity", minimum=1)
    btuh = require_int(body, "btuh_input_rating", minimum=1)
    check_app_mutable(app)
    # Rows may be added while DRAFT or SUBMITTED; LOAD_CONFIRMED or later → locked
    if spine_at_least(app, "LOAD_CONFIRMED"):
        raise_error(ERR_LOADS_LOCKED, "Loads are locked once the application is LOAD_CONFIRMED")
    now = db.now_iso()
    load = {
        "id": new_id(),
        "service_application_id": app["id"],
        "appliance_type": appliance_type,
        "quantity": quantity,
        "btuh_input_rating": btuh,
        "counted_load_cfph": counted_load_cfph(quantity, btuh),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.appliance_loads[load["id"]] = load
    return success_object(load, 201)


@bp.route("/appliance-loads/<lid>", methods=["GET"])
def get_one_load(lid):
    require_roles(*ANY_ROLE)
    return success_object(get_load(lid))


@bp.route("/appliance-loads", methods=["GET"])
def list_loads():
    require_roles(*ANY_ROLE)
    records = list(db.appliance_loads.values())
    app_id = request.args.get("service_application_id")
    if app_id is not None:
        records = [r for r in records if r["service_application_id"] == app_id]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/appliance-loads/<lid>", methods=["PATCH"])
def patch_load(lid):
    user_id, _ = require_roles("Builder")
    load = get_load(lid)
    app = get_application(load["service_application_id"])
    _owns(user_id, app)
    body = get_body()
    require_fields(body, "expected_load_version")
    if body["expected_load_version"] != load["version"]:
        raise_error(ERR_STALE_VERSION, "Load version is stale")
    check_app_mutable(app)
    if spine_at_least(app, "LOAD_CONFIRMED"):
        raise_error(ERR_LOADS_LOCKED, "Loads are locked once the application is LOAD_CONFIRMED")
    if app["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Loads may be edited only while the application is DRAFT")
    quantity = load["quantity"]
    btuh = load["btuh_input_rating"]
    if "quantity" in body:
        quantity = require_int(body, "quantity", minimum=1)
    if "btuh_input_rating" in body:
        btuh = require_int(body, "btuh_input_rating", minimum=1)
    load["quantity"] = quantity
    load["btuh_input_rating"] = btuh
    load["counted_load_cfph"] = counted_load_cfph(quantity, btuh)
    touch(load)
    return success_object(load)


@bp.route("/appliance-loads/<lid>", methods=["DELETE"])
def delete_load(lid):
    user_id, _ = require_roles("Builder")
    load = get_load(lid)
    app = get_application(load["service_application_id"])
    _owns(user_id, app)
    check_app_mutable(app)
    if spine_at_least(app, "LOAD_CONFIRMED"):
        raise_error(ERR_LOADS_LOCKED, "Loads are locked once the application is LOAD_CONFIRMED")
    if app["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Loads may be deleted only while the application is DRAFT")
    del db.appliance_loads[lid]
    return no_content()
