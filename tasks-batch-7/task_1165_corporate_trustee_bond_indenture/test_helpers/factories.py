"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS


def create_indenture_payload(**overrides) -> dict:
    defaults = {
        "name": "I1",
        "issuer_ref": "issuer-1",
        "governing_law": TEST_DEFAULTS["GOVERNING_LAW"],
        "initial_trustee_ref": TEST_DEFAULTS["INITIAL_TRUSTEE_REF"],
        "annual_admin_fee_cents": TEST_DEFAULTS["ANNUAL_ADMIN_FEE_CENTS"],
        "extraordinary_hourly_rate_cents": TEST_DEFAULTS["EXTRAORDINARY_HOURLY_RATE_CENTS"],
        "default_hourly_rate_cents": TEST_DEFAULTS["DEFAULT_HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_tranche_payload(indenture_id: str, **overrides) -> dict:
    defaults = {
        "indenture_id": indenture_id,
        "series_code": "T1",
        "original_principal_cents": 400000000,
        "interest_rate_bps": TEST_DEFAULTS["INTEREST_RATE_BPS"],
        "day_count_convention": "ACT_360",
        "payment_frequency": "SEMI_ANNUAL",
        "maturity_date": TEST_DEFAULTS["MATURITY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_noteholder_account_payload(**overrides) -> dict:
    defaults = {
        "holder_ref": "H-A",
        "legal_name": "Holder A",
        "contact_email": "a@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(tranche_id: str, noteholder_account_id: str,
                            original_principal_cents: int, **overrides) -> dict:
    defaults = {
        "tranche_id": tranche_id,
        "noteholder_account_id": noteholder_account_id,
        "original_principal_cents": original_principal_cents,
    }
    defaults.update(overrides)
    return defaults


def create_covenant_obligation_payload(indenture_id: str, **overrides) -> dict:
    defaults = {
        "indenture_id": indenture_id,
        "covenant_type": "FINANCIAL_REPORT",
        "frequency": "QUARTERLY",
        "period_anchor_date": "2026-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_covenant_certificate_payload(covenant_obligation_id: str, **overrides) -> dict:
    defaults = {
        "covenant_obligation_id": covenant_obligation_id,
        "period_end_date": "2026-06-30",
        "document_ref": "doc-1",
    }
    defaults.update(overrides)
    return defaults


def create_interest_run_payload(tranche_id: str, **overrides) -> dict:
    defaults = {
        "tranche_id": tranche_id,
        "payment_type": "INTEREST",
        "period_start_date": TEST_DEFAULTS["INTEREST_PERIOD_START"],
        "period_end_date": TEST_DEFAULTS["INTEREST_PERIOD_END"],
        "scheduled_payment_date": TEST_DEFAULTS["INTEREST_PAYMENT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_redemption_run_payload(tranche_id: str, target_amount_cents: int,
                                  payment_type: str = "SINKING_FUND_REDEMPTION",
                                  **overrides) -> dict:
    defaults = {
        "tranche_id": tranche_id,
        "payment_type": payment_type,
        "scheduled_payment_date": "2026-06-15",
        "target_amount_cents": target_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_default_case_payload(indenture_id: str, **overrides) -> dict:
    defaults = {
        "indenture_id": indenture_id,
        "default_type": "PAYMENT",
        "cure_deadline": TEST_DEFAULTS["CURE_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_direction_payload(default_case_id: str, expected_default_case_version: int,
                             **overrides) -> dict:
    defaults = {
        "default_case_id": default_case_id,
        "instruction_type": "ACCELERATE",
        "expires_at": TEST_DEFAULTS["DIRECTION_EXPIRY"],
        "expected_default_case_version": expected_default_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(noteholder_account_id: str, **overrides) -> dict:
    defaults = {"noteholder_account_id": noteholder_account_id}
    defaults.update(overrides)
    return defaults


def create_consent_solicitation_payload(indenture_id: str, **overrides) -> dict:
    defaults = {
        "indenture_id": indenture_id,
        "subject_type": "AMEND_TERMS",
        "amendment_payload": {"annual_admin_fee_cents": 2600000},
        "consent_threshold_bps": 5000,
        "tabulation_basis": "CURRENT_OUTSTANDING",
        "record_date": "2026-06-01",
        "expiry_date": "2026-07-01",
    }
    defaults.update(overrides)
    return defaults


def create_ballot_payload(noteholder_account_id: str, vote: str = "CONSENT", **overrides) -> dict:
    defaults = {"noteholder_account_id": noteholder_account_id, "vote": vote}
    defaults.update(overrides)
    return defaults


def create_collateral_item_payload(indenture_id: str, **overrides) -> dict:
    defaults = {
        "indenture_id": indenture_id,
        "description": "Collateral item",
        "collateral_type": "REAL_ESTATE",
        "appraised_value_cents": 500000000,
        "valuation_date": "2026-04-01",
    }
    defaults.update(overrides)
    return defaults


def create_release_request_payload(collateral_item_id: str,
                                   expected_collateral_item_version: int,
                                   **overrides) -> dict:
    defaults = {
        "collateral_item_id": collateral_item_id,
        "request_type": "RELEASE",
        "expected_collateral_item_version": expected_collateral_item_version,
    }
    defaults.update(overrides)
    return defaults


def create_substitution_request_payload(collateral_item_id: str,
                                        expected_collateral_item_version: int,
                                        **overrides) -> dict:
    defaults = {
        "collateral_item_id": collateral_item_id,
        "request_type": "SUBSTITUTION",
        "substitute_description": "substitute securities",
        "substitute_collateral_type": "SECURITIES",
        "substitute_appraised_value_cents": 470000000,
        "substitute_valuation_date": "2026-04-15",
        "expected_collateral_item_version": expected_collateral_item_version,
    }
    defaults.update(overrides)
    return defaults


def create_fee_invoice_payload(indenture_id: str, **overrides) -> dict:
    defaults = {
        "indenture_id": indenture_id,
        "invoice_type": "ANNUAL_ADMIN",
        "service_period_start": "2026-01-01",
        "service_period_end": "2026-12-31",
        "description": "annual",
    }
    defaults.update(overrides)
    return defaults


def create_extraordinary_invoice_payload(indenture_id: str, hours: float, **overrides) -> dict:
    defaults = {
        "indenture_id": indenture_id,
        "invoice_type": "EXTRAORDINARY_SERVICE",
        "service_period_start": "2026-05-01",
        "service_period_end": "2026-05-31",
        "extraordinary_hours": hours,
        "description": "extraordinary service",
    }
    defaults.update(overrides)
    return defaults


def create_trustee_appointment_payload(indenture_id: str, expected_indenture_version: int,
                                       **overrides) -> dict:
    defaults = {
        "indenture_id": indenture_id,
        "incoming_trustee_ref": "trustee-beta",
        "reason": "RESIGNATION",
        "proposed_effective_date": "2026-09-01",
        "expected_indenture_version": expected_indenture_version,
    }
    defaults.update(overrides)
    return defaults
