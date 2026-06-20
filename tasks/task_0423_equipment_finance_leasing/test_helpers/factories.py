"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields with server-side defaults
(advance_payment_count, security_deposit_cents, trac_residual_pct_bps,
renewal_months, replaces_equipment_unit_id) are omitted unless overridden.
"""
from .constants import TEST_DEFAULTS


def create_lessor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Atlas Leasing",
        "home_state_code": TEST_DEFAULTS["HOME_STATE_CODE"],
        "sales_tax_rate_bps": TEST_DEFAULTS["SALES_TAX_RATE_BPS"],
        "property_tax_rate_bps": TEST_DEFAULTS["PROPERTY_TAX_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": "MachineCo",
        "remit_account": "RA-1",
    }
    defaults.update(overrides)
    return defaults


def create_credit_application_payload(**overrides) -> dict:
    defaults = {
        "applicant_legal_name": "Acme Customer",
        "requested_amount_cents": TEST_DEFAULTS["REQUESTED_AMOUNT_CENTS"],
        "credit_score": TEST_DEFAULTS["CREDIT_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def approve_application_payload(approved_amount_cents: int, **overrides) -> dict:
    defaults = {"approved_amount_cents": approved_amount_cents}
    defaults.update(overrides)
    return defaults


def create_lease_payload(vendor_id: str, **overrides) -> dict:
    """Lease origination. Optional advance_payment_count / security_deposit_cents /
    trac_residual_pct_bps are only emitted when supplied via overrides."""
    defaults = {
        "vendor_id": vendor_id,
        "lease_type": "FMV",
        "equipment_cost_cents": TEST_DEFAULTS["EQUIPMENT_COST_CENTS"],
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "monthly_rate_factor_bps": TEST_DEFAULTS["MONTHLY_RATE_FACTOR_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(serial_number: str, original_cost_cents: int = 500_000,
                             **overrides) -> dict:
    defaults = {
        "serial_number": serial_number,
        "description": "Press",
        "original_cost_cents": original_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def book_lease_payload(expected_lease_version: int, **overrides) -> dict:
    defaults = {"expected_lease_version": expected_lease_version}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_invoice_payload(schedule_line_id: str, **overrides) -> dict:
    defaults = {"schedule_line_id": schedule_line_id}
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_ucc_filing_payload(jurisdiction_state_code: str, **overrides) -> dict:
    defaults = {"jurisdiction_state_code": jurisdiction_state_code}
    defaults.update(overrides)
    return defaults


def create_tax_assessment_payload(tax_type: str, **overrides) -> dict:
    defaults = {"tax_type": tax_type}
    defaults.update(overrides)
    return defaults


def create_addon_payload(kind: str, added_cost_cents: int, serial_number: str,
                         **overrides) -> dict:
    """Add-on proposal. For UPGRADE, pass replaces_equipment_unit_id via overrides."""
    defaults = {
        "kind": kind,
        "added_cost_cents": added_cost_cents,
        "serial_number": serial_number,
        "description": "Attachment",
    }
    defaults.update(overrides)
    return defaults


def create_eot_election_payload(election: str, **overrides) -> dict:
    """End-of-term election. For RENEW, pass renewal_months via overrides."""
    defaults = {"election": election}
    defaults.update(overrides)
    return defaults


def exercise_election_payload(**overrides) -> dict:
    """Exercise. For BUYOUT, pass buyout_payment_cents via overrides."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def record_sale_payload(sale_proceeds_cents: int, **overrides) -> dict:
    defaults = {"sale_proceeds_cents": sale_proceeds_cents}
    defaults.update(overrides)
    return defaults
