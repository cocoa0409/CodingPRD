"""Payload factories — one per creatable resource, input fields only."""
from .constants import WINDOW_START, WINDOW_END


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Acme Builders",
        "credit_limit_cents": 100000000,
        "delivery_terms": "DELIVERED",
    }
    defaults.update(overrides)
    return defaults


def create_engineer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Eng One",
        "license_number": "PE-1",
        "license_state": "GA",
        "license_expiry": "2027-06-30T00:00:00Z",
        "seal_authority": "TRUSS_AND_PANEL",
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "job_name": "Test Job",
        "jobsite_address": "1 Site Rd",
        "jobsite_state": "GA",
        "delivery_window_start": WINDOW_START,
        "delivery_window_end": WINDOW_END,
        "contracted_value_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_design_payload(expected_job_version, **overrides) -> dict:
    defaults = {
        "component_ref": "TR-01",
        "component_type": "ROOF_TRUSS",
        "span_ft": 32.0,
        "pitch_degrees": 26.57,
        "design_load_psf": 40.0,
        "lumber_grade": "SPF_MSR2400",
        "plating": "P20",
        "quantity_required": 10,
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def cut_list_line_payload(member_label, dimension, length_ft, qty) -> dict:
    return {
        "member_label": member_label,
        "dimension": dimension,
        "length_ft": length_ft,
        "qty": qty,
    }


def create_cut_list_payload(jig_setup_id, lines, **overrides) -> dict:
    defaults = {"jig_setup_id": jig_setup_id, "lines": lines}
    defaults.update(overrides)
    return defaults


def create_jig_payload(**overrides) -> dict:
    defaults = {
        "setup_code": "JIG-ROOF-A",
        "component_type_supported": "ROOF_TRUSS",
        "plate_class": "P20",
        "changeover_minutes_from": {},
    }
    defaults.update(overrides)
    return defaults


def create_lumber_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_kind": "LUMBER",
        "lumber_dimension": "L2X6",
        "lumber_grade": "SPF_MSR2400",
        "received_board_feet": 500.0,
        "unit_cost_cents_per_bf": 900,
    }
    defaults.update(overrides)
    return defaults


def create_plate_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_kind": "PLATE",
        "plate_class": "P20",
        "received_plates": 1000,
        "unit_cost_cents_per_plate": 250,
    }
    defaults.update(overrides)
    return defaults


def create_lumber_reservation_payload(lot_id, expected_lot_version, cut_list_line_id, reserved_bf) -> dict:
    return {
        "lot_id": lot_id,
        "expected_lot_version": expected_lot_version,
        "cut_list_line_id": cut_list_line_id,
        "reserved_bf": reserved_bf,
    }


def create_plate_reservation_payload(lot_id, expected_lot_version, cut_list_id, reserved_plates) -> dict:
    return {
        "lot_id": lot_id,
        "expected_lot_version": expected_lot_version,
        "cut_list_id": cut_list_id,
        "reserved_plates": reserved_plates,
    }


def create_crane_payload(**overrides) -> dict:
    defaults = {
        "crane_code": "CR-HEAVY",
        "capacity_lbs": 30000,
        "crane_class": "HEAVY",
        "hourly_rate_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_crane_slot_payload(crane_id, purpose, start_at, end_at, expected_crane_version, **overrides) -> dict:
    defaults = {
        "crane_id": crane_id,
        "purpose": purpose,
        "start_at": start_at,
        "end_at": end_at,
        "expected_crane_version": expected_crane_version,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(cut_list_id, jig_setup_id, requested_completion_at="2026-08-15T00:00:00Z") -> dict:
    return {
        "cut_list_id": cut_list_id,
        "jig_setup_id": jig_setup_id,
        "requested_completion_at": requested_completion_at,
    }


def create_load_payload(scheduled_date="2026-08-21T00:00:00Z", planned_weight_est_lbs=8000) -> dict:
    return {
        "scheduled_date": scheduled_date,
        "planned_weight_est_lbs": planned_weight_est_lbs,
    }


def create_bundle_payload(production_batch_id, stack_position, weight_lbs, **overrides) -> dict:
    defaults = {
        "production_batch_id": production_batch_id,
        "stack_position": stack_position,
        "weight_lbs": weight_lbs,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(bundle_id, **overrides) -> dict:
    defaults = {
        "bundle_id": bundle_id,
        "claim_type": "FIELD_DAMAGE",
        "description": "cracked chord",
        "claimed_amount_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(supersedes_design_id, expected_job_version, **overrides) -> dict:
    defaults = {
        "supersedes_design_id": supersedes_design_id,
        "reason": "field dimension change",
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults
