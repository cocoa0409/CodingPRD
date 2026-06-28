"""Payload factories — one per entity, input fields only."""


DEFAULTS = {
    "EMAIL": "borrower@example.com",
    "FULL_NAME": "Test Borrower",
    "STATE_CODE": "CA",
    "APR_BPS": 0,
    "ADMIN_FEE_CENTS": 0,
    "PRINCIPAL_CENTS": 60000,
    "TERM_MONTHS": 12,
    "DEPOSIT_CENTS": 50000,
    "AUTOPAY_DAY": 5,
    "PAYMENT_AMOUNT_CENTS": 5000,
}

_email_counter = [0]


def unique_email(prefix="acct") -> str:
    """Produce a unique email per call so account creation never collides."""
    _email_counter[0] += 1
    return f"{prefix}-{_email_counter[0]}@example.com"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": DEFAULTS["FULL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(**overrides) -> dict:
    defaults = {
        "product_kind": "LOAN",
        "apr_bps": DEFAULTS["APR_BPS"],
        "admin_fee_cents": DEFAULTS["ADMIN_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(account_id, disclosure_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "disclosure_id": disclosure_id,
        "principal_cents": DEFAULTS["PRINCIPAL_CENTS"],
        "term_months": DEFAULTS["TERM_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(loan_id, expected_loan_version, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "amount_cents": DEFAULTS["PAYMENT_AMOUNT_CENTS"],
        "source": "MANUAL",
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_secured_card_payload(account_id, disclosure_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "disclosure_id": disclosure_id,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(amount_cents, expected_card_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_card_version": expected_card_version,
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_autopay_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "day_of_month": DEFAULTS["AUTOPAY_DAY"],
    }
    defaults.update(overrides)
    return defaults
