"""Payload factories — one per created entity, request fields only.

Each factory returns the PRD's request body with sensible defaults and accepts
``**overrides`` so a test can control exactly the field under examination.
"""
from .constants import CLOCK_EPOCH, REQUIRED_WAIVER_VERSION, TEST_DEFAULTS


def shell_component_criteria(
    replace_threshold=TEST_DEFAULTS["SHELL_REPLACE_THRESHOLD"],
    fail_threshold=TEST_DEFAULTS["SHELL_FAIL_THRESHOLD"],
    metric_direction="HIGHER_IS_WORSE",
    code="SHELL",
    metric="crack_length_mm",
    unit="mm",
) -> dict:
    """One entry of a model's ``component_criteria`` array."""
    return {
        "code": code,
        "metric": metric,
        "metric_direction": metric_direction,
        "replace_threshold": replace_threshold,
        "fail_threshold": fail_threshold,
        "unit": unit,
    }


def create_model_spec_payload(**overrides) -> dict:
    payload = {
        "manufacturer": TEST_DEFAULTS["MANUFACTURER"],
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
        "standard_code": TEST_DEFAULTS["STANDARD_CODE"],
        "shell_material": "POLYCARBONATE",
        "max_service_life_years": TEST_DEFAULTS["MAX_SERVICE_LIFE_YEARS"],
        "warranty_years": TEST_DEFAULTS["WARRANTY_YEARS"],
        "record_retention_years": TEST_DEFAULTS["RECORD_RETENTION_YEARS"],
        "pass_si_max": TEST_DEFAULTS["PASS_SI_MAX"],
        "repair_si_max": TEST_DEFAULTS["REPAIR_SI_MAX"],
        "max_retest_count": TEST_DEFAULTS["MAX_RETEST_COUNT"],
        "reconditionable": True,
        "required_component_codes": ["SHELL"],
        "component_criteria": [shell_component_criteria()],
    }
    payload.update(overrides)
    return payload


def create_approved_part_payload(model_spec_id, **overrides) -> dict:
    payload = {
        "model_spec_id": model_spec_id,
        "part_number": "PN-SHELL-1",
        "component_code": "SHELL",
        "oem_approved": True,
        "unit_price_cents": TEST_DEFAULTS["PART_UNIT_PRICE_CENTS"],
        "received_qty": 4,
    }
    payload.update(overrides)
    return payload


def create_test_bench_payload(**overrides) -> dict:
    payload = {
        "bench_code": "RIG-1",
        "test_type": "DROP_IMPACT",
        "daily_session_quota": TEST_DEFAULTS["BENCH_DAILY_SESSION_QUOTA"],
        "cooldown_minutes": 45,
    }
    payload.update(overrides)
    return payload


def calibrate_test_bench_payload(**overrides) -> dict:
    payload = {"calibration_valid_until": TEST_DEFAULTS["BENCH_CALIBRATION_VALID_UNTIL"]}
    payload.update(overrides)
    return payload


def create_loaner_unit_payload(model_spec_id, **overrides) -> dict:
    payload = {
        "model_spec_id": model_spec_id,
        "asset_tag": "LN-001",
        "condition_grade": "A",
        "certification_valid_until": TEST_DEFAULTS["BENCH_CALIBRATION_VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload


def create_customer_account_payload(**overrides) -> dict:
    payload = {
        "org_name": "Northside High",
        "org_type": "SCHOOL",
        "sport": "FOOTBALL",
        "contact_email": "ad@northside.example",
    }
    payload.update(overrides)
    return payload


def liability_acknowledgment_payload(**overrides) -> dict:
    payload = {"waiver_version": REQUIRED_WAIVER_VERSION, "signer_name": "R. Vega"}
    payload.update(overrides)
    return payload


def billing_hold_payload(hold=True, **overrides) -> dict:
    payload = {"hold": hold, "reason": "unpaid invoice 8841"}
    payload.update(overrides)
    return payload


def create_intake_shipment_payload(customer_account_id, **overrides) -> dict:
    payload = {
        "customer_account_id": customer_account_id,
        "sport": "FOOTBALL",
        "service_tier": "STANDARD",
        "declared_unit_count": 1,
        "season_start_date": TEST_DEFAULTS["SEASON_START_DATE"],
        "season_end_date": TEST_DEFAULTS["SEASON_END_DATE"],
    }
    payload.update(overrides)
    return payload


def count_shipment_payload(counted_unit_count, **overrides) -> dict:
    payload = {"counted_unit_count": counted_unit_count}
    payload.update(overrides)
    return payload


def accept_shipment_payload(discrepancy_resolution="MATCHED", **overrides) -> dict:
    payload = {"discrepancy_resolution": discrepancy_resolution}
    payload.update(overrides)
    return payload


def create_equipment_unit_payload(intake_shipment_id, serial_number="SN-0001", **overrides) -> dict:
    payload = {
        "intake_shipment_id": intake_shipment_id,
        "serial_number": serial_number,
        "declared_model_code": TEST_DEFAULTS["MODEL_CODE"],
    }
    payload.update(overrides)
    return payload


def identify_unit_payload(model_spec_id, **overrides) -> dict:
    payload = {
        "model_spec_id": model_spec_id,
        "manufacture_date": TEST_DEFAULTS["MANUFACTURE_DATE"],
        "age_basis": "MANUFACTURE_DATE",
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(component_code="SHELL", **overrides) -> dict:
    payload = {
        "component_code": component_code,
        "measurement_value": TEST_DEFAULTS["SHELL_MEASUREMENT_PASS"],
        "measurement_unit": "mm",
        "note": "no crown cracking",
    }
    payload.update(overrides)
    return payload


def condemn_unit_payload(condemn_reason="NOT_RECONDITIONABLE", **overrides) -> dict:
    payload = {"condemn_reason": condemn_reason}
    payload.update(overrides)
    return payload


def release_unit_payload(**overrides) -> dict:
    payload = {"released_to": "Northside High athletics"}
    payload.update(overrides)
    return payload


def create_shell_test_payload(equipment_unit_id, test_bench_id, **overrides) -> dict:
    payload = {
        "equipment_unit_id": equipment_unit_id,
        "test_bench_id": test_bench_id,
        "window_start": "2026-08-01T09:00:00Z",
        "window_end": "2026-08-01T10:00:00Z",
        "conditioning": "AMBIENT",
    }
    payload.update(overrides)
    return payload


def record_impacts_payload(front=300, side=300, crown=300, **overrides) -> dict:
    payload = {"peak_g_front": front, "peak_g_side": side, "peak_g_crown": crown}
    payload.update(overrides)
    return payload


def determine_payload(determination="PASS", **overrides) -> dict:
    payload = {"determination": determination}
    payload.update(overrides)
    return payload


def create_repair_order_payload(equipment_unit_id, expected_equipment_unit_version, **overrides) -> dict:
    payload = {
        "equipment_unit_id": equipment_unit_id,
        "expected_equipment_unit_version": expected_equipment_unit_version,
    }
    payload.update(overrides)
    return payload


def part_line_payload(approved_part_id, quantity=1, **overrides) -> dict:
    payload = {
        "approved_part_id": approved_part_id,
        "quantity": quantity,
        "lot_code": "LOT-A",
        "oem_cert_ref": "OEM-A-1",
    }
    payload.update(overrides)
    return payload


def verify_repair_payload(outcome="PASSED", **overrides) -> dict:
    payload = {"outcome": outcome, "note": "rework inspected"}
    payload.update(overrides)
    return payload


def cancel_repair_payload(**overrides) -> dict:
    payload = {"cancel_reason": "customer declined the rework quote"}
    payload.update(overrides)
    return payload


def create_certification_label_payload(equipment_unit_id, expected_equipment_unit_version, **overrides) -> dict:
    payload = {
        "equipment_unit_id": equipment_unit_id,
        "expected_equipment_unit_version": expected_equipment_unit_version,
    }
    payload.update(overrides)
    return payload


def void_label_payload(**overrides) -> dict:
    payload = {"void_reason": "traceability code misprinted on the decal"}
    payload.update(overrides)
    return payload


def witness_destruction_payload(**overrides) -> dict:
    payload = {"method": "SHELL_CRUSH", "witness_name": "M. Okafor"}
    payload.update(overrides)
    return payload


def verify_destruction_payload(**overrides) -> dict:
    payload = {"verification_ref": "DEST-VER-1"}
    payload.update(overrides)
    return payload


def create_loaner_assignment_payload(customer_account_id, requested_model_spec_id, **overrides) -> dict:
    payload = {
        "customer_account_id": customer_account_id,
        "requested_model_spec_id": requested_model_spec_id,
        "window_start": "2026-08-05T00:00:00Z",
        "window_end": "2026-08-12T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def return_loaner_payload(**overrides) -> dict:
    payload = {"return_condition_note": "returned clean, no damage"}
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc=CLOCK_EPOCH, **overrides) -> dict:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
