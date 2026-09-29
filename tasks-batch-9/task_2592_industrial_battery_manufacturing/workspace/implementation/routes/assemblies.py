"""Battery assemblies: build, two independent verification axes, rework."""
from decimal import Decimal

from flask import Blueprint, g

from authz import PLANT_ADMIN, PRODUCTION_SUPERVISOR, QUALITY_INSPECTOR, endpoint
from errors import ApiError
from helpers import apply_filters, lookup, paginated, unique_or_conflict
from response import object_response
from store import db
from validation import forbid, require
from services.constants import (
    MAX_REWORKS,
    POSTURE_FROZEN,
    TORQUE_TOLERANCE_HIGH,
    TORQUE_TOLERANCE_LOW,
)
from services.lot_service import derive_certification

bp = Blueprint("assemblies", __name__)

ASSEMBLY_READERS = [PLANT_ADMIN, PRODUCTION_SUPERVISOR, QUALITY_INSPECTOR]

CREATE_SPEC = {
    "lot_id": {"type": "id", "required": True},
    "serial_number": {"type": "string", "required": True},
    "module_count": {"type": "int", "required": True, "gte": 1, "lte": 48},
    "case_type": {
        "type": "enum",
        "required": True,
        "values": ["STEEL_TRAY", "POLY_CASE", "MODULAR_RACK"],
    },
    "torque_spec_nm": {"type": "number", "required": True, "gt": 0},
    "ir_min_megaohm": {"type": "number", "required": True, "gt": 0},
}

VERIFY_SPEC = {
    "verification_type": {
        "type": "enum",
        "required": True,
        "values": ["TORQUE", "INSULATION_RESISTANCE"],
    },
    "measured_torque_nm": {"type": "number", "gte": 0},
    "connection_count": {"type": "int", "gte": 0},
    "measured_ir_megaohm": {"type": "number", "gte": 0},
    "test_voltage_v": {"type": "number", "gte": 500},
}

REWORK_SPEC = {"rework_note": {"type": "string", "allow_blank": True}}

ASSEMBLY_FILTERS = {
    "lot_id": "lot_id",
    "torque_status": "torque_status",
    "insulation_status": "insulation_status",
    "certification_status": "certification_status",
}
DEFAULT_ORDER = [("created_at", "asc"), ("id", "asc")]


def _check_verification_discriminator(payload):
    if payload["verification_type"] == "TORQUE":
        require(payload, "measured_torque_nm", "for a TORQUE verification")
        require(payload, "connection_count", "for a TORQUE verification")
        forbid(payload, "measured_ir_megaohm", "for a TORQUE verification")
        forbid(payload, "test_voltage_v", "for a TORQUE verification")
    else:
        require(payload, "measured_ir_megaohm", "for an INSULATION_RESISTANCE verification")
        require(payload, "test_voltage_v", "for an INSULATION_RESISTANCE verification")
        forbid(payload, "measured_torque_nm", "for an INSULATION_RESISTANCE verification")
        forbid(payload, "connection_count", "for an INSULATION_RESISTANCE verification")


def _lot_of(assembly):
    return db.production_lots.get(assembly["lot_id"])


def _guard_lot_not_held(assembly):
    lot = _lot_of(assembly)
    if lot is not None and lot.get("env_hold_status") == "HELD":
        raise ApiError("ERR_LOT_ENV_HELD", "The owning lot is under an environmental hold")


@bp.post("/battery-assemblies")
@endpoint([PRODUCTION_SUPERVISOR], body=CREATE_SPEC)
def create_assembly():
    payload = g.body
    lot = lookup("production_lots", payload["lot_id"])
    unique_or_conflict("battery_assemblies", "serial_number", payload["serial_number"])
    if lot["process_state"] != "ASSEMBLY":
        raise ApiError(
            "ERR_LOT_STATE_INVALID", "Assemblies may only be built from a lot in ASSEMBLY"
        )
    plant = db.plants.get(lot["plant_id"])
    if plant is not None and plant.get("compliance_posture") == POSTURE_FROZEN:
        raise ApiError("ERR_PLANT_FROZEN", "The plant's compliance posture is FROZEN")
    if lot.get("env_hold_status") == "HELD":
        raise ApiError("ERR_LOT_ENV_HELD", "The lot is under an environmental hold")
    record = {
        "lot_id": lot["id"],
        "serial_number": payload["serial_number"],
        "module_count": payload["module_count"],
        "case_type": payload["case_type"],
        "torque_spec_nm": payload["torque_spec_nm"],
        "ir_min_megaohm": payload["ir_min_megaohm"],
        "torque_status": "PENDING",
        "insulation_status": "PENDING",
        "certification_status": "PENDING",
        "measured_torque_nm": None,
        "measured_ir_megaohm": None,
        "rework_count": 0,
    }
    db.insert("battery_assemblies", record)
    return object_response(record, 201)


@bp.get("/battery-assemblies")
@endpoint(ASSEMBLY_READERS, paginated=True)
def list_assemblies():
    rows = apply_filters(db.rows("battery_assemblies"), ASSEMBLY_FILTERS)
    return paginated(rows, DEFAULT_ORDER)


@bp.get("/battery-assemblies/<assembly_id>")
@endpoint(ASSEMBLY_READERS)
def read_assembly(assembly_id):
    return object_response(lookup("battery_assemblies", assembly_id))


@bp.post("/battery-assemblies/<assembly_id>/verifications")
@endpoint(
    [QUALITY_INSPECTOR], body=VERIFY_SPEC, schema_check=_check_verification_discriminator
)
def record_verification(assembly_id):
    payload = g.body
    assembly = lookup("battery_assemblies", assembly_id)
    axis = "torque_status" if payload["verification_type"] == "TORQUE" else "insulation_status"
    if assembly[axis] != "PENDING":
        raise ApiError(
            "ERR_ASSEMBLY_AXIS_ALREADY_RECORDED",
            "This axis already holds a verdict for the current rework generation",
        )
    _guard_lot_not_held(assembly)
    if payload["verification_type"] == "TORQUE":
        expected = 2 * assembly["module_count"]
        if payload["connection_count"] != expected:
            raise ApiError(
                "ERR_CONNECTION_COUNT_MISMATCH",
                "connection_count must equal %d for this assembly" % expected,
            )
        spec = assembly["torque_spec_nm"]
        low = spec * TORQUE_TOLERANCE_LOW
        high = spec * TORQUE_TOLERANCE_HIGH
        reading = payload["measured_torque_nm"]
        assembly["torque_status"] = "PASS" if low <= reading <= high else "FAIL"
        assembly["measured_torque_nm"] = reading
    else:
        reading = payload["measured_ir_megaohm"]
        assembly["insulation_status"] = (
            "PASS" if reading >= assembly["ir_min_megaohm"] else "FAIL"
        )
        assembly["measured_ir_megaohm"] = reading
    derive_certification(assembly)
    db.touch(assembly)
    return object_response(assembly)


@bp.post("/battery-assemblies/<assembly_id>/rework")
@endpoint([PRODUCTION_SUPERVISOR], body=REWORK_SPEC)
def rework_assembly(assembly_id):
    assembly = lookup("battery_assemblies", assembly_id)
    if assembly["certification_status"] not in ("REJECTED", "REVOKED"):
        raise ApiError(
            "ERR_ASSEMBLY_STATE_INVALID",
            "Only a REJECTED or REVOKED assembly may be reworked",
        )
    _guard_lot_not_held(assembly)
    if assembly.get("rework_count", 0) >= MAX_REWORKS:
        raise ApiError(
            "ERR_REWORK_LIMIT_REACHED", "This assembly has already been reworked three times"
        )
    assembly["torque_status"] = "PENDING"
    assembly["insulation_status"] = "PENDING"
    assembly["measured_torque_nm"] = None
    assembly["measured_ir_megaohm"] = None
    assembly["certification_status"] = "PENDING"
    assembly["rework_count"] = assembly.get("rework_count", 0) + 1
    db.touch(assembly)
    return object_response(assembly)
