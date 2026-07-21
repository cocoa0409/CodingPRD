"""Payload factories — one per entity, input fields only.

Canonical defaults match the common setup values used throughout the suite so a
test overrides only the values that distinguish it.
"""

DEFAULTS = {
    "plan_sponsor_name": "Acme",
    "plan_sponsor_tax_id": "11-1111111",
    "plan_year_start": "2026-01-01",
    "plan_year_end": "2026-12-31",
    "individual_deductible_cents": 100000,
    "oop_max_cents": 500000,
    "plan_coinsurance_pct": 0.80,
    "run_out_days": 90,
    "provider_name": "InNet",
    "provider_tax_id": "22-2222222",
    "provider_npi": "1111111111",
    "member_first_name": "Mia",
    "member_last_name": "N",
    "coverage_effective_date": "2026-01-01",
    "carrier_name": "ReCarrier",
    "effective_date": "2026-01-01",
    "expiry_date": "2027-01-01",
    "specific_deductible_cents": 5000000,
    "aggregate_attachment_cents": 100000000,
    "service_date": "2026-03-01",
}


def create_plan_payload(**overrides) -> dict:
    payload = {
        "sponsor_name": DEFAULTS["plan_sponsor_name"],
        "sponsor_tax_id": DEFAULTS["plan_sponsor_tax_id"],
        "plan_year_start": DEFAULTS["plan_year_start"],
        "plan_year_end": DEFAULTS["plan_year_end"],
        "individual_deductible_cents": DEFAULTS["individual_deductible_cents"],
        "oop_max_cents": DEFAULTS["oop_max_cents"],
        "plan_coinsurance_pct": DEFAULTS["plan_coinsurance_pct"],
        "run_out_days": DEFAULTS["run_out_days"],
    }
    payload.update(overrides)
    return payload


def create_provider_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["provider_name"],
        "tax_id": DEFAULTS["provider_tax_id"],
        "npi": DEFAULTS["provider_npi"],
        "in_network": True,
        "ppo_discount_pct": 0.40,
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {
        "first_name": DEFAULTS["member_first_name"],
        "last_name": DEFAULTS["member_last_name"],
        "coverage_effective_date": DEFAULTS["coverage_effective_date"],
    }
    payload.update(overrides)
    return payload


def create_stop_loss_policy_payload(**overrides) -> dict:
    payload = {
        "carrier_name": DEFAULTS["carrier_name"],
        "contract_basis": "PAID",
        "effective_date": DEFAULTS["effective_date"],
        "expiry_date": DEFAULTS["expiry_date"],
        "specific_deductible_cents": DEFAULTS["specific_deductible_cents"],
        "aggregate_attachment_cents": DEFAULTS["aggregate_attachment_cents"],
    }
    payload.update(overrides)
    return payload


def create_laser_payload(**overrides) -> dict:
    payload = {
        "laser_deductible_cents": 10000000,
        "effective_date": "2026-01-01",
        "expiry_date": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def create_claim_payload(**overrides) -> dict:
    payload = {
        "service_date": DEFAULTS["service_date"],
        "billed_lines": [{"billed_cents": 100000}],
    }
    payload.update(overrides)
    return payload
