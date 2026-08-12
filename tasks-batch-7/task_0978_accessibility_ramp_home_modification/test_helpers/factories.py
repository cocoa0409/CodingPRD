"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS

_seq = {"n": 0}


def _next() -> int:
    _seq["n"] += 1
    return _seq["n"]


def create_case_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "client_name": f"Test Client {n}",
        "client_address": f"{n} Ramp Way",
        "client_phone": TEST_DEFAULTS["CLIENT_PHONE"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "assessor_id": f"ot-{n}",
        "assessor_role": "OT",
        "assessment_type": "INITIAL",
        "scheduled_date": "2026-05-01T00:00:00Z",
        "mobility_score": TEST_DEFAULTS["MOBILITY_SCORE"],
        "hazard_count": TEST_DEFAULTS["HAZARD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def complete_assessment_payload(**overrides) -> dict:
    defaults = {
        "mobility_score": TEST_DEFAULTS["MOBILITY_SCORE"],
        "hazard_count": TEST_DEFAULTS["HAZARD_COUNT"],
        "recommended_modifications": ["RAMP"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(expected_case_version, **overrides) -> dict:
    defaults = {
        "valid_until": TEST_DEFAULTS["QUOTE_VALID_UNTIL"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_quote_line_item_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "line_type": "MATERIAL",
        "description": f"Line item {n}",
        "quantity": 1,
        "unit": "each",
        "unit_price_cents": 10000,
        "tax_rate_pct": 0.0,
        "sort_order": n,
    }
    defaults.update(overrides)
    return defaults


def create_funding_source_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "source_type": "STATE_GRANT",
        "program_name": f"Program {n}",
        "requested_cents": 10000,
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def approve_funding_payload(approved_cents, expected_case_version) -> dict:
    return {
        "approved_cents": approved_cents,
        "expected_case_version": expected_case_version,
    }


def create_funding_allocation_payload(quote_id, amount_cents, **overrides) -> dict:
    defaults = {
        "quote_id": quote_id,
        "amount_cents": amount_cents,
        "allocation_type": "QUOTE_LEVEL",
    }
    defaults.update(overrides)
    return defaults


def create_installation_job_payload(quote_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "quote_id": quote_id,
        "scheduled_start": "2026-05-01T00:00:00Z",
        "scheduled_end": "2026-05-10T00:00:00Z",
        "crew_lead_id": f"crew-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_rental_ramp_payload(inventory_unit_id, **overrides) -> dict:
    defaults = {
        "inventory_unit_id": inventory_unit_id,
        "rental_start": TEST_DEFAULTS["RENTAL_START"],
        "rental_end": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inventory_unit_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "unit_tag": f"U-{n:03d}",
        "ramp_type": "MODULAR_ALUMINUM",
        "length_feet": 20,
        "width_inches": 36,
        "weight_capacity_lbs": 700,
        "monthly_rate_cents": 20000,
        "purchase_price_cents": 400000,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "inspection_type": "PRE_INSTALL",
        "inspector_id": f"insp-{n}",
        "scheduled_date": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def fail_inspection_payload(**overrides) -> dict:
    defaults = {
        "deficiencies": ["SLOPE_STEEP"],
        "correction_deadline": "2026-05-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(expected_case_version, **overrides) -> dict:
    defaults = {
        "invoice_type": "SERVICE_CALL",
        "due_date": TEST_DEFAULTS["INVOICE_DUE_DATE"],
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_line_item_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "description": f"Invoice line {n}",
        "quantity": 1,
        "unit_price_cents": 1000,
        "tax_rate_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def create_warranty_claim_payload(installation_job_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "installation_job_id": installation_job_id,
        "issue_description": f"Issue {n}",
        "severity": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_ot_consultation_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "ot_provider_id": f"otp-{n}",
        "consultation_type": "HOME_SAFETY",
        "scheduled_date": "2026-05-01T00:00:00Z",
        "goals": ["safe_transfer"],
    }
    defaults.update(overrides)
    return defaults


def create_reassessment_schedule_payload(**overrides) -> dict:
    defaults = {
        "trigger_event": "TIME_BASED",
        "due_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
