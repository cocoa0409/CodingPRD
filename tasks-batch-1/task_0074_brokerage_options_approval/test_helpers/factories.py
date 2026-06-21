"""Payload factories — one per entity, input fields only."""

DEFAULT_TRADE_DATE = "2026-06-01"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_holder_user_id": "h_a",
        "legal_name": "A Holder",
        "tax_id": "111-11-1111",
        "date_of_birth": "1980-01-01",
        "w9_certified": True,
        "liquid_net_worth_cents": 30_000_000,
        "annual_income_cents": 30_000_000,
        "investment_experience": "GOOD",
        "cash_balance_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_options_approval_payload(account_id, requested_level, **overrides) -> dict:
    defaults = {"account_id": account_id, "requested_level": requested_level}
    defaults.update(overrides)
    return defaults


def create_margin_upgrade_payload(account_id, requested_margin_type, **overrides) -> dict:
    defaults = {"account_id": account_id, "requested_margin_type": requested_margin_type}
    defaults.update(overrides)
    return defaults


def create_position_payload(account_id, symbol="ACME", instrument_type="EQUITY",
                            quantity=10, market_value_cents=1_000_000, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "symbol": symbol,
        "instrument_type": instrument_type,
        "quantity": quantity,
        "market_value_cents": market_value_cents,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(account_id, symbol="ACME", instrument_type="EQUITY",
                         side="BUY", order_type="LIMIT", quantity=1,
                         trade_date=DEFAULT_TRADE_DATE, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "symbol": symbol,
        "instrument_type": instrument_type,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
        "trade_date": trade_date,
    }
    defaults.update(overrides)
    return defaults


def create_acat_transfer_payload(account_id, direction="IN", counterparty_dtc="0226",
                                 transfer_value_cents=500_000, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "direction": direction,
        "counterparty_dtc": counterparty_dtc,
        "transfer_value_cents": transfer_value_cents,
    }
    defaults.update(overrides)
    return defaults
