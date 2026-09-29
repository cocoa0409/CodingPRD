"""Request-payload builders.

Each builder returns a fresh dict carrying the PRD-required fields with a
sensible, PRD-legal default, and accepts keyword overrides so a test can pin
exactly the field it cares about. Passing ``None`` for an override removes the
key entirely, which is how omitted-optional and missing-required cases are
expressed.
"""

from typing import Any, Dict

from .constants import (
    BODY_DUMP_12FT,
    BODY_SERVICE_11FT,
    CM_F550,
    CUSTOMER_METRO,
    EQ_CRANE_6000,
    WORK_BAY_1,
    vin_f550,
)

_REMOVE = "__remove__"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _REMOVE:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


REMOVE = _REMOVE


# --------------------------------------------------------------------------
# Reference catalog
# --------------------------------------------------------------------------
def chassis_model_payload(**overrides) -> Dict[str, Any]:
    return _merge(CM_F550, overrides)


def body_spec_payload(**overrides) -> Dict[str, Any]:
    return _merge(BODY_SERVICE_11FT, overrides)


def dump_body_spec_payload(**overrides) -> Dict[str, Any]:
    return _merge(BODY_DUMP_12FT, overrides)


def equipment_spec_payload(**overrides) -> Dict[str, Any]:
    return _merge(EQ_CRANE_6000, overrides)


def work_bay_payload(**overrides) -> Dict[str, Any]:
    return _merge(WORK_BAY_1, overrides)


def customer_payload(**overrides) -> Dict[str, Any]:
    return _merge(CUSTOMER_METRO, overrides)


# --------------------------------------------------------------------------
# Build configuration and order
# --------------------------------------------------------------------------
def build_configuration_payload(
    chassis_model_id: str, body_spec_id: str, **overrides
) -> Dict[str, Any]:
    base = {
        "config_code": "CFG-SERVICE-A",
        "chassis_model_id": chassis_model_id,
        "body_spec_id": body_spec_id,
        "standardization_tier": "CUSTOM",
        "standard_equipment_spec_ids": [],
    }
    return _merge(base, overrides)


def upfit_order_payload(build_configuration_id: str, **overrides) -> Dict[str, Any]:
    base = {
        "order_number": "UO-5001",
        "build_configuration_id": build_configuration_id,
        "order_type": "POOL_STOCK",
        "body_mount_offset_from_front_axle_in": 120,
    }
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Chassis custody
# --------------------------------------------------------------------------
def chassis_payload(chassis_model_id: str, **overrides) -> Dict[str, Any]:
    base = {
        "vin": vin_f550(1),
        "chassis_model_id": chassis_model_id,
        "availability_date": "2026-08-05",
    }
    return _merge(base, overrides)


def inspection_payload(front_lb: int, rear_lb: int, **overrides) -> Dict[str, Any]:
    base = {
        "measured_front_axle_weight_lb": front_lb,
        "measured_rear_axle_weight_lb": rear_lb,
    }
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Equipment and electrical
# --------------------------------------------------------------------------
def equipment_installation_payload(
    upfit_order_id: str, equipment_spec_id: str, **overrides
) -> Dict[str, Any]:
    base = {
        "upfit_order_id": upfit_order_id,
        "equipment_spec_id": equipment_spec_id,
        "mount_cg_from_front_axle_in": 208,
        "hydraulic_circuit": "PRIMARY",
    }
    return _merge(base, overrides)


def electrical_interface_payload(upfit_order_id: str, **overrides) -> Dict[str, Any]:
    base = {
        "upfit_order_id": upfit_order_id,
        "interface_method": "BODY_BUILDER_MODULE",
        "circuit_amp_draw": 4,
        "signal_source": "BODY_CONTROLLER",
    }
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Scheduling, certification, labelling, warranty
# --------------------------------------------------------------------------
def build_slot_payload(
    upfit_order_id: str, work_bay_id: str, start_date: str, end_date: str, **overrides
) -> Dict[str, Any]:
    base = {
        "upfit_order_id": upfit_order_id,
        "work_bay_id": work_bay_id,
        "slot_type": "BODY_MOUNT",
        "start_date": start_date,
        "end_date": end_date,
    }
    return _merge(base, overrides)


def weight_certification_payload(
    upfit_order_id: str, basis: str, expected_upfit_order_version: int, **overrides
) -> Dict[str, Any]:
    base = {
        "upfit_order_id": upfit_order_id,
        "basis": basis,
        "expected_upfit_order_version": expected_upfit_order_version,
    }
    return _merge(base, overrides)


def compliance_label_payload(
    upfit_order_id: str, weight_certification_id: str, **overrides
) -> Dict[str, Any]:
    base = {
        "upfit_order_id": upfit_order_id,
        "weight_certification_id": weight_certification_id,
    }
    return _merge(base, overrides)


def warranty_claim_payload(
    upfit_order_id: str, failure_system: str, claim_cost_cents: int, **overrides
) -> Dict[str, Any]:
    base = {
        "upfit_order_id": upfit_order_id,
        "claim_number": "WC-5001",
        "failure_system": failure_system,
        "claim_cost_cents": claim_cost_cents,
    }
    return _merge(base, overrides)


def allocate_chassis_payload(chassis_id: str, expected_chassis_version: int) -> Dict[str, Any]:
    return {
        "chassis_id": chassis_id,
        "expected_chassis_version": expected_chassis_version,
    }
