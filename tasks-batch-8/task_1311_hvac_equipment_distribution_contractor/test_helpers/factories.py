"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "company_name": _uniq("Company"),
        "license_number": _uniq("LIC"),
    }
    defaults.update(overrides)
    return defaults


def create_equipment_model_payload(**overrides) -> dict:
    defaults = {
        "model_number": _uniq("CU"),
        "equipment_type": "CONDENSER",
        "refrigerant_type": "R410A",
        "capacity_btuh": 36000,
        "family_code": "FAM-A",
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_ahri_rating_payload(outdoor_unit_id: str, indoor_unit_id: str, **overrides) -> dict:
    defaults = {
        "ahri_reference_number": _uniq("AHRI"),
        "outdoor_unit_id": outdoor_unit_id,
        "indoor_unit_id": indoor_unit_id,
        "seer2": 17.0,
        "eer2": 12.5,
    }
    defaults.update(overrides)
    return defaults


def create_prebuy_program_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("PREBUY"),
        "family_code": "FAM-A",
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-09-01T00:00:00Z",
        "ship_by_date": "2026-09-15T00:00:00Z",
        "deposit_pct": 0.25,
        "discount_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_pool_payload(**overrides) -> dict:
    defaults = {
        "family_code": "FAM-A",
        "season_start": "2026-08-01T00:00:00Z",
        "season_end": "2026-09-01T00:00:00Z",
        "total_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(contractor_id: str, **overrides) -> dict:
    defaults = {"contractor_id": contractor_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    defaults = {"quantity": 1}
    defaults.update(overrides)
    return defaults


def create_warranty_registration_payload(
    serial_number: str, equipment_model_id: str, contractor_id: str,
    order_id: str, install_date: str, **overrides,
) -> dict:
    defaults = {
        "serial_number": serial_number,
        "equipment_model_id": equipment_model_id,
        "contractor_id": contractor_id,
        "order_id": order_id,
        "install_date": install_date,
    }
    defaults.update(overrides)
    return defaults


def create_parts_claim_payload(
    warranty_registration_id: str, contractor_id: str, failure_date: str, **overrides,
) -> dict:
    defaults = {
        "warranty_registration_id": warranty_registration_id,
        "contractor_id": contractor_id,
        "failure_date": failure_date,
        "part_cost_cents": 100_000,
        "labor_cost_cents": 40_000,
    }
    defaults.update(overrides)
    return defaults


def create_cylinder_payload(**overrides) -> dict:
    defaults = {
        "cylinder_tag": _uniq("CYL"),
        "refrigerant_type": "R410A",
        "tare_weight_lbs": TEST_DEFAULTS["TARE_WEIGHT_LBS"],
        "full_weight_lbs": TEST_DEFAULTS["FULL_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_rebate_submission_payload(
    contractor_id: str, order_id: str, ahri_rating_id: str, **overrides,
) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "order_id": order_id,
        "ahri_rating_id": ahri_rating_id,
        "program_type": "FEDERAL_TAX_CREDIT",
        "homeowner_name": "H Homeowner",
        "install_address": "1 Main St",
        "install_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_training_course_payload(**overrides) -> dict:
    defaults = {
        "course_code": _uniq("TC"),
        "title": "R-454B Handling",
        "credit_hours": 4,
        "session_start": "2026-08-10T00:00:00Z",
        "session_end": "2026-08-12T00:00:00Z",
        "instructor_name": _uniq("Instructor"),
        "max_seats": 20,
    }
    defaults.update(overrides)
    return defaults


def create_coop_claim_payload(contractor_id: str, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "invoice_reference": _uniq("INV-AD"),
        "period": "2026-H2",
        "spend_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults
