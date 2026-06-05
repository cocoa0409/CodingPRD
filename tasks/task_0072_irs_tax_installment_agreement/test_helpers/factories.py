"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TAXPAYER_NAME": "Test Taxpayer LLC",
    "FILING_STATUS": "BUSINESS",
    "MDI_CENTS": 300000,
    "TAX_YEAR": 2023,
    "ASSESSED_TAX_CENTS": 1000000,
    "ASSESSMENT_DATE": "2024-01-15T00:00:00.000Z",
    "ACTIVE_FROM": "2024-04-15T00:00:00.000Z",
    "ACTIVE_TO": "2024-10-15T00:00:00.000Z",
}

# A monotonically increasing TIN source so each created account is unique
# within a single (per-test) server process.
_tin_counter = [300000000]


def fresh_tin() -> str:
    _tin_counter[0] += 1
    return str(_tin_counter[0])


def create_tax_account_payload(**overrides) -> dict:
    defaults = {
        "taxpayer_name": DEFAULTS["TAXPAYER_NAME"],
        "tin": fresh_tin(),
        "filing_status": DEFAULTS["FILING_STATUS"],
        "monthly_disposable_income_cents": DEFAULTS["MDI_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_tax_period_payload(tax_account_id: str, **overrides) -> dict:
    defaults = {
        "tax_account_id": tax_account_id,
        "tax_year": DEFAULTS["TAX_YEAR"],
        "assessed_tax_cents": DEFAULTS["ASSESSED_TAX_CENTS"],
        "assessment_date": DEFAULTS["ASSESSMENT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_csed_suspension_payload(tax_period_id: str, **overrides) -> dict:
    defaults = {
        "tax_period_id": tax_period_id,
        "reason": "MANUAL",
        "start_at": DEFAULTS["ACTIVE_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(tax_account_id: str, **overrides) -> dict:
    defaults = {
        "tax_account_id": tax_account_id,
        "agreement_type": "LONG_TERM",
        "payment_method": "MANUAL",
        "monthly_payment_cents": 200000,
        "term_months": 6,
        "active_from": DEFAULTS["ACTIVE_FROM"],
        "active_to": DEFAULTS["ACTIVE_TO"],
        "low_income_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(tax_account_id: str, amount_cents: int,
                           payment_source: str = "MANUAL", **overrides) -> dict:
    defaults = {
        "tax_account_id": tax_account_id,
        "amount_cents": amount_cents,
        "payment_source": payment_source,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(tax_account_id: str, offer_amount_cents: int,
                         net_realizable_equity_cents: int = 500000, **overrides) -> dict:
    defaults = {
        "tax_account_id": tax_account_id,
        "offer_amount_cents": offer_amount_cents,
        "net_realizable_equity_cents": net_realizable_equity_cents,
    }
    defaults.update(overrides)
    return defaults


def create_lien_payload(tax_account_id: str, filed_amount_cents: int = 1000000, **overrides) -> dict:
    defaults = {
        "tax_account_id": tax_account_id,
        "filed_amount_cents": filed_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_cnc_payload(tax_account_id: str, hardship_reason: str = "NO_DISPOSABLE_INCOME", **overrides) -> dict:
    defaults = {
        "tax_account_id": tax_account_id,
        "hardship_reason": hardship_reason,
    }
    defaults.update(overrides)
    return defaults


def create_account_event_payload(tax_account_id: str, event_type: str, **overrides) -> dict:
    defaults = {
        "tax_account_id": tax_account_id,
        "event_type": event_type,
    }
    defaults.update(overrides)
    return defaults
