"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Required vs optional follows the PRD §3 workflows.
"""

DEFAULTS = {
    "REG_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "OPEN_AT": "2026-02-01T00:00:00Z",
    "CLOSE_AT": "2026-03-01T00:00:00Z",
    "NAICS_THRESHOLD": 500,
}


def create_vendor_payload(**overrides) -> dict:
    """POST /vendors. Required: legal_name, uei, employee_count, registration_expires_at.
    Optional: set_aside_certifications (defaults to [] server-side)."""
    defaults = {
        "legal_name": "Test Vendor",
        "uei": "TEST00000001",
        "employee_count": 50,
        "registration_expires_at": DEFAULTS["REG_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_solicitation_payload(**overrides) -> dict:
    """POST /solicitations. Required: title, vehicle_type, naics_size_threshold,
    open_at, close_at. Optional: set_aside_type (defaults to NONE server-side)."""
    defaults = {
        "title": "Test Solicitation",
        "vehicle_type": "RFP",
        "naics_size_threshold": DEFAULTS["NAICS_THRESHOLD"],
        "open_at": DEFAULTS["OPEN_AT"],
        "close_at": DEFAULTS["CLOSE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_factor_payload(name, kind, weight, **overrides) -> dict:
    """POST /solicitations/{id}/factors. Required: name, kind, weight."""
    defaults = {"name": name, "kind": kind, "weight": weight}
    defaults.update(overrides)
    return defaults


def create_proposal_payload(solicitation_id, vendor_id, total_price_cents, **overrides) -> dict:
    """POST /proposals. Required: solicitation_id, vendor_id, total_price_cents."""
    defaults = {
        "solicitation_id": solicitation_id,
        "vendor_id": vendor_id,
        "total_price_cents": total_price_cents,
    }
    defaults.update(overrides)
    return defaults


def create_score_payload(factor_id, raw_score, **overrides) -> dict:
    """POST /proposals/{id}/scores. Required: factor_id, raw_score."""
    defaults = {"factor_id": factor_id, "raw_score": raw_score}
    defaults.update(overrides)
    return defaults


def create_award_payload(solicitation_id, proposal_id, expected_solicitation_version, **overrides) -> dict:
    """POST /awards. Required: solicitation_id, proposal_id, expected_solicitation_version."""
    defaults = {
        "solicitation_id": solicitation_id,
        "proposal_id": proposal_id,
        "expected_solicitation_version": expected_solicitation_version,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(award_id, contract_type, base_value_cents, **overrides) -> dict:
    """POST /contracts. Required: award_id, contract_type, base_value_cents.
    For CPFF, total_estimated_cost_cents and fixed_fee_cents must be supplied via overrides."""
    defaults = {
        "award_id": award_id,
        "contract_type": contract_type,
        "base_value_cents": base_value_cents,
    }
    defaults.update(overrides)
    return defaults


def create_clin_payload(clin_number, unit_price_cents, funded_qty, **overrides) -> dict:
    """POST /contracts/{id}/clins. Required (FFP): clin_number, unit_price_cents, funded_qty."""
    defaults = {
        "clin_number": clin_number,
        "unit_price_cents": unit_price_cents,
        "funded_qty": funded_qty,
    }
    defaults.update(overrides)
    return defaults


def create_ffp_invoice_payload(contract_id, clin_id, invoiced_qty, expected_contract_version, **overrides) -> dict:
    """POST /invoices (FFP shape): contract_id, clin_id, invoiced_qty, expected_contract_version."""
    defaults = {
        "contract_id": contract_id,
        "clin_id": clin_id,
        "invoiced_qty": invoiced_qty,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_cpff_invoice_payload(contract_id, allowable_cost_cents, expected_contract_version, **overrides) -> dict:
    """POST /invoices (CPFF shape): contract_id, allowable_cost_cents, expected_contract_version."""
    defaults = {
        "contract_id": contract_id,
        "allowable_cost_cents": allowable_cost_cents,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_modification_payload(mod_type, **overrides) -> dict:
    """POST /contracts/{id}/modifications. Required: mod_type.
    delta_cents / option_value_cents / option_window_close_at via overrides."""
    defaults = {"mod_type": mod_type}
    defaults.update(overrides)
    return defaults


def create_protest_payload(award_id, protester_vendor_id, grounds, **overrides) -> dict:
    """POST /protests. Required: award_id, protester_vendor_id, grounds."""
    defaults = {
        "award_id": award_id,
        "protester_vendor_id": protester_vendor_id,
        "grounds": grounds,
    }
    defaults.update(overrides)
    return defaults


def create_cpars_payload(rating, **overrides) -> dict:
    """POST /contracts/{id}/cpars. Required: rating."""
    defaults = {"rating": rating}
    defaults.update(overrides)
    return defaults
