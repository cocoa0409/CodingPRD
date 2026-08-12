"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LEGAL_NAME": "Test Client",
    "DATE_OF_BIRTH": "1970-01-01",
    "COUNTY": "TRV",
    "MONTHLY_BENEFIT": 80000,
    "EFFECTIVE_START": "2026-01-01",
    "BOND_COVERAGE": 5000000,
    "BOND_START": "2026-01-01",
    "BOND_END": "2027-01-01",
    "PREMIUM_PAID_THROUGH": "2026-12-31",
    "PERIOD_MONTH": "2026-06",
    "SOURCE_BENEFIT": 100000,
    "RECEIVED_DATE": "2026-06-02",
    "SCHEDULED_RELEASE_DATE": "2026-06-10",
}

_bank_ref_counter = [0]
_case_number_counter = [0]
_ssn_counter = [0]


def _next_bank_ref() -> str:
    _bank_ref_counter[0] += 1
    return f"BA-T-{_bank_ref_counter[0]:05d}"


def _next_case_number() -> str:
    _case_number_counter[0] += 1
    return f"CV-2026-{_case_number_counter[0]:05d}"


def _next_ssn4() -> str:
    _ssn_counter[0] += 1
    return f"{_ssn_counter[0] % 10000:04d}"


def create_client_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
        "ssn_last4": _next_ssn4(),
        "county_of_residence": DEFAULTS["COUNTY"],
        "medicaid_enrolled": False,
    }
    defaults.update(overrides)
    return defaults


def create_entitlement_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "claim_type": "SSI",
        "monthly_benefit_cents": DEFAULTS["MONTHLY_BENEFIT"],
        "effective_start_date": DEFAULTS["EFFECTIVE_START"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_trust_account_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "account_type": "OPERATING",
        "bank_account_ref": _next_bank_ref(),
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_budget_plan_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "period_month": DEFAULTS["PERIOD_MONTH"],
        "source_benefit_cents": DEFAULTS["SOURCE_BENEFIT"],
        "lines": [{"category": "HOUSING", "percent": 100}],
        "expected_client_version": None,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "account_id": None,
        "budget_plan_id": None,
        "payee_name": "Test Payee",
        "category": "HOUSING",
        "amount_cents": 10000,
        "scheduled_release_date": DEFAULTS["SCHEDULED_RELEASE_DATE"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_deposit_payload(**overrides) -> dict:
    defaults = {
        "account_id": None,
        "source": "OTHER",
        "amount_cents": 10000,
        "received_date": DEFAULTS["RECEIVED_DATE"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_court_order_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "order_type": "RESTRICTED_WITHDRAWAL",
        "amount_limit_cents": 50000,
        "petitioned_date": "2026-06-01",
        "expiry_date": "2026-12-31",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_surety_bond_payload(**overrides) -> dict:
    defaults = {
        "coverage_amount_cents": DEFAULTS["BOND_COVERAGE"],
        "coverage_start_date": DEFAULTS["BOND_START"],
        "coverage_end_date": DEFAULTS["BOND_END"],
        "premium_paid_through_date": DEFAULTS["PREMIUM_PAID_THROUGH"],
    }
    defaults.update(overrides)
    return defaults


def create_accounting_report_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "report_type": "SSA_6233",
        "period_start_date": "2026-05-01",
        "period_end_date": "2026-05-31",
        "basis": "CASH",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_spend_down_plan_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "target_month": DEFAULTS["PERIOD_MONTH"],
        "entries": [{"category": "MEDICAL", "planned_amount_cents": 1000}],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_audit_case_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "authority": "SSA",
        "scope": "CLIENT_ACCOUNT",
        "period_start_date": "2026-01-01",
        "period_end_date": "2026-05-31",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_conservator_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "full_name": "Court Conservator",
        "court_case_number": _next_case_number(),
        "authority_scope": "EXCLUSIVE",
        "appointed_date": "2026-01-10",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}
