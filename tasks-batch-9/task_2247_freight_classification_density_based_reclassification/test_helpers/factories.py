"""Payload factories -- one per resource, carrying only client-supplied fields."""

from .constants import STANDARD_DENSITY_BREAKS, TEST_DEFAULTS


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_terminal_payload(**overrides) -> dict:
    payload = {
        "code": TEST_DEFAULTS["TERMINAL_CODE"],
        "name": TEST_DEFAULTS["TERMINAL_NAME"],
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "account_code": TEST_DEFAULTS["ACCOUNT_CODE"],
        "name": TEST_DEFAULTS["CUSTOMER_NAME"],
    }
    payload.update(overrides)
    return payload


def posture_payload(billing_posture: str, expected_customer_version: int) -> dict:
    return {
        "billing_posture": billing_posture,
        "expected_customer_version": expected_customer_version,
    }


def create_tariff_version_payload(**overrides) -> dict:
    payload = {
        "code": TEST_DEFAULTS["TARIFF_CODE"],
        "effective_at": TEST_DEFAULTS["TARIFF_EFFECTIVE_AT"],
        "density_breaks": [dict(row) for row in STANDARD_DENSITY_BREAKS],
    }
    payload.update(overrides)
    return payload


def create_commodity_profile_payload(tariff_version_id: str, **overrides) -> dict:
    payload = {
        "tariff_version_id": tariff_version_id,
        "nmfc_item": TEST_DEFAULTS["NMFC_ITEM"],
        "description": TEST_DEFAULTS["COMMODITY_DESCRIPTION"],
        "classification_basis": "DENSITY_BASED",
    }
    payload.update(overrides)
    return payload


def create_rate_program_payload(customer_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "program_type": "CLASS_BASED",
        "base_rate_per_cwt_cents": TEST_DEFAULTS["BASE_RATE_PER_CWT_CENTS"],
        "discount_pct": TEST_DEFAULTS["DISCOUNT_PCT"],
        "min_charge_cents": TEST_DEFAULTS["MIN_CHARGE_CENTS"],
    }
    payload.update(overrides)
    return payload


def activate_rate_program_payload(expected_customer_version: int) -> dict:
    return {"expected_customer_version": expected_customer_version}


def create_exception_agreement_payload(
    customer_id: str,
    commodity_profile_id: str,
    effective_from: str,
    effective_to: str,
    **overrides,
) -> dict:
    payload = {
        "customer_id": customer_id,
        "commodity_profile_id": commodity_profile_id,
        "agreement_type": "EXCEPTION_CLASS",
        "agreed_class_code": 92.5,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(
    customer_id: str, origin_terminal_id: str, pro_number: str, **overrides
) -> dict:
    payload = {
        "customer_id": customer_id,
        "origin_terminal_id": origin_terminal_id,
        "pro_number": pro_number,
        "pickup_at": TEST_DEFAULTS["PICKUP_AT"],
        "bol_declared_total_weight_lb": 400,
    }
    payload.update(overrides)
    return payload


def create_shipment_line_payload(commodity_profile_id: str, **overrides) -> dict:
    payload = {
        "line_no": 1,
        "commodity_profile_id": commodity_profile_id,
        "declared_class_code": 70,
        "declared_weight_lb": 400,
        "pieces": 4,
        "declared_length_in": 48.0,
        "declared_width_in": 40.0,
        "declared_height_in": 48.0,
    }
    payload.update(overrides)
    return payload


def line_measurement(
    line_no: int,
    measured_weight_lb: int,
    measured_length_in: float,
    measured_width_in: float,
    measured_height_in: float,
) -> dict:
    return {
        "line_no": line_no,
        "measured_weight_lb": measured_weight_lb,
        "measured_length_in": measured_length_in,
        "measured_width_in": measured_width_in,
        "measured_height_in": measured_height_in,
    }


def create_capture_event_payload(
    shipment_id: str,
    measured_total_weight_lb: int,
    line_measurements: list,
    device_type: str = "COMBINED",
    **overrides,
) -> dict:
    payload = {
        "shipment_id": shipment_id,
        "device_type": device_type,
        "measured_total_weight_lb": measured_total_weight_lb,
        "line_measurements": line_measurements,
    }
    payload.update(overrides)
    return payload


def create_inspection_finding_payload(shipment_line_id: str, **overrides) -> dict:
    payload = {
        "shipment_line_id": shipment_line_id,
        "finding_basis": "DENSITY",
        "found_class_code": 250,
        "evidence_photo_count": 3,
    }
    payload.update(overrides)
    return payload


def create_correction_notice_payload(
    shipment_id: str, expected_shipment_version: int, **overrides
) -> dict:
    payload = {
        "shipment_id": shipment_id,
        "notice_type": "RECLASS",
        "expected_shipment_version": expected_shipment_version,
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(correction_notice_id: str, **overrides) -> dict:
    payload = {
        "correction_notice_id": correction_notice_id,
        "claim_basis": "DENSITY_RECOMPUTE",
        "evidence_doc_count": 2,
    }
    payload.update(overrides)
    return payload


def resolve_dispute_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def supplement_dispute_payload(additional_doc_count: int) -> dict:
    return {"additional_doc_count": additional_doc_count}


def create_repricing_run_payload(
    new_tariff_version_id: str,
    sample_window_start_at: str,
    sample_window_end_at: str,
    **overrides,
) -> dict:
    payload = {
        "new_tariff_version_id": new_tariff_version_id,
        "scope": "ALL_CLASS_BASED",
        "sample_window_start_at": sample_window_start_at,
        "sample_window_end_at": sample_window_end_at,
    }
    payload.update(overrides)
    return payload
