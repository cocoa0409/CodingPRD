"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TOTAL_COMMISSION_PCT": 0.06,
    "COOP_SPLIT_PCT": 0.50,
    "LIST_PRICE_CENTS": 50_000_000,
    "MAX_BUDGET_CENTS": 60_000_000,
    "MONTHLY_INCOME_CENTS": 2_000_000,
}

_LICENSE_COUNTER = [0]
_SERIAL_COUNTER = [0]
_ADDRESS_COUNTER = [0]


def unique_license_no(prefix: str = "LIC") -> str:
    _LICENSE_COUNTER[0] += 1
    return f"{prefix}-{_LICENSE_COUNTER[0]:06d}"


def unique_serial_no(prefix: str = "LB") -> str:
    _SERIAL_COUNTER[0] += 1
    return f"{prefix}-{_SERIAL_COUNTER[0]:06d}"


def unique_address(prefix: str = "Test St") -> str:
    _ADDRESS_COUNTER[0] += 1
    return f"{_ADDRESS_COUNTER[0]} {prefix}"


def create_brokerage_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Realty",
        "default_total_commission_pct": DEFAULTS["TOTAL_COMMISSION_PCT"],
        "default_coop_split_pct": DEFAULTS["COOP_SPLIT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(brokerage_id: str, **overrides) -> dict:
    defaults = {
        "brokerage_id": brokerage_id,
        "full_name": "Agent Smith",
        "license_no": unique_license_no(),
    }
    defaults.update(overrides)
    return defaults


def create_buyer_payload(buyer_agent_id: str, **overrides) -> dict:
    defaults = {
        "buyer_agent_id": buyer_agent_id,
        "full_name": "Bob Buyer",
        "max_budget_cents": DEFAULTS["MAX_BUDGET_CENTS"],
        "monthly_income_cents": DEFAULTS["MONTHLY_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(listing_agent_id: str, **overrides) -> dict:
    defaults = {
        "listing_agent_id": listing_agent_id,
        "address": unique_address(),
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lockbox_payload(**overrides) -> dict:
    defaults = {"serial_no": unique_serial_no()}
    defaults.update(overrides)
    return defaults


def create_showing_payload(buyer_agent_id: str, buyer_id: str,
                           start_at: str, end_at: str, **overrides) -> dict:
    defaults = {
        "buyer_agent_id": buyer_agent_id,
        "buyer_id": buyer_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(buyer_id: str, buyer_agent_id: str,
                         initial_price_cents: int = 49_000_000,
                         earnest_money_cents: int = 0, **overrides) -> dict:
    defaults = {
        "buyer_id": buyer_id,
        "buyer_agent_id": buyer_agent_id,
        "initial_price_cents": initial_price_cents,
        "earnest_money_cents": earnest_money_cents,
    }
    defaults.update(overrides)
    return defaults


def counter_payload(counter_price_cents: int, actor_agent_id: str, **overrides) -> dict:
    defaults = {
        "counter_price_cents": counter_price_cents,
        "actor_agent_id": actor_agent_id,
    }
    defaults.update(overrides)
    return defaults


def accept_payload(expected_listing_version: int) -> dict:
    return {"expected_listing_version": expected_listing_version}


def close_payload(expected_listing_version: int) -> dict:
    return {"expected_listing_version": expected_listing_version}
