"""Payload factories — one per entity, input fields only.

Each factory carries only the fields the PRD declares as client input for the
create endpoint. Required fields get sensible defaults; optional fields are
omitted unless overridden.
"""
import uuid


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_test_offering_payload(**overrides) -> dict:
    """POST /catalog/test-offerings. Required: test_code, display_name,
    list_price_cents, specimen_type. Optional flags/bounds omitted by default."""
    defaults = {
        "test_code": "TC" + _unique_suffix().upper(),
        "display_name": "Test Offering",
        "list_price_cents": 4000,
        "specimen_type": "BLOOD",
    }
    defaults.update(overrides)
    return defaults


def create_panel_bundle_payload(**overrides) -> dict:
    """POST /catalog/panel-bundles. Required: bundle_code, display_name,
    member_test_codes, bundle_price_cents."""
    defaults = {
        "bundle_code": "BND" + _unique_suffix().upper(),
        "display_name": "Panel Bundle",
        "member_test_codes": [],
        "bundle_price_cents": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    """POST /catalog/patients. Required: email, full_name, date_of_birth,
    state_code. Optional: hsa_balance_cents, consent_share_results."""
    defaults = {
        "email": "patient_" + _unique_suffix() + "@x.com",
        "full_name": "Test Patient",
        "date_of_birth": "1990-01-01",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_cart_payload(patient_id, **overrides) -> dict:
    """POST /catalog/carts. Required: patient_id. Optional: fund_source."""
    defaults = {"patient_id": patient_id}
    defaults.update(overrides)
    return defaults


def create_cart_line_payload(cart_id, test_offering_id, **overrides) -> dict:
    """POST /catalog/cart-lines. Required: cart_id, test_offering_id."""
    defaults = {"cart_id": cart_id, "test_offering_id": test_offering_id}
    defaults.update(overrides)
    return defaults


def create_order_payload(cart_id, fulfillment_mode, expected_cart_version, **overrides) -> dict:
    """POST /catalog/orders. Required: cart_id, fulfillment_mode, expected_cart_version."""
    defaults = {
        "cart_id": cart_id,
        "fulfillment_mode": fulfillment_mode,
        "expected_cart_version": expected_cart_version,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(order_id, psc_location_code, slot_start, slot_end, **overrides) -> dict:
    """POST /catalog/appointments. Required: order_id, psc_location_code,
    slot_start, slot_end. Optional: fasting_confirmed."""
    defaults = {
        "order_id": order_id,
        "psc_location_code": psc_location_code,
        "slot_start": slot_start,
        "slot_end": slot_end,
    }
    defaults.update(overrides)
    return defaults


def create_home_kit_payload(order_id, shipping_state_code, **overrides) -> dict:
    """POST /catalog/home-kits. Required: order_id, shipping_state_code."""
    defaults = {"order_id": order_id, "shipping_state_code": shipping_state_code}
    defaults.update(overrides)
    return defaults


def process_specimen_payload(analyzer_value, **overrides) -> dict:
    """POST /catalog/specimens/{id}/process. Required: analyzer_value."""
    defaults = {"analyzer_value": analyzer_value}
    defaults.update(overrides)
    return defaults


def amend_lab_result_payload(analyzer_value, **overrides) -> dict:
    """POST /catalog/lab-results/{id}/amend. Required: analyzer_value."""
    defaults = {"analyzer_value": analyzer_value}
    defaults.update(overrides)
    return defaults


def create_telehealth_referral_payload(lab_result_id, **overrides) -> dict:
    """POST /catalog/telehealth-referrals. Required: lab_result_id."""
    defaults = {"lab_result_id": lab_result_id}
    defaults.update(overrides)
    return defaults


def create_analyzer_run_payload(analyzer_code, run_start, run_end, **overrides) -> dict:
    """POST /catalog/analyzer-runs. Required: analyzer_code, run_start, run_end.
    Optional: buffer_minutes (default 30 server-side)."""
    defaults = {
        "analyzer_code": analyzer_code,
        "run_start": run_start,
        "run_end": run_end,
    }
    defaults.update(overrides)
    return defaults


def physician_decision_payload(decision, **overrides) -> dict:
    """POST /catalog/physician-orders/{id}/decision. Required: decision.
    Optional: clinical_note."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
