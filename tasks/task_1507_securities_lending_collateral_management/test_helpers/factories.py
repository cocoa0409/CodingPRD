"""Payload factories — one per creatable entity, input fields only."""

DEFAULTS = {
    "SECURITY_SYMBOL": "SEC1",
    "SECURITY_ASSET_CLASS": "EQUITY",
    "SECURITY_PRICE_CENTS": 1000,
    "OWNER_NAME": "Owner One",
    "REVENUE_SHARE_BPS": 6000,
    "INDEMNIFICATION_OPT_IN": False,
    "BORROWER_NAME": "Borrower One",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "QUANTITY_TOTAL": 100_000,
    "MIN_FEE_BPS": 25,
    "REQUEST_QUANTITY": 1000,
    "MAX_RATE_BPS": 40,
    "NEEDED_BY_DATE": "2026-08-20",
    "LOAN_QUANTITY": 1000,
    "LOAN_RATE_BPS": 25,
    "OVERRIDE_NEW_LIMIT_CENTS": 200_000_000,
    "OVERRIDE_EFFECTIVE_FROM": "2026-09-01",
    "OVERRIDE_EXPIRES_AT": "2026-10-01",
    "RECALL_REASON": "SALE",
    "RECALL_DEADLINE": "2026-08-10",
    "INSTRUMENT_TYPE": "MMF",
    "PRINCIPAL_CENTS": 100_000,
    "STATED_YIELD_BPS": 360,
    "REPORT_PERIOD": "2026-08",
    "REPORT_TYPE": "MONTHLY_LOAN_ACTIVITY",
}


def create_security_payload(**overrides) -> dict:
    defaults = {
        "symbol": DEFAULTS["SECURITY_SYMBOL"],
        "asset_class": DEFAULTS["SECURITY_ASSET_CLASS"],
        "price_cents": DEFAULTS["SECURITY_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_beneficial_owner_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["OWNER_NAME"],
        "revenue_share_bps": DEFAULTS["REVENUE_SHARE_BPS"],
        "indemnification_opt_in": DEFAULTS["INDEMNIFICATION_OPT_IN"],
    }
    defaults.update(overrides)
    return defaults


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["BORROWER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lendable_position_payload(owner_id, security_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "security_id": security_id,
        "quantity_total": DEFAULTS["QUANTITY_TOTAL"],
        "min_fee_bps": DEFAULTS["MIN_FEE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_borrow_request_payload(borrower_id, security_id, **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "security_id": security_id,
        "quantity": DEFAULTS["REQUEST_QUANTITY"],
        "max_rate_bps": DEFAULTS["MAX_RATE_BPS"],
        "collateral_type": "SECURITIES",
        "needed_by_date": DEFAULTS["NEEDED_BY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(owner_id, borrower_id, security_id, position_id,
                        **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "borrower_id": borrower_id,
        "security_id": security_id,
        "position_id": position_id,
        "quantity": DEFAULTS["LOAN_QUANTITY"],
        "collateral_type": "SECURITIES",
        "rate_bps": DEFAULTS["LOAN_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_limit_override_payload(**overrides) -> dict:
    defaults = {
        "new_limit_cents": DEFAULTS["OVERRIDE_NEW_LIMIT_CENTS"],
        "effective_from": DEFAULTS["OVERRIDE_EFFECTIVE_FROM"],
        "expires_at": DEFAULTS["OVERRIDE_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_cash_pledge_payload(amount_cents, **overrides) -> dict:
    defaults = {"pledge_type": "CASH", "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_security_pledge_payload(pledge_security_id, quantity,
                                   **overrides) -> dict:
    defaults = {
        "pledge_type": "SECURITY",
        "pledge_security_id": pledge_security_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(quantity, **overrides) -> dict:
    defaults = {
        "quantity": quantity,
        "reason": DEFAULTS["RECALL_REASON"],
        "deadline_date": DEFAULTS["RECALL_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_reinvestment_payload(**overrides) -> dict:
    defaults = {
        "instrument_type": DEFAULTS["INSTRUMENT_TYPE"],
        "principal_cents": DEFAULTS["PRINCIPAL_CENTS"],
        "stated_yield_bps": DEFAULTS["STATED_YIELD_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_report_payload(**overrides) -> dict:
    defaults = {
        "period": DEFAULTS["REPORT_PERIOD"],
        "report_type": DEFAULTS["REPORT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_month_end_close_payload(**overrides) -> dict:
    defaults = {"period": DEFAULTS["REPORT_PERIOD"]}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
