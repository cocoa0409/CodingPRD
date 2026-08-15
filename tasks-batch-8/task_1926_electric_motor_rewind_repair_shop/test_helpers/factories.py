"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import CANONICAL_SHOP


def create_shop_payload(**overrides) -> dict:
    payload = dict(CANONICAL_SHOP)
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    defaults = {"company_name": "C"}
    defaults.update(overrides)
    return defaults


def create_motor_payload(owner_customer_id, serial_number, **overrides) -> dict:
    defaults = {
        "owner_customer_id": owner_customer_id,
        "serial_number": serial_number,
        "rated_kw": 30,
        "frame_mm": 200,
        "voltage_v": 460,
        "manufacture_year": 2020,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id, motor_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "motor_id": motor_id,
        "priority": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_incoming_test_payload(**overrides) -> dict:
    defaults = {"kind": "INCOMING", "insulation_megohms": 500}
    defaults.update(overrides)
    return defaults


def create_core_loss_test_payload(measured_watts, **overrides) -> dict:
    defaults = {"kind": "CORE_LOSS", "measured_watts": measured_watts}
    defaults.update(overrides)
    return defaults


def create_final_test_payload(vibration_mm_s=2.0, **overrides) -> dict:
    defaults = {
        "kind": "FINAL",
        "vibration_mm_s": vibration_mm_s,
        "insulation_megohms": 900,
    }
    defaults.update(overrides)
    return defaults


def create_diagnosis_payload(**overrides) -> dict:
    defaults = {
        "failure_diagnosis": "winding short",
        "rewind_hours": 5,
        "materials_cents": 10000,
        "replacement_cost_cents": 999999,
    }
    defaults.update(overrides)
    return defaults


def create_quote_issue_payload(expected_work_order_version, **overrides) -> dict:
    defaults = {"expected_work_order_version": expected_work_order_version}
    defaults.update(overrides)
    return defaults


def create_coil_data_payload(**overrides) -> dict:
    defaults = {
        "wire_gauge_awg": "14",
        "turns_per_coil": 22,
        "coils_per_phase": 6,
        "connection": "WYE",
        "winding_resistance_ohms": 0.42,
    }
    defaults.update(overrides)
    return defaults


def create_deliver_payload(expected_work_order_version, **overrides) -> dict:
    defaults = {"expected_work_order_version": expected_work_order_version}
    defaults.update(overrides)
    return defaults


def create_payment_payload(payment_cents, **overrides) -> dict:
    defaults = {"payment_cents": payment_cents}
    defaults.update(overrides)
    return defaults


def create_pool_contract_payload(customer_id, slot_count=2, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "slot_count": slot_count}
    defaults.update(overrides)
    return defaults


def create_loan_payload(work_order_id, spare_motor_id, **overrides) -> dict:
    defaults = {"work_order_id": work_order_id, "spare_motor_id": spare_motor_id}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(failure_mode="WINDING_SHORT", **overrides) -> dict:
    defaults = {"failure_mode": failure_mode}
    defaults.update(overrides)
    return defaults


def create_claim_approval_payload(remedy="PRORATED_CREDIT", **overrides) -> dict:
    defaults = {"remedy": remedy}
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
