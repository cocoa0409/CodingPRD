"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "DEAL_NAME": "Test Deal",
    "DEAL_TYPE": "SINGLE_TENANT",
    "TARGET_CLOSE_DATE": "2026-10-01T00:00:00Z",
    "EARNEST_MONEY_CENTS": 250000,
    "PURCHASE_PRICE_CENTS": 15000000,
    "LEGAL_NAME": "Test Tenant LLC",
    "CREDIT_RATING": "INVESTMENT_GRADE",
    "CREDIT_SCORE": 800,
    "ANNUAL_REVENUE_CENTS": 100000000,
    "ADDRESS": "1 Test St",
    "PROPERTY_TYPE": "RETAIL",
    "RENTABLE_SQFT": 5000,
    "YEAR_BUILT": 2010,
    "LEASE_TYPE": "NNN",
    "ANNUAL_BASE_RENT_CENTS": 1000000,
    "LEASE_COMMENCEMENT": "2020-01-01T00:00:00Z",
    "LEASE_EXPIRATION": "2036-01-01T00:00:00Z",
    "PSA_PRICE_CENTS": 15000000,
    "PSA_EARNEST_MONEY_CENTS": 250000,
    "DD_PERIOD_DAYS": 30,
    "FINANCING_CONTINGENCY_DAYS": 0,
    "TITLE_COMPANY": "Test Title Co",
    "TITLE_RECEIVED_AT": "2026-08-02T00:00:00Z",
    "LOAN_TYPE": "NEW_LOAN",
    "LOAN_AMOUNT_CENTS": 5000000,
    "INTEREST_RATE_BPS": 600,
    "AMORTIZATION_MONTHS": 0,
    "LENDER_NAME": "Test Bank",
}


def create_deal_payload(**overrides) -> dict:
    defaults = {
        "deal_name": DEFAULTS["DEAL_NAME"],
        "deal_type": DEFAULTS["DEAL_TYPE"],
        "target_close_date": DEFAULTS["TARGET_CLOSE_DATE"],
        "earnest_money_cents": DEFAULTS["EARNEST_MONEY_CENTS"],
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "credit_rating": DEFAULTS["CREDIT_RATING"],
        "credit_score": DEFAULTS["CREDIT_SCORE"],
        "annual_revenue_cents": DEFAULTS["ANNUAL_REVENUE_CENTS"],
        "is_guaranteed": True,
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = {
        "address": DEFAULTS["ADDRESS"],
        "property_type": DEFAULTS["PROPERTY_TYPE"],
        "rentable_sqft": DEFAULTS["RENTABLE_SQFT"],
        "year_built": DEFAULTS["YEAR_BUILT"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(tenant_id, **overrides) -> dict:
    defaults = {
        "tenant_id": tenant_id,
        "lease_type": DEFAULTS["LEASE_TYPE"],
        "annual_base_rent_cents": DEFAULTS["ANNUAL_BASE_RENT_CENTS"],
        "lease_commencement_date": DEFAULTS["LEASE_COMMENCEMENT"],
        "lease_expiration_date": DEFAULTS["LEASE_EXPIRATION"],
    }
    defaults.update(overrides)
    return defaults


def create_underwriting_model_payload(**overrides) -> dict:
    defaults = {"opex_allowance_variant": "CONSERVATIVE"}
    defaults.update(overrides)
    return defaults


def create_psa_payload(**overrides) -> dict:
    defaults = {
        "psa_price_cents": DEFAULTS["PSA_PRICE_CENTS"],
        "earnest_money_cents": DEFAULTS["PSA_EARNEST_MONEY_CENTS"],
        "dd_period_days": DEFAULTS["DD_PERIOD_DAYS"],
        "financing_contingency_days": DEFAULTS["FINANCING_CONTINGENCY_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_title_review_payload(**overrides) -> dict:
    defaults = {
        "title_company": DEFAULTS["TITLE_COMPANY"],
        "survey_type": "ALTA",
        "received_at": DEFAULTS["TITLE_RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_title_exception_payload(**overrides) -> dict:
    defaults = {
        "exception_code": "B2-100",
        "severity": "STANDARD",
        "description": "Test exception",
        "cure_cost_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_environmental_assessment_payload(**overrides) -> dict:
    defaults = {
        "phase": "PHASE_I",
        "recognized_environmental_condition": False,
        "reliance_letter_received": True,
    }
    defaults.update(overrides)
    return defaults


def create_pca_payload(**overrides) -> dict:
    defaults = {
        "immediate_repair_cost_cents": 100000,
        "capital_reserve_cents_per_sqft": 50,
        "condition_rating": "GOOD",
    }
    defaults.update(overrides)
    return defaults


def create_estoppel_payload(lease_id, tenant_id, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "tenant_id": tenant_id,
        "rent_confirmed_cents": DEFAULTS["ANNUAL_BASE_RENT_CENTS"],
        "default_confirmed": True,
    }
    defaults.update(overrides)
    return defaults


def create_snda_payload(lease_id, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "lender_name": DEFAULTS["LENDER_NAME"],
        "non_disturbance_confirmed": True,
    }
    defaults.update(overrides)
    return defaults


def create_financing_application_payload(**overrides) -> dict:
    defaults = {
        "loan_type": DEFAULTS["LOAN_TYPE"],
        "loan_amount_cents": DEFAULTS["LOAN_AMOUNT_CENTS"],
        "interest_rate_bps": DEFAULTS["INTEREST_RATE_BPS"],
        "amortization_months": DEFAULTS["AMORTIZATION_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def issue_statement_payload(closing_date, proration_inputs) -> dict:
    return {"closing_date": closing_date, "proration_inputs": proration_inputs}


def reissue_statement_payload(expected_deal_version, closing_date,
                              proration_inputs) -> dict:
    return {
        "expected_deal_version": expected_deal_version,
        "closing_date": closing_date,
        "proration_inputs": proration_inputs,
    }


def amend_psa_payload(expected_psa_version, psa_price_cents,
                      earnest_money_cents) -> dict:
    return {
        "expected_psa_version": expected_psa_version,
        "psa_price_cents": psa_price_cents,
        "earnest_money_cents": earnest_money_cents,
    }


def create_true_up_payload(**overrides) -> dict:
    defaults = {
        "line_type": "OTHER",
        "amount_cents": 1000,
        "reason": "Test adjustment",
    }
    defaults.update(overrides)
    return defaults


def proration_line(line_type, lease_id, annual_amount_cents, period_start,
                   period_end) -> dict:
    return {
        "line_type": line_type,
        "lease_id": lease_id,
        "annual_amount_cents": annual_amount_cents,
        "period_start": period_start,
        "period_end": period_end,
    }
