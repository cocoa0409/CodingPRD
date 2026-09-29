"""Build configurations (PRD section 3.5 opening paragraphs)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import lookup

configurations_bp = Blueprint("configurations", __name__, url_prefix="/upfit")


@configurations_bp.route("/build-configurations", methods=["POST"])
def create_build_configuration():
    middleware.require(middleware.ROLE_UPFIT_ENGINEER)
    payload = v.body()
    # 5. request shape
    config_code = v.req_str(payload, "config_code")
    chassis_model_id = v.req_str(payload, "chassis_model_id")
    body_spec_id = v.req_str(payload, "body_spec_id")
    standardization_tier = v.req_enum(payload, "standardization_tier", v.STANDARDIZATION_TIER)
    standard_equipment_spec_ids = v.req_id_list(payload, "standard_equipment_spec_ids", default=[])

    # 6. existence, in the order the endpoint declares the foreign keys
    model = lookup.chassis_model(chassis_model_id)
    body = lookup.body_spec(body_spec_id)
    for spec_id in standard_equipment_spec_ids:
        lookup.equipment_spec(spec_id)

    # 8. uniqueness
    for existing in db.build_configurations.values():
        if existing["config_code"] == config_code:
            raise ApiError(
                "ERR_DUPLICATE_CONFIG_CODE",
                "Configuration code '%s' is already in use." % config_code,
            )

    # 12. body builder book fit rules, in ladder order
    if model["cab_to_axle_in"] < body["required_min_ca_in"]:
        raise ApiError(
            "ERR_CAB_TO_AXLE_INSUFFICIENT",
            "Chassis cab-to-axle %s is below the body's minimum %s."
            % (model["cab_to_axle_in"], body["required_min_ca_in"]),
        )
    if model["wheelbase_in"] < body["required_min_wheelbase_in"]:
        raise ApiError(
            "ERR_WHEELBASE_INSUFFICIENT",
            "Chassis wheelbase %s is below the body's minimum %s."
            % (model["wheelbase_in"], body["required_min_wheelbase_in"]),
        )

    row = db.insert(
        db.build_configurations,
        {
            "config_code": config_code,
            "chassis_model_id": chassis_model_id,
            "body_spec_id": body_spec_id,
            "standardization_tier": standardization_tier,
            "standard_equipment_spec_ids": list(standard_equipment_spec_ids),
            "status": "DRAFT",
            "published_at": None,
        },
    )
    return response.object_response(db.serialize(row), 201)


@configurations_bp.route("/build-configurations/<build_configuration_id>/publish", methods=["POST"])
def publish_build_configuration(build_configuration_id):
    middleware.require(middleware.ROLE_UPFIT_ENGINEER)
    config = lookup.build_configuration(build_configuration_id)
    if config["status"] != "DRAFT":
        raise ApiError(
            "ERR_CONFIG_INVALID_STATE",
            "Only a DRAFT configuration may be published; this one is %s." % config["status"],
        )
    config["status"] = "PUBLISHED"
    config["published_at"] = db.clock_now_iso()
    db.touch(config)
    return response.object_response(db.serialize(config), 200)


@configurations_bp.route(
    "/build-configurations/<build_configuration_id>/deprecate", methods=["POST"]
)
def deprecate_build_configuration(build_configuration_id):
    middleware.require(middleware.ROLE_UPFIT_ENGINEER)
    config = lookup.build_configuration(build_configuration_id)
    if config["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_CONFIG_INVALID_STATE",
            "Only a PUBLISHED configuration may be deprecated; this one is %s." % config["status"],
        )
    config["status"] = "DEPRECATED"
    db.touch(config)
    return response.object_response(db.serialize(config), 200)


@configurations_bp.route("/build-configurations/<build_configuration_id>", methods=["GET"])
def get_build_configuration(build_configuration_id):
    middleware.require(*middleware.STAFF_ROLES)
    return response.object_response(
        db.serialize(lookup.build_configuration(build_configuration_id)), 200
    )


@configurations_bp.route("/build-configurations", methods=["GET"])
def list_build_configurations():
    middleware.require(*middleware.STAFF_ROLES)
    chassis_model_id = v.filter_str("chassis_model_id")
    body_spec_id = v.filter_str("body_spec_id")
    standardization_tier = v.filter_enum("standardization_tier", v.STANDARDIZATION_TIER)
    status = v.filter_enum("status", v.CONFIG_STATUS)
    rows = list(db.build_configurations.values())
    if chassis_model_id is not None:
        rows = [r for r in rows if r["chassis_model_id"] == chassis_model_id]
    if body_spec_id is not None:
        rows = [r for r in rows if r["body_spec_id"] == body_spec_id]
    if standardization_tier is not None:
        rows = [r for r in rows if r["standardization_tier"] == standardization_tier]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows)
