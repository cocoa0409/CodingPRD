"""Module manufacturing endpoints: registration, pixel test, calibration, reads."""

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import serializers
import store
import validators as v
from errors import ApiError

bp = Blueprint("modules", __name__)


def _apply_rework(module):
    """Uniform rework accounting (calculations.module_rework_cycle_accounting)."""
    candidate = module["rework_cycles"] + 1
    module["rework_cycles"] = candidate
    module["module_state"] = "SCRAPPED" if candidate > calc.MAX_REWORK_CYCLES else "REWORK"


@bp.route("/modules", methods=["POST"])
def create_module():
    auth.require("ProductionOperator")
    body = v.body()
    display_model_id = v.get_id(body, "display_model_id")
    serial_no = v.get_str(body, "serial_no", min_len=1, max_len=40)
    if store.display_models.get(display_model_id) is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    if any(m["serial_no"] == serial_no for m in store.modules.values()):
        raise ApiError("ERR_MODULE_SERIAL_DUPLICATE")
    rec = store.new_record({
        "display_model_id": display_model_id,
        "serial_no": serial_no,
        "cabinet_id": None,
        "slot_index": None,
        "replaces_module_id": None,
        "reserved_service_contract_id": None,
        "dead_pixel_count": None,
        "max_cluster_size": None,
        "measured_brightness_nits": None,
        "measured_color_x": None,
        "measured_color_y": None,
        "color_bin": None,
        "color_bin_rank": None,
        "rework_cycles": 0,
        "calibrated_by_user_id": None,
        "module_state": "MANUFACTURED",
    })
    store.modules[rec["id"]] = rec
    return envelope.object_response(serializers.module(rec), 201)


@bp.route("/modules/<module_id>/pixel-test", methods=["POST"])
def pixel_test(module_id):
    auth.require("ProductionOperator")
    body = v.body()
    dead = v.get_int(body, "dead_pixel_count", minimum=0)
    cluster = v.get_int(body, "max_cluster_size", minimum=0)
    module = store.modules.get(module_id)
    if module is None:
        raise ApiError("ERR_MODULE_NOT_FOUND")
    if module["module_state"] not in ("MANUFACTURED", "REWORK"):
        raise ApiError("ERR_INVALID_MODULE_STATE")
    model = store.display_models.get(module["display_model_id"])

    module["dead_pixel_count"] = dead
    module["max_cluster_size"] = cluster
    passed = (dead <= model["module_dead_pixel_max"]
              and cluster <= model["module_cluster_max"])
    if passed:
        module["module_state"] = "PIXEL_TESTED"
    else:
        _apply_rework(module)
    store.touch(module)
    return envelope.object_response(serializers.module(module))


@bp.route("/modules/<module_id>/calibrate", methods=["POST"])
def calibrate(module_id):
    user_id, _ = auth.require("ProductionOperator")
    body = v.body()
    brightness = v.get_int(body, "measured_brightness_nits", minimum=0)
    color_x = v.get_num(body, "measured_color_x", exclusive_min=0, exclusive_max=1, places=4)
    color_y = v.get_num(body, "measured_color_y", exclusive_min=0, exclusive_max=1, places=4)
    module = store.modules.get(module_id)
    if module is None:
        raise ApiError("ERR_MODULE_NOT_FOUND")
    if module["module_state"] not in ("PIXEL_TESTED", "REWORK"):
        raise ApiError("ERR_INVALID_MODULE_STATE")
    model = store.display_models.get(module["display_model_id"])

    err = calc.chroma_error(color_x, color_y, model)
    # rung 46 — nothing is stored, rework_cycles untouched, no state change
    if err > calc.CHROMA_REWORK_TOLERANCE:
        raise ApiError("ERR_CHROMA_OUT_OF_TOLERANCE")

    module["measured_brightness_nits"] = brightness
    module["measured_color_x"] = color_x
    module["measured_color_y"] = color_y
    if err > calc.CHROMA_CALIBRATED_TOLERANCE:
        module["color_bin"] = None
        module["color_bin_rank"] = None
        _apply_rework(module)
    else:
        bin_name = calc.color_bin_for(err, brightness, model)
        module["color_bin"] = bin_name
        module["color_bin_rank"] = calc.COLOR_BIN_RANKS[bin_name]
        module["calibrated_by_user_id"] = user_id
        module["module_state"] = "CALIBRATED"
    store.touch(module)
    return envelope.object_response(serializers.module(module))


@bp.route("/modules/<module_id>", methods=["GET"])
def get_module(module_id):
    auth.require(*auth.ALL_ROLES)
    module = store.modules.get(module_id)
    if module is None:
        raise ApiError("ERR_MODULE_NOT_FOUND")
    return envelope.object_response(serializers.module(module))


@bp.route("/modules", methods=["GET"])
def list_modules():
    auth.require(*auth.ALL_ROLES)
    limit, offset = v.pagination()
    filters = {
        "display_model_id": v.query_str("display_model_id"),
        "cabinet_id": v.query_str("cabinet_id"),
        "replaces_module_id": v.query_str("replaces_module_id"),
        "reserved_service_contract_id": v.query_str("reserved_service_contract_id"),
        "module_state": v.query_enum("module_state", calc.MODULE_STATES),
        "color_bin": v.query_enum("color_bin", calc.COLOR_BINS),
    }
    rows = aggregates.by_created(store.modules.values())
    for field, wanted in filters.items():
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return envelope.paginated(rows, limit, offset, serializers.module)
