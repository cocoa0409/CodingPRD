"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

DEFAULTS = {
    "CUSTODIAN_NAME": "CUSTO",
    "TICKER": "ACME",
    "ASSET_CLASS": "EQUITY",
    "LOT_SIZE": 1,
    "REFERENCE_PRICE_CENTS": 1000,
    "BROKER_CODE": "BRK1",
    "COMMISSION_RATE_BP": 50,
    "BUDGET_PERIOD_START": "2026-01-01",
    "BUDGET_PERIOD_END": "2027-01-01",
    "BUDGET_AMOUNT_CENTS": 100000,
    "ORDER_QTY": 100,
    "FILL_PRICE_CENTS": 1000,
    "FILL_EXECUTED_AT": "2026-08-01T09:00:00Z",
    "RESTRICTION_EFFECTIVE_FROM": "2026-07-01T00:00:00Z",
    "RESTRICTION_EFFECTIVE_TO": "2026-12-31T23:59:59Z",
}


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_code": "A1",
        "display_name": "Account A1",
        "account_type": "DISCRETIONARY",
        "custodian_name": DEFAULTS["CUSTODIAN_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_security_payload(**overrides) -> dict:
    defaults = {
        "ticker": DEFAULTS["TICKER"],
        "asset_class": DEFAULTS["ASSET_CLASS"],
        "lot_size": DEFAULTS["LOT_SIZE"],
        "reference_price_cents": DEFAULTS["REFERENCE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_broker_payload(**overrides) -> dict:
    defaults = {
        "broker_code": DEFAULTS["BROKER_CODE"],
        "display_name": "Broker One",
        "commission_rate_bp": DEFAULTS["COMMISSION_RATE_BP"],
        "supported_asset_classes": ["EQUITY", "FIXED_INCOME"],
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["BUDGET_PERIOD_START"],
        "period_end": DEFAULTS["BUDGET_PERIOD_END"],
        "budget_amount_cents": DEFAULTS["BUDGET_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_restriction_payload(**overrides) -> dict:
    defaults = {
        "rule_type": "PROHIBITED",
        "side": "BUY",
        "effective_from": DEFAULTS["RESTRICTION_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["RESTRICTION_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(account_id, security_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "security_id": security_id,
        "side": "BUY",
        "order_qty": DEFAULTS["ORDER_QTY"],
        "order_type": "MARKET",
    }
    defaults.update(overrides)
    return defaults


def create_block_payload(security_id, **overrides) -> dict:
    defaults = {"security_id": security_id, "side": "BUY"}
    defaults.update(overrides)
    return defaults


def create_fill_payload(**overrides) -> dict:
    defaults = {
        "fill_qty": DEFAULTS["ORDER_QTY"],
        "fill_price_cents": DEFAULTS["FILL_PRICE_CENTS"],
        "executed_at": DEFAULTS["FILL_EXECUTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(method, expected_block_version, **overrides) -> dict:
    defaults = {"method": method, "expected_block_version": expected_block_version}
    defaults.update(overrides)
    return defaults


def create_flag_payload(error_type, **overrides) -> dict:
    defaults = {"error_type": error_type}
    defaults.update(overrides)
    return defaults


def create_fail_payload(fail_reason, **overrides) -> dict:
    defaults = {"fail_reason": fail_reason}
    defaults.update(overrides)
    return defaults


def create_status_payload(to_status) -> dict:
    return {"to_status": to_status}


def create_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
