"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ACCOUNTHOLDER_NAME": "Test Holder",
    "ACCOUNTHOLDER_EMAIL": "test.holder@x.com",
    "ACCOUNTHOLDER_DOB": "1980-01-01",
    "EMPLOYER_NAME": "Test Employer",
    "PLAN_YEAR": 2026,
    "MERCHANT": "Test Clinic",
    "SERVICE_DATE": "2026-02-01T00:00:00Z",
    "LAST_FOUR": "4242",
}


def create_accountholder_payload(**overrides) -> dict:
    """Accountholder input fields: full_name, email, date_of_birth."""
    defaults = {
        "full_name": DEFAULTS["ACCOUNTHOLDER_NAME"],
        "email": DEFAULTS["ACCOUNTHOLDER_EMAIL"],
        "date_of_birth": DEFAULTS["ACCOUNTHOLDER_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_employer_payload(**overrides) -> dict:
    """Employer input fields: name, optional payroll_contributions_enabled."""
    defaults = {"name": DEFAULTS["EMPLOYER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_payroll_period_payload(period_start_day, period_end_day, **overrides) -> dict:
    """PayrollPeriod input fields: period_start_day, period_end_day."""
    defaults = {
        "period_start_day": period_start_day,
        "period_end_day": period_end_day,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(accountholder_id, **overrides) -> dict:
    """HsaAccount input fields: accountholder_id, plan_year, optional employer_id,
    invest_threshold_cents, sweep_increment_cents."""
    defaults = {
        "accountholder_id": accountholder_id,
        "plan_year": DEFAULTS["PLAN_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_coverage_period_payload(coverage_tier, effective_month, end_month,
                                   **overrides) -> dict:
    """CoveragePeriod input fields: coverage_tier, effective_month, end_month."""
    defaults = {
        "coverage_tier": coverage_tier,
        "effective_month": effective_month,
        "end_month": end_month,
    }
    defaults.update(overrides)
    return defaults


def create_contribution_payload(channel, amount_cents, **overrides) -> dict:
    """Contribution input fields: channel, amount_cents, optional contribution_kind."""
    defaults = {
        "channel": channel,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_sweep_payload(expected_account_version, **overrides) -> dict:
    """InvestmentSweep input fields: expected_account_version, optional
    requested_amount_cents."""
    defaults = {"expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults


def create_card_payload(**overrides) -> dict:
    """DebitCard input fields: last_four."""
    defaults = {"last_four": DEFAULTS["LAST_FOUR"]}
    defaults.update(overrides)
    return defaults


def create_receipt_payload(account_id, amount_cents, is_qualified_medical,
                           **overrides) -> dict:
    """Receipt input fields: account_id, merchant, service_date, amount_cents,
    is_qualified_medical."""
    defaults = {
        "account_id": account_id,
        "merchant": DEFAULTS["MERCHANT"],
        "service_date": DEFAULTS["SERVICE_DATE"],
        "amount_cents": amount_cents,
        "is_qualified_medical": is_qualified_medical,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(method, amount_cents, **overrides) -> dict:
    """Distribution input fields: method, amount_cents, optional card_id."""
    defaults = {
        "method": method,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_correction_payload(requested_amount_cents, expected_account_version,
                              **overrides) -> dict:
    """ExcessCorrection input fields: requested_amount_cents, expected_account_version."""
    defaults = {
        "requested_amount_cents": requested_amount_cents,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_tax_form_payload(form_type, tax_year, **overrides) -> dict:
    """TaxForm input fields: form_type, tax_year."""
    defaults = {
        "form_type": form_type,
        "tax_year": tax_year,
    }
    defaults.update(overrides)
    return defaults
