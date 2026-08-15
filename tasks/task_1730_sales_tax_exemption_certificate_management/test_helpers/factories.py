"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS


def create_tenant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["TENANT_LEGAL_NAME"],
        "home_state_code": TEST_DEFAULTS["TENANT_HOME_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": TEST_DEFAULTS["SHIP_TO_STATE"],
        "accepted_form_types": ["RESALE"],
        "validity_window_days": 0,
        "anchor_rule": "EFFECTIVE_DATE",
        "allows_drop_ship_resale": False,
        "requires_state_registration_number": False,
        "blanket_cert_allowed": False,
    }
    defaults.update(overrides)
    return defaults


def create_exemption_reason_payload(**overrides) -> dict:
    defaults = {
        "code": TEST_DEFAULTS["REASON_CODE"],
        "description": "Resale",
        "tax_engine_code": TEST_DEFAULTS["REASON_TAX_ENGINE_CODE"],
        "requires_certificate": True,
        "allowed_form_types": ["RESALE"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "external_ref": "C1",
        "legal_name": "Customer One",
        "primary_ship_to_state": TEST_DEFAULTS["SHIP_TO_STATE"],
        "exemption_reason_code": TEST_DEFAULTS["REASON_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "ship_to_state": TEST_DEFAULTS["SHIP_TO_STATE"],
        "form_type": "RESALE",
        "exemption_reason_code": TEST_DEFAULTS["REASON_CODE"],
        "state_registration_number": "",
        "signed_date": TEST_DEFAULTS["SIGNED_DATE"],
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_certificate_version_payload(**overrides) -> dict:
    defaults = {
        "file_uri": "s3://cert.pdf",
        "form_type": "RESALE",
        "signed_date": TEST_DEFAULTS["SIGNED_DATE"],
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "order_ref": "O1",
        "ship_to_state": TEST_DEFAULTS["SHIP_TO_STATE"],
        "exemption_reason_code": TEST_DEFAULTS["REASON_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    defaults = {
        "sku": "ABC-1",
        "quantity": 1,
        "unit_price_cents": 5000,
        "is_exempt_claimed": True,
    }
    defaults.update(overrides)
    return defaults


def create_drop_ship_link_payload(retailer_customer_id, resale_certificate_id, **overrides) -> dict:
    defaults = {
        "retailer_customer_id": retailer_customer_id,
        "ship_to_state": TEST_DEFAULTS["SHIP_TO_STATE"],
        "resale_certificate_id": resale_certificate_id,
    }
    defaults.update(overrides)
    return defaults


def create_audit_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "A1",
        "population_state_filter": [TEST_DEFAULTS["SHIP_TO_STATE"]],
        "sampling_method": "FIXED_FLOOR",
        "floor_sample_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_remediation_action_payload(**overrides) -> dict:
    defaults = {
        "action_type": "WAIVE_SAMPLE",
        "assigned_to_user_id": "u_co1",
    }
    defaults.update(overrides)
    return defaults


def create_outreach_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "OC1",
        "target_state_filter": [],
        "days_before_expiration": 30,
        "scheduled_send_day_index": 1,
    }
    defaults.update(overrides)
    return defaults
