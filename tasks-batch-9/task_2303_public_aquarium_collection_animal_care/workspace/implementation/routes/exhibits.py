"""Exhibit registration, editing and reads."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("exhibits", __name__)

HABITATS = ("COLD_MARINE", "TROPICAL_MARINE", "FRESHWATER", "TOUCH_POOL")
POSTURES = ("OPEN", "RESTRICTED", "CLOSED")
SESSION_STATUSES = ("SCHEDULED", "ACTIVE", "COMPLETED", "SUSPENDED", "CANCELLED")
PROGRAM_TYPES = ("TOUCH_POOL_CONTACT", "FEEDING_ENCOUNTER", "DIVE_ENCOUNTER")

EXHIBIT_COMPUTED = (
    "occupied_bioload_units", "bioload_utilization_pct", "posture",
    "last_posture_reason", "suspended_session_count",
)


@bp.route("/aquarium/exhibits", methods=["POST"])
def create_exhibit():
    M.authenticate({M.CURATOR})
    body = M.json_body()
    system = M.fetch_body_fk(body, "life_support_system_id", "life_support_systems")

    V.reject_computed(body, EXHIBIT_COMPUTED)
    exhibit_code = V.as_str(body, "exhibit_code", required=True)
    name = V.as_str(body, "name", required=True)
    habitat_type = V.as_enum(body, "habitat_type", HABITATS, required=True)
    V.as_id(body, "life_support_system_id", required=True)
    display_volume = V.as_dec(body, "display_volume_liters", required=True, exclusive_minimum=0)
    capacity = V.as_dec(body, "bioload_capacity_units", required=True, exclusive_minimum=0)
    program_enabled = V.as_bool(body, "interaction_program_enabled", default=False)

    if habitat_type != system["design_habitat"]:
        raise ApiError("ERR_HABITAT_MISMATCH")
    for row in db.db.exhibits.values():
        if row["exhibit_code"] == exhibit_code:
            raise ApiError("ERR_DUPLICATE_CODE")

    posture, reason = calc.exhibit_posture(
        system, Decimal("0.00"), engine.redundancy_overdue(system))
    row = db.new_row()
    row.update({
        "exhibit_code": exhibit_code,
        "name": name,
        "habitat_type": habitat_type,
        "life_support_system_id": system["id"],
        "display_volume_liters": display_volume,
        "bioload_capacity_units": capacity,
        "occupied_bioload_units": Decimal("0.00"),
        "bioload_utilization_pct": Decimal("0.00"),
        "posture": posture,
        "last_posture_reason": reason,
        "interaction_program_enabled": program_enabled,
        "suspended_session_count": 0,
    })
    db.insert("exhibits", row)
    return response.object_response(S.exhibit(row), 201)


@bp.route("/aquarium/exhibits", methods=["GET"])
def list_exhibits():
    M.authenticate(M.NON_LIAISON)
    system_id = M.str_param("life_support_system_id")
    posture = M.enum_param("posture", POSTURES)
    limit, offset = M.pagination()

    def keep(row):
        if system_id is not None and row["life_support_system_id"] != system_id:
            return False
        if posture is not None and row["posture"] != posture:
            return False
        return True

    rows = db.ordered("exhibits", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.exhibit(r) for r in page], limit, offset, total)


@bp.route("/aquarium/exhibits/<row_id>", methods=["GET"])
def get_exhibit(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("exhibits", row_id)
    return response.object_response(S.exhibit(row))


@bp.route("/aquarium/exhibits/<row_id>", methods=["PATCH"])
def patch_exhibit(row_id):
    M.authenticate({M.DIRECTOR})
    exhibit = M.fetch("exhibits", row_id)
    body = M.json_body()
    system = None
    if "life_support_system_id" in body and body["life_support_system_id"] is not None:
        system = M.fetch_body_fk(body, "life_support_system_id", "life_support_systems")

    V.reject_computed(body, EXHIBIT_COMPUTED)
    expected_version = V.as_int(body, "expected_exhibit_version", required=True, minimum=0)
    capacity = V.as_dec(body, "bioload_capacity_units", exclusive_minimum=0)
    program_enabled = V.as_bool(body, "interaction_program_enabled")
    name = V.as_str(body, "name")
    if "life_support_system_id" in body and body["life_support_system_id"] is not None:
        V.as_id(body, "life_support_system_id")

    if expected_version != exhibit["version"]:
        raise ApiError("ERR_STALE_EXHIBIT_VERSION")

    if name is not None:
        exhibit["name"] = name
    if capacity is not None:
        exhibit["bioload_capacity_units"] = capacity
    if system is not None:
        exhibit["life_support_system_id"] = system["id"]
    if program_enabled is not None:
        if program_enabled and not exhibit["interaction_program_enabled"]:
            exhibit["suspended_session_count"] = 0
        exhibit["interaction_program_enabled"] = program_enabled

    engine.recompute_exhibit(exhibit, force=True)
    return response.object_response(S.exhibit(exhibit))


@bp.route("/aquarium/exhibits/<row_id>/interaction-sessions", methods=["GET"])
def list_exhibit_sessions(row_id):
    M.authenticate(M.NON_LIAISON)
    exhibit = M.fetch("exhibits", row_id)
    status = M.enum_param("status", SESSION_STATUSES)
    program_type = M.enum_param("program_type", PROGRAM_TYPES)
    limit, offset = M.pagination()

    def keep(row):
        if row["exhibit_id"] != exhibit["id"]:
            return False
        if status is not None and row["status"] != status:
            return False
        if program_type is not None and row["program_type"] != program_type:
            return False
        return True

    rows = db.ordered("interaction_sessions", keep)
    page, total = M.paginate(rows, limit, offset)
    return response.list_response([S.interaction_session(r) for r in page], limit, offset, total)
