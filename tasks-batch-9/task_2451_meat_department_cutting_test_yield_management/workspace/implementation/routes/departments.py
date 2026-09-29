"""Department provisioning and retrieval (PRD §3.1)."""

from decimal import Decimal

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import rhu
from db import db, make
from errors import ApiError
from response import list_response, object_response

bp = Blueprint("departments", __name__)

DEFAULTS = {
    "target_margin_pct": Decimal("0.32"),
    "shelf_life_days_ground": 2,
    "shelf_life_days_whole_muscle": 5,
    "shelf_life_days_vac_packed": 14,
    "max_safe_case_temp_c": Decimal("4.4"),
    "critical_case_temp_c": Decimal("7.0"),
    "pickup_slot_capacity": 2,
    "grind_sanitation_buffer_min": 30,
    "markdown_floor_pct": Decimal("0.10"),
    "shrink_tolerance_pct": Decimal("0.015"),
    "deposit_rate": Decimal("0.25"),
}


@bp.route("/meat-ops/departments", methods=["POST"])
def create_department():
    mw.authenticate((mw.STORE_ADMIN,))
    payload = v.body()

    name = v.field_str(payload, "name", required=True, min_len=1, max_len=120)
    store_code = v.field_str(payload, "store_code", required=True,
                             min_len=2, max_len=16)
    if store_code != store_code.upper():
        v.bad("'store_code' must be uppercase")

    target_margin_pct = v.field_num(payload, "target_margin_pct", minimum=0,
                                    maximum=Decimal("0.60"),
                                    default=DEFAULTS["target_margin_pct"], places=4)
    ground = v.field_int(payload, "shelf_life_days_ground", minimum=1, maximum=10,
                         default=DEFAULTS["shelf_life_days_ground"])
    whole = v.field_int(payload, "shelf_life_days_whole_muscle", minimum=1, maximum=20,
                        default=DEFAULTS["shelf_life_days_whole_muscle"])
    vac = v.field_int(payload, "shelf_life_days_vac_packed", minimum=1, maximum=45,
                      default=DEFAULTS["shelf_life_days_vac_packed"])
    max_safe = v.field_num(payload, "max_safe_case_temp_c", minimum=Decimal("0.0"),
                           default=DEFAULTS["max_safe_case_temp_c"], places=1)
    critical = v.field_num(payload, "critical_case_temp_c",
                           default=DEFAULTS["critical_case_temp_c"], places=1)
    if not (max_safe < critical):
        v.bad("'max_safe_case_temp_c' must be strictly below 'critical_case_temp_c'")

    pickup_slot_capacity = v.field_int(payload, "pickup_slot_capacity", minimum=1,
                                       maximum=10,
                                       default=DEFAULTS["pickup_slot_capacity"])
    buffer_min = v.field_int(payload, "grind_sanitation_buffer_min", minimum=0,
                             maximum=240,
                             default=DEFAULTS["grind_sanitation_buffer_min"])
    markdown_floor_pct = v.field_num(payload, "markdown_floor_pct", minimum=0,
                                     maximum=Decimal("0.50"),
                                     default=DEFAULTS["markdown_floor_pct"], places=4)
    shrink_tolerance_pct = v.field_num(payload, "shrink_tolerance_pct", gt=0,
                                       maximum=Decimal("0.25"),
                                       default=DEFAULTS["shrink_tolerance_pct"],
                                       places=4)
    deposit_rate = v.field_num(payload, "deposit_rate", minimum=0,
                               maximum=Decimal("1.0"),
                               default=DEFAULTS["deposit_rate"], places=4)

    for existing in db.departments.values():
        if existing["store_code"] == store_code:
            raise ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                           "store_code is already in use")

    department = make("Department", {
        "name": name,
        "store_code": store_code,
        "target_margin_pct": rhu(target_margin_pct, 4),
        "shelf_life_days_ground": ground,
        "shelf_life_days_whole_muscle": whole,
        "shelf_life_days_vac_packed": vac,
        "max_safe_case_temp_c": rhu(max_safe, 1),
        "critical_case_temp_c": rhu(critical, 1),
        "pickup_slot_capacity": pickup_slot_capacity,
        "grind_sanitation_buffer_min": buffer_min,
        "markdown_floor_pct": rhu(markdown_floor_pct, 4),
        "shrink_tolerance_pct": rhu(shrink_tolerance_pct, 4),
        "deposit_rate": rhu(deposit_rate, 4),
        "case_posture": "SALES_OPEN",
        "open_case_failure_count": 0,
        "contained_case_failure_count": 0,
        "consecutive_out_of_spec_readings": 0,
    })
    db.departments[department["id"]] = department
    return object_response(department, 201)


@bp.route("/meat-ops/departments/<department_id>", methods=["GET"])
def get_department(department_id):
    mw.authenticate(mw.ALL_ROLES)
    department = v.resolve("department", department_id)
    return object_response(department)
