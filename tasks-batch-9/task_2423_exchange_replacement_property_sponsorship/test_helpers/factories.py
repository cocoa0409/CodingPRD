"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_property_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PROPERTY_NAME"],
        "state_code": TEST_DEFAULTS["PROPERTY_STATE_CODE"],
        "asset_type": TEST_DEFAULTS["PROPERTY_ASSET_TYPE"],
        "purchase_price_cents": TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
        "appraised_value_cents": TEST_DEFAULTS["APPRAISED_VALUE_CENTS"],
        "annual_noi_cents": TEST_DEFAULTS["ANNUAL_NOI_CENTS"],
        "occupancy_rate": TEST_DEFAULTS["OCCUPANCY_RATE"],
        "contract_close_deadline": TEST_DEFAULTS["CONTRACT_CLOSE_DEADLINE"],
    }
    payload.update(overrides)
    return payload


def create_trust_payload(property_id: str, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "trust_name": TEST_DEFAULTS["TRUST_NAME"],
        "total_units": TEST_DEFAULTS["TOTAL_UNITS"],
        "reserve_floor_cents": TEST_DEFAULTS["RESERVE_FLOOR_CENTS"],
        "reserve_target_pct": TEST_DEFAULTS["RESERVE_TARGET_PCT"],
    }
    payload.update(overrides)
    return payload


def create_offering_payload(trust_id: str, **overrides) -> dict:
    payload = {
        "trust_id": trust_id,
        "exemption_rule": "RULE_506B",
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
        "min_units_per_investor": TEST_DEFAULTS["MIN_UNITS_PER_INVESTOR"],
        "load_pct": TEST_DEFAULTS["LOAD_PCT"],
        "closing_costs_cents": TEST_DEFAULTS["CLOSING_COSTS_CENTS"],
        "reserve_funding_pct": TEST_DEFAULTS["RESERVE_FUNDING_PCT"],
        "rescission_window_days": TEST_DEFAULTS["RESCISSION_WINDOW_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_loan_facility_payload(trust_id: str, **overrides) -> dict:
    payload = {
        "trust_id": trust_id,
        "lender_name": TEST_DEFAULTS["LOAN_LENDER_NAME"],
        "principal_cents": TEST_DEFAULTS["LOAN_PRINCIPAL_CENTS"],
        "rate_bps": TEST_DEFAULTS["LOAN_RATE_BPS"],
        "recourse_type": "NON_RECOURSE",
        "maturity_on": TEST_DEFAULTS["LOAN_MATURITY_ON"],
    }
    payload.update(overrides)
    return payload


def reprice_loan_payload(**overrides) -> dict:
    payload = {
        "principal_cents": 750_000_000,
        "rate_bps": 450,
        "recourse_type": "NON_RECOURSE",
    }
    payload.update(overrides)
    return payload


def create_master_lease_payload(trust_id: str, **overrides) -> dict:
    payload = {
        "trust_id": trust_id,
        "master_tenant_user_id": TEST_DEFAULTS["MASTER_TENANT_USER_ID"],
        "term_start_on": TEST_DEFAULTS["LEASE_TERM_START_ON"],
        "term_end_on": TEST_DEFAULTS["LEASE_TERM_END_ON"],
        "base_rent_annual_cents": TEST_DEFAULTS["LEASE_BASE_RENT_ANNUAL_CENTS"],
        "supplemental_rent_annual_cents": TEST_DEFAULTS[
            "LEASE_SUPPLEMENTAL_RENT_ANNUAL_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


def create_investor_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Alice Adams",
        "entity_type": "INDIVIDUAL",
        "accreditation_method": "SELF_CERT_NET_WORTH",
        "annual_income_cents": 90_000_000,
        "net_worth_cents": 2_000_000_000,
        "liquid_net_worth_cents": 1_600_000_000,
    }
    payload.update(overrides)
    return payload


def create_exchange_file_payload(investor_id: str, **overrides) -> dict:
    payload = {
        "investor_id": investor_id,
        "qi_reference": "QI-A-2026",
        "relinquished_closed_on": "2026-08-05T00:00:00.000Z",
        "relinquished_sale_price_cents": 400_000_000,
        "net_proceeds_cents": 250_000_000,
        "debt_retired_cents": 100_000_000,
        "identification_rule": "THREE_PROPERTY",
        "boot_tolerance_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_identification_payload(
    exchange_file_id: str, property_id: str, **overrides
) -> dict:
    payload = {
        "exchange_file_id": exchange_file_id,
        "property_id": property_id,
        "fair_market_value_cents": TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(
    offering_id: str,
    investor_id: str,
    exchange_file_id: str,
    units_requested: int,
    expected_offering_version: int,
    **overrides,
) -> dict:
    payload = {
        "offering_id": offering_id,
        "investor_id": investor_id,
        "exchange_file_id": exchange_file_id,
        "units_requested": units_requested,
        "expected_offering_version": expected_offering_version,
    }
    payload.update(overrides)
    return payload


def create_capital_need_payload(trust_id: str, **overrides) -> dict:
    payload = {
        "trust_id": trust_id,
        "need_type": "NORMAL_REPAIR",
        "amount_cents": 25_000_000,
        "needed_by": "2027-01-31T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_distribution_payload(
    trust_id: str, expected_trust_version: int, **overrides
) -> dict:
    payload = {
        "trust_id": trust_id,
        "kind": "OPERATING",
        "period_start": "2026-10-01T00:00:00.000Z",
        "period_end": "2027-01-01T00:00:00.000Z",
        "expected_trust_version": expected_trust_version,
    }
    payload.update(overrides)
    return payload


def create_tax_statement_payload(
    trust_id: str, subscription_id: str, **overrides
) -> dict:
    payload = {
        "trust_id": trust_id,
        "subscription_id": subscription_id,
        "tax_year": 2026,
        "allocation_variant": "UNITS_AT_YEAR_END",
    }
    payload.update(overrides)
    return payload


def create_exit_event_payload(trust_id: str, **overrides) -> dict:
    payload = {
        "trust_id": trust_id,
        "exit_mode": "ASSET_SALE",
        "gross_price_cents": 1_450_000_000,
        "selling_costs_cents": 36_250_000,
        "consent_threshold_pct": 0.51,
        "expected_close_on": "2027-03-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_exit_consent_payload(
    exit_event_id: str, subscription_id: str, **overrides
) -> dict:
    payload = {
        "exit_event_id": exit_event_id,
        "subscription_id": subscription_id,
        "decision": "CONSENT",
    }
    payload.update(overrides)
    return payload


def rent_posting_payload(**overrides) -> dict:
    payload = {"rent_kind": "BASE", "amount_cents": 22_500_000}
    payload.update(overrides)
    return payload


def debt_service_payment_payload(**overrides) -> dict:
    payload = {"amount_cents": 7_650_000}
    payload.update(overrides)
    return payload
