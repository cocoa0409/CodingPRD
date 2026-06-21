"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_property_payload(**overrides) -> dict:
    """Required input: name, state_code. Optional: recovery_cap_pct, common_area_pct."""
    defaults = {
        "name": "Test Property",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_utility_payload(property_id, **overrides) -> dict:
    """Required: property_id, utility_type, allocation_method, unit_of_measure.
    Optional: monthly_admin_fee_cents."""
    defaults = {
        "property_id": property_id,
        "utility_type": "WATER",
        "allocation_method": "CONSUMPTION",
        "unit_of_measure": "GAL",
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(property_id, **overrides) -> dict:
    """Required: property_id, unit_number, square_feet."""
    defaults = {
        "property_id": property_id,
        "unit_number": "101",
        "square_feet": 800,
    }
    defaults.update(overrides)
    return defaults


def create_meter_payload(property_id, utility_id, **overrides) -> dict:
    """Required: property_id, utility_id, serial_number."""
    defaults = {
        "property_id": property_id,
        "utility_id": utility_id,
        "serial_number": "SN-001",
    }
    defaults.update(overrides)
    return defaults


def assign_meter_payload(unit_id, effective_from=None, **overrides) -> dict:
    """Required: unit_id, effective_from. Optional: effective_to."""
    defaults = {
        "unit_id": unit_id,
        "effective_from": effective_from or TEST_DEFAULTS["PERIOD_START"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(unit_id, property_id, tenant_user_id, **overrides) -> dict:
    """Required: unit_id, property_id, tenant_user_id, occupant_count, move_in_date."""
    defaults = {
        "unit_id": unit_id,
        "property_id": property_id,
        "tenant_user_id": tenant_user_id,
        "occupant_count": 1,
        "move_in_date": TEST_DEFAULTS["MOVE_IN_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_bill_payload(property_id, utility_id, **overrides) -> dict:
    """Required: property_id, utility_id, period_label, total_cost_cents."""
    defaults = {
        "property_id": property_id,
        "utility_id": utility_id,
        "period_label": TEST_DEFAULTS["PERIOD_LABEL"],
        "total_cost_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_meter_read_payload(meter_id, property_id, **overrides) -> dict:
    """Required: meter_id, property_id, period_label, reading_value."""
    defaults = {
        "meter_id": meter_id,
        "property_id": property_id,
        "period_label": TEST_DEFAULTS["PERIOD_LABEL"],
        "reading_value": 100,
    }
    defaults.update(overrides)
    return defaults


def create_billing_cycle_payload(property_id, utility_id, vendor_bill_id, **overrides) -> dict:
    """Required: property_id, utility_id, vendor_bill_id, period_label, period_start, period_end."""
    defaults = {
        "property_id": property_id,
        "utility_id": utility_id,
        "vendor_bill_id": vendor_bill_id,
        "period_label": TEST_DEFAULTS["PERIOD_LABEL"],
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def post_payment_payload(amount_cents, expected_statement_version, **overrides) -> dict:
    """Required: amount_cents, expected_statement_version."""
    defaults = {
        "amount_cents": amount_cents,
        "expected_statement_version": expected_statement_version,
    }
    defaults.update(overrides)
    return defaults


def open_dispute_payload(reason="HIGH_READING", **overrides) -> dict:
    """Required: reason. Optional: requested_re_read, credit_amount_cents."""
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(credit_amount_cents=0, **overrides) -> dict:
    """Optional: credit_amount_cents (defaults to 0)."""
    defaults = {"credit_amount_cents": credit_amount_cents}
    defaults.update(overrides)
    return defaults
