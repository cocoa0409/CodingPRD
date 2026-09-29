"""PRD 3.3 / 3.4 -- building configurations, locking and accessory kits."""

from flask import Blueprint, request

import constants as C
import serializers as S
import validation as V
from errors import ApiError
from middleware import ANY, roles_required
from response import object_response, paginated
from services import calc, domain
from store import db, new_row, now_iso, ordered, touch

bp = Blueprint("configurations", __name__)

COMPUTED_LOCK_FIELDS = (
    "building_length_ft",
    "footprint_sqft",
    "roof_slope_factor",
    "panel_area_sqft",
    "design_wind_pressure_psf",
    "dead_load_psf",
    "roof_snow_load_psf",
    "estimated_frame_weight_lbs",
)


@bp.route("/building-configurations", methods=["POST"])
@roles_required("SalesEngineer")
def create_configuration():
    data = V.body()
    builder_id = V.get_string(data, "builder_id")
    jurisdiction_id = V.get_string(data, "jurisdiction_id")
    clear_span_ft = V.get_number(data, "clear_span_ft", minimum=20, maximum=200)
    bay_spacing_ft = V.get_number(data, "bay_spacing_ft", minimum=15, maximum=30)
    bay_count = V.get_int(data, "bay_count", minimum=1, maximum=40)
    eave_height_ft = V.get_number(data, "eave_height_ft", minimum=10, maximum=60)
    roof_pitch = V.get_number(data, "roof_pitch_rise_per_12", minimum=0.25, maximum=6)
    panel_profile = V.get_enum(data, "panel_profile", C.PANEL_PROFILES)
    panel_color = V.get_enum(data, "panel_color", C.COLORS)
    insulation_r_value = V.get_int(data, "insulation_r_value", choices=C.INSULATION_R_VALUES)

    # Band 4: body foreign keys resolve in the order the input list declares them.
    builder = domain.get_builder(builder_id)
    jurisdiction = domain.get_jurisdiction(jurisdiction_id)

    # Band 8.
    if builder["status"] != "AUTHORIZED":
        raise ApiError("ERR_BUILDER_NOT_AUTHORIZED")

    fields = {
        "builder_id": builder["id"],
        "jurisdiction_id": jurisdiction["id"],
        "clear_span_ft": clear_span_ft,
        "bay_spacing_ft": bay_spacing_ft,
        "bay_count": bay_count,
        "eave_height_ft": eave_height_ft,
        "roof_pitch_rise_per_12": roof_pitch,
        "panel_profile": panel_profile,
        "panel_color": panel_color,
        "insulation_r_value": insulation_r_value,
        "criteria_revision_at_lock": None,
        "status": "DRAFT",
        "locked_at": None,
    }
    for name in COMPUTED_LOCK_FIELDS:
        fields[name] = None
    row = new_row(fields)
    db.configurations[row["id"]] = row
    return object_response(S.configuration_out(row), 201)


@bp.route("/building-configurations/<configuration_id>", methods=["GET"])
@roles_required(ANY)
def read_configuration(configuration_id):
    return object_response(S.configuration_out(domain.get_configuration(configuration_id)))


@bp.route("/building-configurations", methods=["GET"])
@roles_required(ANY)
def list_configurations():
    builder_id = request.args.get("builder_id")
    jurisdiction_id = request.args.get("jurisdiction_id")
    status = request.args.get("status")

    def predicate(row):
        if builder_id is not None and row["builder_id"] != builder_id:
            return False
        if jurisdiction_id is not None and row["jurisdiction_id"] != jurisdiction_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(ordered(db.configurations, predicate), S.configuration_out)


@bp.route("/building-configurations/<configuration_id>/lock", methods=["POST"])
@roles_required("SalesEngineer")
def lock_configuration(configuration_id):
    config = domain.get_configuration(configuration_id)
    builder = db.builders.get(config["builder_id"])

    # Band 8 precedes band 9.
    if builder is None or builder["status"] != "AUTHORIZED":
        raise ApiError("ERR_BUILDER_NOT_AUTHORIZED")
    if config["status"] not in ("DRAFT", "CRITERIA_STALE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    jurisdiction = db.jurisdictions.get(config["jurisdiction_id"])
    if jurisdiction is None:
        raise ApiError("ERR_JURISDICTION_NOT_FOUND")

    # A re-lock overwrites every previously stored load and weight field.
    config.update(calc.configuration_geometry_and_loads(config, jurisdiction))
    config["criteria_revision_at_lock"] = jurisdiction["criteria_revision"]
    config["locked_at"] = now_iso()
    config["status"] = "LOCKED"
    touch(config)
    return object_response(S.configuration_out(config))


@bp.route("/building-configurations/<configuration_id>/accessory-kits", methods=["POST"])
@roles_required("SalesEngineer")
def create_accessory_kit(configuration_id):
    data = V.body()
    kit_type = V.get_enum(data, "kit_type", C.KIT_TYPES)
    quantity = V.get_int(data, "quantity", minimum=1)
    unit_price_cents = V.get_int(data, "unit_price_cents", minimum=0)
    unit_weight_lbs = V.get_number(data, "unit_weight_lbs", minimum=0)
    erection_stage = V.get_enum(data, "erection_stage", C.ERECTION_STAGES)

    config = domain.get_configuration(configuration_id)

    row = new_row(
        {
            "configuration_id": config["id"],
            "kit_type": kit_type,
            "quantity": quantity,
            "unit_price_cents": unit_price_cents,
            "unit_weight_lbs": unit_weight_lbs,
            "erection_stage": erection_stage,
            # Exact integer product, no rounding.
            "extended_price_cents": unit_price_cents * quantity,
            "extended_weight_lbs": calc.rhu(calc.D(unit_weight_lbs) * calc.D(quantity), 2),
        }
    )
    db.accessory_kits[row["id"]] = row
    return object_response(S.accessory_kit_out(row), 201)


@bp.route("/building-configurations/<configuration_id>/accessory-kits", methods=["GET"])
@roles_required(ANY)
def list_accessory_kits(configuration_id):
    config = domain.get_configuration(configuration_id)
    kit_type = request.args.get("kit_type")

    def predicate(row):
        if row["configuration_id"] != config["id"]:
            return False
        if kit_type is not None and row["kit_type"] != kit_type:
            return False
        return True

    return paginated(ordered(db.accessory_kits, predicate), S.accessory_kit_out)
