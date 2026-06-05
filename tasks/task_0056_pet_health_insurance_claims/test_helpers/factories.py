"""Payload factories — one per entity, input fields only."""


def create_account_payload(**overrides) -> dict:
    defaults = {"email": "holder@example.com", "full_name": "Test Holder"}
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    """Required: pet_name, species, base_premium_cents, annual_deductible_cents,
    reimbursement_rate_bps, annual_cap_cents, effective_date.
    Optional (defaulted server-side): waiting_period_days (14), wellness_rider (false)."""
    defaults = {
        "pet_name": "Rex",
        "species": "DOG",
        "base_premium_cents": 4500,
        "annual_deductible_cents": 25000,
        "reimbursement_rate_bps": 8000,
        "annual_cap_cents": 500000,
        "waiting_period_days": 14,
        "wellness_rider": False,
        "effective_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_condition_payload(**overrides) -> dict:
    defaults = {"name": "condition", "first_diagnosed_date": "2026-02-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    """Required: claim_type, incident_date. condition_id optional (required for non-WELLNESS)."""
    defaults = {"claim_type": "ILLNESS", "incident_date": "2026-03-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {"description": "service", "billed_amount_cents": 40000}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {"file_uri": "s3://invoices/doc"}
    defaults.update(overrides)
    return defaults
