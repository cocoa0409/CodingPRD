"""LifeSupportSystem, WaterQualityReading and redundancy tests."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("lss", __name__)

SYSTEM_TYPES = ("RECIRCULATING_MARINE", "FLOW_THROUGH", "CLOSED_FRESHWATER")
HABITATS = ("COLD_MARINE", "TROPICAL_MARINE", "FRESHWATER", "TOUCH_POOL")
REDUNDANCY_CLASSES = ("N", "N_PLUS_1", "TWO_N")
ALARM_STATES = ("NORMAL", "WARNING", "CRITICAL", "OFFLINE")
SEVERITIES = ("NORMAL", "WARNING", "CRITICAL")
POSTURES = ("OPEN", "RESTRICTED", "CLOSED")

SYSTEM_COMPUTED = (
    "last_redundancy_test_at", "last_redundancy_test_result", "redundancy_overdue",
    "alarm_state", "consecutive_normal_readings", "consecutive_breach_readings",
    "water_quality_index",
)
READING_COMPUTED = (
    "life_support_system_id", "severity", "breach_parameters", "water_quality_index_snapshot",
)


@bp.route("/aquarium/life-support-systems", methods=["POST"])
def create_system():
    M.authenticate({M.DIRECTOR})
    body = M.json_body()
    V.reject_computed(body, SYSTEM_COMPUTED)
    system_code = V.as_str(body, "system_code", required=True, min_len=1, max_len=32)
    system_type = V.as_enum(body, "system_type", SYSTEM_TYPES, required=True)
    design_habitat = V.as_enum(body, "design_habitat", HABITATS, required=True)
    redundancy_class = V.as_enum(body, "redundancy_class", REDUNDANCY_CLASSES, required=True)
    # PRD §3.1 lists `redundancy_test_interval_days` among the registration
    # inputs and states no default, so it is required.
    interval = V.as_int(
        body, "redundancy_test_interval_days", required=True, minimum=7, maximum=365
    )

    for row in db.db.life_support_systems.values():
        if row["system_code"] == system_code:
            raise ApiError("ERR_DUPLICATE_CODE")

    row = db.new_row()
    row.update({
        "system_code": system_code,
        "system_type": system_type,
        "design_habitat": design_habitat,
        "redundancy_class": redundancy_class,
        "redundancy_test_interval_days": interval,
        "last_redundancy_test_at": None,
        "last_redundancy_test_result": None,
        "alarm_state": "NORMAL",
        "consecutive_normal_readings": 0,
        "consecutive_breach_readings": 0,
        "water_quality_index": Decimal("100.00"),
    })
    db.insert("life_support_systems", row)
    return response.object_response(S.life_support_system(row), 201)


@bp.route("/aquarium/life-support-systems", methods=["GET"])
def list_systems():
    M.authenticate(M.NON_LIAISON)
    alarm_state = M.enum_param("alarm_state", ALARM_STATES)
    design_habitat = M.enum_param("design_habitat", HABITATS)
    limit, offset = M.pagination()

    def keep(row):
        if alarm_state is not None and row["alarm_state"] != alarm_state:
            return False
        if design_habitat is not None and row["design_habitat"] != design_habitat:
            return False
        return True

    rows = db.ordered("life_support_systems", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.life_support_system(r) for r in page], limit, offset, total)


@bp.route("/aquarium/life-support-systems/<row_id>", methods=["GET"])
def get_system(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("life_support_systems", row_id)
    return response.object_response(S.life_support_system(row))


@bp.route("/aquarium/life-support-systems/<row_id>/water-quality-readings", methods=["POST"])
def create_reading(row_id):
    M.authenticate({M.AQUARIST})
    system = M.fetch("life_support_systems", row_id)
    body = M.json_body()
    V.reject_computed(body, READING_COMPUTED)
    taken_at = V.as_dt(body, "taken_at", required=True)
    values = {
        "temperature_c": V.as_dec(body, "temperature_c", required=True),
        "salinity_ppt": V.as_dec(body, "salinity_ppt", required=True, minimum=0),
        "ph": V.as_dec(body, "ph", required=True, minimum=0, maximum=14),
        "dissolved_oxygen_mg_l": V.as_dec(body, "dissolved_oxygen_mg_l", required=True, minimum=0),
        "ammonia_mg_l": V.as_dec(body, "ammonia_mg_l", required=True, minimum=0),
        "nitrite_mg_l": V.as_dec(body, "nitrite_mg_l", required=True, minimum=0),
    }
    if taken_at > db.db.clock:
        raise ApiError("ERR_TIMESTAMP_IN_FUTURE")

    snapshot, severity, breaches = calc.water_quality(system["design_habitat"], values)
    row = db.new_row(with_common=False)
    row.update({
        "life_support_system_id": system["id"],
        "taken_at": taken_at,
        "severity": severity,
        "breach_parameters": breaches,
        "water_quality_index_snapshot": snapshot,
    })
    row.update(values)
    db.insert("water_quality_readings", row)
    engine.apply_reading(system, row)
    return response.object_response(S.water_quality_reading(row), 201)


@bp.route("/aquarium/life-support-systems/<row_id>/water-quality-readings", methods=["GET"])
def list_readings(row_id):
    M.authenticate(M.NON_LIAISON)
    system = M.fetch("life_support_systems", row_id)
    severity = M.enum_param("severity", SEVERITIES)
    limit, offset = M.pagination()

    def keep(row):
        if row["life_support_system_id"] != system["id"]:
            return False
        if severity is not None and row["severity"] != severity:
            return False
        return True

    rows = db.ordered("water_quality_readings", keep, reverse=True)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.water_quality_reading(r) for r in page], limit, offset, total)


@bp.route("/aquarium/life-support-systems/<row_id>/redundancy-tests", methods=["POST"])
def create_redundancy_test(row_id):
    M.authenticate({M.AQUARIST})
    system = M.fetch("life_support_systems", row_id)
    body = M.json_body()
    V.reject_computed(body, SYSTEM_COMPUTED)
    performed_at = V.as_dt(body, "performed_at", required=True)
    result = V.as_enum(body, "result", ("PASS", "FAIL"), required=True)
    V.as_str(body, "note")
    if performed_at > db.db.clock:
        raise ApiError("ERR_TIMESTAMP_IN_FUTURE")
    engine.apply_redundancy_test(system, performed_at, result)
    return response.object_response(S.life_support_system(system), 201)


@bp.route("/aquarium/life-support-systems/<row_id>/exhibits", methods=["GET"])
def list_system_exhibits(row_id):
    M.authenticate(M.NON_LIAISON)
    system = M.fetch("life_support_systems", row_id)
    posture = M.enum_param("posture", POSTURES)
    limit, offset = M.pagination()

    def keep(row):
        if row["life_support_system_id"] != system["id"]:
            return False
        if posture is not None and row["posture"] != posture:
            return False
        return True

    rows = db.ordered("exhibits", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.exhibit(r) for r in page], limit, offset, total)
