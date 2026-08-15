"""PackageConfiguration endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services.calculations as calc

bp = Blueprint("configurations", __name__)

VALID_ENCLOSURE_TYPES = {"OPEN", "WEATHERPROOF", "SOUND_ATTENUATED"}


def _compute_config_fields(config, order, study):
    """Compute usable_gallons, tank_price_cents, runtime_hours, min_runtime_hours."""
    engine = db.engine_models.get(study["engine_model_id"])
    if engine is None:
        raise errors.not_found("Engine model referenced by sizing study not found")
    usable, tank_price, runtime, min_runtime = calc.compute_fuel_config(
        order, engine["fuel_burn_gph_at_75"], config["fuel_tank_gallons"]
    )
    config["usable_gallons"] = usable
    config["tank_price_cents"] = tank_price
    config["runtime_hours"] = runtime
    config["min_runtime_hours"] = min_runtime


@bp.route("/genset-packaging/configurations", methods=["POST"])
def create_configuration():
    mw.require_roles("ApplicationEngineer")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    sizing_study_id = mw.require_string(body, "sizing_study_id")
    enclosure_type = mw.require_enum(body, "enclosure_type", VALID_ENCLOSURE_TYPES)
    enclosure_price_cents = mw.require_int(body, "enclosure_price_cents", minimum=0)
    fuel_tank_gallons = mw.require_int(body, "fuel_tank_gallons", minimum=1)

    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")
    study = db.sizing_studies.get(sizing_study_id)
    if study is None:
        raise errors.not_found("Sizing study not found")

    record = {
        "order_id": order_id,
        "sizing_study_id": sizing_study_id,
        "enclosure_type": enclosure_type,
        "enclosure_price_cents": enclosure_price_cents,
        "fuel_tank_gallons": fuel_tank_gallons,
        "usable_gallons": 0,
        "tank_price_cents": 0,
        "runtime_hours": 0,
        "min_runtime_hours": 0,
        "status": "DRAFT",
    }
    db.stamp_new(record)

    _compute_config_fields(record, order, study)

    db.configurations[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/configurations/<configurationId>", methods=["GET"])
def get_configuration(configurationId):
    mw.authenticate()
    record = db.configurations.get(configurationId)
    if record is None:
        raise errors.not_found("Package configuration not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/configurations", methods=["GET"])
def list_configurations():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.configurations.values())
    for param in ("order_id", "sizing_study_id"):
        val = mw.request.args.get(param)
        if val:
            items = [c for c in items if c.get(param) == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/configurations/<configurationId>/lock", methods=["POST"])
def lock_configuration(configurationId):
    mw.require_roles("ApplicationEngineer")

    config = db.configurations.get(configurationId)
    if config is None:
        raise errors.not_found("Package configuration not found")

    if config["status"] != "DRAFT":
        raise errors.ApiError(
            errors.ERR_CONFIG_STATE_INVALID, 409,
            "Configuration must be DRAFT to lock",
        )

    order = db.orders.get(config["order_id"])
    if order is None:
        raise errors.not_found("Package order not found")

    # Gate: order commercial_status must be AUTHORIZED
    if order["commercial_status"] != "AUTHORIZED":
        raise errors.ApiError(
            errors.ERR_INVALID_COMMERCIAL_STATE, 409,
            "Order commercial_status must be AUTHORIZED to lock configuration",
        )

    # Gate: linked sizing study must be APPROVED
    study = db.sizing_studies.get(config["sizing_study_id"])
    if study is None:
        raise errors.not_found("Sizing study not found")
    if study["status"] != "APPROVED":
        raise errors.ApiError(
            errors.ERR_SIZING_NOT_APPROVED, 409,
            "Linked sizing study must be APPROVED",
        )

    # Re-evaluate runtime fields at lock
    _compute_config_fields(config, order, study)

    # Gate: runtime_hours >= min_runtime_hours
    if config["runtime_hours"] < config["min_runtime_hours"]:
        raise errors.ApiError(
            errors.ERR_FUEL_RUNTIME_INSUFFICIENT, 422,
            "runtime_hours below min_runtime_hours",
        )

    # Compute order total price
    engine = db.engine_models.get(study["engine_model_id"])
    alternator = db.alternator_models.get(study["alternator_model_id"])
    if engine is None or alternator is None:
        raise errors.not_found("Catalog model not found")

    total_price, discount_tier = calc.compute_order_total(
        engine["list_price_cents"],
        alternator["list_price_cents"],
        config["enclosure_price_cents"],
        config["tank_price_cents"],
        order["freight_charge_cents"],
    )
    order["total_price_cents"] = total_price
    order["discount_tier"] = discount_tier

    config["status"] = "LOCKED"
    db.touch(config)

    # First LOCKED config -> order SIZING -> CONFIGURING
    if order["build_status"] == "SIZING":
        order["build_status"] = "CONFIGURING"
        db.touch(order)

    return resp.success_object(config)


@bp.route("/genset-packaging/configurations/<configurationId>/unlock", methods=["POST"])
def unlock_configuration(configurationId):
    mw.require_roles("ApplicationEngineer")

    config = db.configurations.get(configurationId)
    if config is None:
        raise errors.not_found("Package configuration not found")

    if config["status"] != "LOCKED":
        raise errors.ApiError(
            errors.ERR_CONFIG_STATE_INVALID, 409,
            "Configuration must be LOCKED to unlock",
        )

    # No live permit in SUBMITTED or APPROVED
    for p in db.permit_cases.values():
        if p["configuration_id"] == configurationId and p["status"] in ("SUBMITTED", "APPROVED"):
            raise errors.ApiError(
                errors.ERR_PERMIT_STATE_INVALID, 409,
                "A live permit (SUBMITTED or APPROVED) blocks unlock",
            )

    config["status"] = "DRAFT"
    db.touch(config)
    return resp.success_object(config)
