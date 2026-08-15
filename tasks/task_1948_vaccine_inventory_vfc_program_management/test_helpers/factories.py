"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import (
    AUDIT_VISIT_DATE,
    DEFAULT_EXPIRES_ON,
    FRIDGE_MAX_C,
    FRIDGE_MIN_C,
    PEDIATRIC_DOB,
    VISIT_DATE,
)

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):05d}"


def create_provider_site_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {"site_name": f"Test Site {n}", "vfc_pin": f"PIN-{n:05d}"}
    defaults.update(overrides)
    return defaults


def create_storage_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_label": _uniq("Fridge"),
        "unit_kind": "REFRIGERATOR",
        "min_temp_c": FRIDGE_MIN_C,
        "max_temp_c": FRIDGE_MAX_C,
    }
    defaults.update(overrides)
    return defaults


def create_vaccine_product_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "ndc_code": f"00006-{4600 + (n % 900):04d}-{n % 100:02d}",
        "display_name": "MMR II (Merck)",
        "presentation": "SINGLE_DOSE_VIAL",
        "doses_per_container": 1,
        "vfc_program_eligible": True,
        "storage_requirement": "REFRIGERATED_2_8C",
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(storage_unit_id, vaccine_product_id, **overrides) -> dict:
    defaults = {
        "storage_unit_id": storage_unit_id,
        "vaccine_product_id": vaccine_product_id,
        "lot_number": _uniq("LOT"),
        "stock_type": "PRIVATE",
        "quantity_on_hand": 5,
        "expires_on": DEFAULT_EXPIRES_ON,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("Patient"),
        "date_of_birth": PEDIATRIC_DOB,
        "insurance_category": "MEDICAID",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(**overrides) -> dict:
    defaults = {
        "screening_date": VISIT_DATE,
        "insurance_category_at_visit": "MEDICAID",
    }
    defaults.update(overrides)
    return defaults


def create_dose_administration_payload(
    patient_id, eligibility_screening_id, lot_id, **overrides
) -> dict:
    defaults = {
        "patient_id": patient_id,
        "eligibility_screening_id": eligibility_screening_id,
        "lot_id": lot_id,
        "administration_date": VISIT_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_vaccine_order_payload(**overrides) -> dict:
    defaults = {"expected_vfc_doses": 5}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(vaccine_product_id, **overrides) -> dict:
    defaults = {"vaccine_product_id": vaccine_product_id, "requested_doses": 5}
    defaults.update(overrides)
    return defaults


def create_approve_order_payload(
    approved_vfc_doses, expected_provider_site_version, line_allocations=None
) -> dict:
    payload = {
        "approved_vfc_doses": approved_vfc_doses,
        "expected_provider_site_version": expected_provider_site_version,
    }
    if line_allocations is not None:
        payload["line_allocations"] = line_allocations
    return payload


def create_allocation_receipt_payload(order_line_id, storage_unit_id, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "storage_unit_id": storage_unit_id,
        "lot_number": _uniq("LOT"),
        "expires_on": DEFAULT_EXPIRES_ON,
        "quantity_doses": 5,
    }
    defaults.update(overrides)
    return defaults


def create_borrow_ticket_payload(from_lot_id, to_lot_id, **overrides) -> dict:
    defaults = {
        "from_lot_id": from_lot_id,
        "to_lot_id": to_lot_id,
        "direction": "PUBLIC_FROM_PRIVATE",
        "borrowed_quantity": 1,
        "reason_code": "STOCK_OUT",
    }
    defaults.update(overrides)
    return defaults


def create_payback_payload(payback_quantity, paying_lot_id, expected_borrow_ticket_version) -> dict:
    return {
        "payback_quantity": payback_quantity,
        "paying_lot_id": paying_lot_id,
        "expected_borrow_ticket_version": expected_borrow_ticket_version,
    }


def create_transfer_payload(
    from_lot_id, destination_site_id, destination_storage_unit_id, **overrides
) -> dict:
    defaults = {
        "from_lot_id": from_lot_id,
        "destination_site_id": destination_site_id,
        "destination_storage_unit_id": destination_storage_unit_id,
        "quantity_doses": 1,
        "reason": "short-dated, reallocate to high-volume site",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {"visit_date": AUDIT_VISIT_DATE}
    defaults.update(overrides)
    return defaults


def create_reading_payload(recorded_at, temperature_c) -> dict:
    return {"recorded_at": recorded_at, "temperature_c": temperature_c}
