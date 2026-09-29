"""Catalogue endpoints: display models, burn-in chambers, crews, logical clock."""

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import serializers
import store
import validators as v
from errors import ApiError

bp = Blueprint("catalogue", __name__)


# ---------------------------------------------------------------------------
# Display models
# ---------------------------------------------------------------------------
@bp.route("/display-models", methods=["POST"])
def create_display_model():
    auth.require("PlantAdmin")
    body = v.body()
    payload = {
        "name": v.get_str(body, "name", min_len=1, max_len=80),
        "pixel_pitch_mm": v.get_num(body, "pixel_pitch_mm", exclusive_min=0, places=2),
        "rated_brightness_nits": v.get_int(body, "rated_brightness_nits", minimum=500),
        "environmental_rating": v.get_enum(body, "environmental_rating",
                                          calc.ENVIRONMENTAL_RATINGS),
        "module_width_mm": v.get_int(body, "module_width_mm", minimum=1),
        "module_height_mm": v.get_int(body, "module_height_mm", minimum=1),
        "module_pixel_cols": v.get_int(body, "module_pixel_cols", minimum=1),
        "module_pixel_rows": v.get_int(body, "module_pixel_rows", minimum=1),
        "cabinet_width_mm": v.get_int(body, "cabinet_width_mm", minimum=1),
        "cabinet_height_mm": v.get_int(body, "cabinet_height_mm", minimum=1),
        "modules_per_cabinet": v.get_int(body, "modules_per_cabinet", minimum=1),
        "cabinet_weight_kg": v.get_num(body, "cabinet_weight_kg", exclusive_min=0),
        "price_per_sqm_cents": v.get_int(body, "price_per_sqm_cents", minimum=1),
        "dead_pixel_ppm_limit": v.get_num(body, "dead_pixel_ppm_limit", minimum=0, places=2),
        "module_dead_pixel_max": v.get_int(body, "module_dead_pixel_max", required=False,
                                           minimum=0, default=3),
        "module_cluster_max": v.get_int(body, "module_cluster_max", required=False,
                                        minimum=0, default=1),
        "reference_color_x": v.get_num(body, "reference_color_x", exclusive_min=0,
                                       exclusive_max=1, places=4),
        "reference_color_y": v.get_num(body, "reference_color_y", exclusive_min=0,
                                       exclusive_max=1, places=4),
        "burn_in_hours_required": v.get_int(body, "burn_in_hours_required", minimum=1),
        "max_drive_pct": v.get_int(body, "max_drive_pct", minimum=1, maximum=100),
    }
    # Geometry is validated, never repaired (PRD section 3.1).
    if payload["cabinet_width_mm"] % payload["module_width_mm"] != 0:
        v.fail("cabinet_width_mm must be an exact multiple of module_width_mm.")
    if payload["cabinet_height_mm"] % payload["module_height_mm"] != 0:
        v.fail("cabinet_height_mm must be an exact multiple of module_height_mm.")
    expected = ((payload["cabinet_width_mm"] // payload["module_width_mm"])
                * (payload["cabinet_height_mm"] // payload["module_height_mm"]))
    if payload["modules_per_cabinet"] != expected:
        v.fail("modules_per_cabinet must equal the module columns times module rows "
               "that fit in a cabinet.")

    rec = store.new_record(payload)
    rec.update(calc.model_geometry(payload))
    store.display_models[rec["id"]] = rec
    return envelope.object_response(serializers.display_model(rec), 201)


@bp.route("/display-models/<display_model_id>", methods=["GET"])
def get_display_model(display_model_id):
    auth.require(*auth.ALL_ROLES)
    rec = store.display_models.get(display_model_id)
    if rec is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return envelope.object_response(serializers.display_model(rec))


@bp.route("/display-models", methods=["GET"])
def list_display_models():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    rating = v.query_enum("environmental_rating", calc.ENVIRONMENTAL_RATINGS)
    rows = aggregates.by_created(store.display_models.values())
    if rating is not None:
        rows = [r for r in rows if r["environmental_rating"] == rating]
    return envelope.paginated(rows, limit, offset, serializers.display_model)


# ---------------------------------------------------------------------------
# Burn-in chambers
# ---------------------------------------------------------------------------
@bp.route("/burn-in-chambers", methods=["POST"])
def create_chamber():
    auth.require("PlantAdmin")
    body = v.body()
    rec = store.new_record({
        "name": v.get_str(body, "name", min_len=1, max_len=60),
        "slot_capacity": v.get_int(body, "slot_capacity", minimum=1),
        "turnaround_minutes": v.get_int(body, "turnaround_minutes", minimum=0),
        "certified_max_drive_pct": v.get_int(body, "certified_max_drive_pct",
                                             minimum=1, maximum=100),
    })
    store.burn_in_chambers[rec["id"]] = rec
    return envelope.object_response(serializers.burn_in_chamber(rec), 201)


@bp.route("/burn-in-chambers/<burn_in_chamber_id>", methods=["GET"])
def get_chamber(burn_in_chamber_id):
    auth.require(*auth.ALL_ROLES)
    rec = store.burn_in_chambers.get(burn_in_chamber_id)
    if rec is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return envelope.object_response(serializers.burn_in_chamber(rec))


@bp.route("/burn-in-chambers", methods=["GET"])
def list_chambers():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    rows = aggregates.by_created(store.burn_in_chambers.values())
    return envelope.paginated(rows, limit, offset, serializers.burn_in_chamber)


# ---------------------------------------------------------------------------
# Commissioning crews
# ---------------------------------------------------------------------------
def _region_code(body, name):
    value = v.get_str(body, name, min_len=2, max_len=8)
    if not value.isupper() or not value.isalpha():
        v.fail("Field '%s' must be 2 to 8 uppercase characters." % name)
    return value


@bp.route("/commissioning-crews", methods=["POST"])
def create_crew():
    auth.require("PlantAdmin")
    body = v.body()
    rec = store.new_record({
        "name": v.get_str(body, "name", min_len=1, max_len=60),
        "region_code": _region_code(body, "region_code"),
        "certification_level": v.get_enum(body, "certification_level",
                                          calc.CERTIFICATION_LEVELS),
    })
    store.commissioning_crews[rec["id"]] = rec
    return envelope.object_response(serializers.commissioning_crew(rec), 201)


@bp.route("/commissioning-crews/<commissioning_crew_id>", methods=["GET"])
def get_crew(commissioning_crew_id):
    auth.require(*auth.ALL_ROLES)
    rec = store.commissioning_crews.get(commissioning_crew_id)
    if rec is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return envelope.object_response(serializers.commissioning_crew(rec))


@bp.route("/commissioning-crews", methods=["GET"])
def list_crews():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    region = v.query_str("region_code")
    level = v.query_enum("certification_level", calc.CERTIFICATION_LEVELS)
    rows = aggregates.by_created(store.commissioning_crews.values())
    if region is not None:
        rows = [r for r in rows if r["region_code"] == region]
    if level is not None:
        rows = [r for r in rows if r["certification_level"] == level]
    return envelope.paginated(rows, limit, offset, serializers.commissioning_crew)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth.require("PlantAdmin")
    body = v.body()
    value = v.get_dt(body, "to_iso8601")
    store.set_logical_now(value)
    return envelope.object_response({"current_utc": store.logical_now()})
