"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "SERVICE_ADDRESS": "1 Test Way",
    "HOUSEHOLD_SIZE": 1,
    "GROSS_ANNUAL_INCOME_CENTS": 500_000,
    "CURRENT_MONTH_INCOME_CENTS": 40_000,
    "INSTALLMENT_COUNT": 4,
    "TENDER_TYPE": "CASH",
    "PHYSICIAN_NAME": "Dr. Test",
    "PHYSICIAN_LICENSE_NUMBER": "L-TEST",
    "CONDITION_CLASS": "SERIOUS",
    "AGENCY_CODE": "COMM_ACTION",
    "FUND_NAME": "Test Fund 2026",
    "FUNDER_TYPE": "STATE_GRANT",
    "FISCAL_YEAR": 2026,
    "PRIORITY_RANK": 1,
}


def create_account_payload(**overrides) -> dict:
    defaults = {"service_address": DEFAULTS["SERVICE_ADDRESS"]}
    defaults.update(overrides)
    return defaults


def create_charge_payload(account_id=None, **overrides) -> dict:
    defaults = {"charge_type": "ARREARAGE", "amount_cents": 10_000,
                "effective_on": "2026-08-01"}
    defaults.update(overrides)
    return defaults


def create_application_payload(account_id, expected_account_version, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
        "gross_annual_income_cents": DEFAULTS["GROSS_ANNUAL_INCOME_CENTS"],
        "current_month_income_cents": DEFAULTS["CURRENT_MONTH_INCOME_CENTS"],
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_dpa_payload(account_id, expected_account_version, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "installment_count": DEFAULTS["INSTALLMENT_COUNT"],
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(account_id, amount_cents, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "tender_type": DEFAULTS["TENDER_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(account_id, effective_from, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "physician_name": DEFAULTS["PHYSICIAN_NAME"],
        "physician_license_number": DEFAULTS["PHYSICIAN_LICENSE_NUMBER"],
        "condition_class": DEFAULTS["CONDITION_CLASS"],
        "effective_from": effective_from,
    }
    defaults.update(overrides)
    return defaults


def create_shutoff_order_payload(account_id, scheduled_date, **overrides) -> dict:
    defaults = {"account_id": account_id, "scheduled_date": scheduled_date}
    defaults.update(overrides)
    return defaults


def create_funding_source_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FUND_NAME"],
        "funder_type": DEFAULTS["FUNDER_TYPE"],
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "appropriated_cents": 100_000,
        "priority_rank": DEFAULTS["PRIORITY_RANK"],
        "eligible_tiers": ["TIER_1", "TIER_2", "TIER_3"],
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(account_id, **overrides) -> dict:
    defaults = {"account_id": account_id, "agency_code": DEFAULTS["AGENCY_CODE"]}
    defaults.update(overrides)
    return defaults
