"""Payload factories — one per write endpoint, input fields only (PRD §4)."""
from .constants import (
    DEFAULT_CORE_BASE_CREDIT_CENTS,
    DEFAULT_CORE_DEPOSIT_CENTS,
    DEFAULT_DYNO_MAX_COOLANT_TEMP_F,
    DEFAULT_DYNO_MIN_HORSEPOWER,
    DEFAULT_DYNO_MIN_OIL_PRESSURE_PSI,
    DEFAULT_LIST_PRICE_CENTS,
    PASSING_DYNO,
)


def create_distributor_payload(**overrides) -> dict:
    defaults = {
        "distributor_code": "D-100",
        "name": "Test Distributor",
        "emissions_requirement": "FEDERAL",
        "credit_limit_cents": 1000000,
        "volume_discount_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def patch_distributor_payload(**fields) -> dict:
    return {k: v for k, v in fields.items() if v is not None}


def create_build_spec_payload(**overrides) -> dict:
    defaults = {
        "engine_family": "SBC-350",
        "application_code": "C1500-1996",
        "emissions_tier": "FEDERAL",
        "list_price_cents": DEFAULT_LIST_PRICE_CENTS,
        "core_deposit_cents": DEFAULT_CORE_DEPOSIT_CENTS,
        "core_base_credit_cents": DEFAULT_CORE_BASE_CREDIT_CENTS,
        "allowed_reuse_grades": ["REUSE_OK", "REWORK"],
        "allowed_interchange_groups": ["CRANK-SBC-3.48", "HEAD-SBC-VORTEC"],
        "dyno_min_horsepower": DEFAULT_DYNO_MIN_HORSEPOWER,
        "dyno_min_oil_pressure_psi": DEFAULT_DYNO_MIN_OIL_PRESSURE_PSI,
        "dyno_max_coolant_temp_f": DEFAULT_DYNO_MAX_COOLANT_TEMP_F,
        "required_op_sequence": ["CRANK_GRIND"],
    }
    defaults.update(overrides)
    return defaults


def create_core_return_payload(distributor_id, build_spec_id,
                               core_deposit_id=None) -> dict:
    payload = {
        "distributor_id": distributor_id,
        "build_spec_id": build_spec_id,
    }
    if core_deposit_id is not None:
        payload["core_deposit_id"] = core_deposit_id
    return payload


def grade_return_payload(grade="GRADE_A", missing_components=None) -> dict:
    return {
        "grade": grade,
        "missing_components": list(missing_components or []),
    }


def respond_grading_payload(action) -> dict:
    return {"action": action}


def create_work_order_payload(core_return_id) -> dict:
    return {"core_return_id": core_return_id}


def advance_work_order_payload(target) -> dict:
    return {"target": target}


def declare_operation_payload(op_type, sequence,
                              expected_work_order_version) -> dict:
    return {
        "op_type": op_type,
        "sequence": sequence,
        "expected_work_order_version": expected_work_order_version,
    }


def perform_operation_payload(station_code, scheduled_start, scheduled_end,
                              result="PASS") -> dict:
    return {
        "station_code": station_code,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "result": result,
    }


def salvage_component_payload(part_type, interchange_group) -> dict:
    return {
        "part_type": part_type,
        "interchange_group": interchange_group,
    }


def inspect_component_payload(reuse_grade, quarantine) -> dict:
    return {
        "reuse_grade": reuse_grade,
        "quarantine": quarantine,
    }


def consume_component_payload(component_id) -> dict:
    return {"component_id": component_id}


def record_dyno_test_payload(dyno_cell_code, started_at, ended_at,
                             horsepower=None, oil_pressure_psi=None,
                             coolant_temp_f=None) -> dict:
    return {
        "dyno_cell_code": dyno_cell_code,
        "started_at": started_at,
        "ended_at": ended_at,
        "horsepower": (PASSING_DYNO["horsepower"]
                       if horsepower is None else horsepower),
        "oil_pressure_psi": (PASSING_DYNO["oil_pressure_psi"]
                             if oil_pressure_psi is None else oil_pressure_psi),
        "coolant_temp_f": (PASSING_DYNO["coolant_temp_f"]
                           if coolant_temp_f is None else coolant_temp_f),
    }


def sell_engine_payload(build_spec_id, expected_distributor_version) -> dict:
    return {
        "build_spec_id": build_spec_id,
        "expected_distributor_version": expected_distributor_version,
    }


def create_warranty_claim_payload(reman_engine_id, distributor_id,
                                  failure_description) -> dict:
    return {
        "reman_engine_id": reman_engine_id,
        "distributor_id": distributor_id,
        "failure_description": failure_description,
    }


def teardown_claim_payload(teardown_findings) -> dict:
    return {"teardown_findings": teardown_findings}


def adjudicate_claim_payload(outcome, teardown_fee_cents) -> dict:
    return {
        "outcome": outcome,
        "teardown_fee_cents": teardown_fee_cents,
    }
