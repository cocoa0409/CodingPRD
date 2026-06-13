"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the resource's input fields with sensible
defaults; pass **overrides to control any value a test needs to pin.
"""

DEFAULTS = {
    "PRODUCT_NAME": "Test Product",
    "OWNER_NAME": "Test Owner",
    "ANNUITANT_AGE": 60,
    "INITIAL_PREMIUM_CENTS": 2_000_000,
    "MIN_INITIAL_PREMIUM_CENTS": 1_000_000,
}


def create_product_payload(**overrides) -> dict:
    """FIXED product by default. fixed_annual_rate_bps is only valid for FIXED."""
    defaults = {
        "name": DEFAULTS["PRODUCT_NAME"],
        "contract_type": "FIXED",
        "fixed_annual_rate_bps": 0,
        "death_benefit_type": "ACCOUNT_VALUE",
        "surrender_charge_schedule": [{"contract_year": 0, "charge_bps": 0}],
        "min_initial_premium_cents": DEFAULTS["MIN_INITIAL_PREMIUM_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "owner_name": DEFAULTS["OWNER_NAME"],
        "annuitant_age": DEFAULTS["ANNUITANT_AGE"],
    }
    defaults.update(overrides)
    return defaults


def create_premium_payload(contract_id: str, expected_contract_version: int, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "gross_premium_cents": DEFAULTS["INITIAL_PREMIUM_CENTS"],
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_sub_account_allocation_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "division_name": "EQUITY",
        "allocation_bps": 10000,
        "unit_value_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_index_segment_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "index_name": "SP500",
        "term_start_date": "2026-01-01T00:00:00Z",
        "term_end_date": "2027-01-01T00:00:00Z",
        "segment_premium_cents": 1_000_000,
        "cap_bps": 800,
        "floor_bps": 0,
        "participation_bps": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_crediting_event_payload(contract_id: str, crediting_kind: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "crediting_kind": crediting_kind,
    }
    defaults.update(overrides)
    return defaults


def create_withdrawal_payload(contract_id: str, requested_amount_cents: int,
                              expected_contract_version: int, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "requested_amount_cents": requested_amount_cents,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(contract_id: str, share_bps: int, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "full_name": "Test Beneficiary",
        "relationship": "SPOUSE",
        "share_bps": share_bps,
    }
    defaults.update(overrides)
    return defaults


def create_annuitization_payload(contract_id: str, payout_option: str = "LIFE_ONLY",
                                 **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "payout_option": payout_option,
    }
    defaults.update(overrides)
    return defaults


def create_death_claim_payload(contract_id: str, date_of_death: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "date_of_death": date_of_death,
    }
    defaults.update(overrides)
    return defaults


def create_exchange_payload(direction: str, transfer_amount_cents: int,
                            cost_basis_cents: int, **overrides) -> dict:
    defaults = {
        "direction": direction,
        "transfer_amount_cents": transfer_amount_cents,
        "cost_basis_cents": cost_basis_cents,
    }
    defaults.update(overrides)
    return defaults
