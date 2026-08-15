"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COMPANY_NAME": "Test Co",
    "UNIT_NAME": "U1",
    "PRICING_NODE": "WEST_HUB",
    "CAPACITY_MW": 10,
    "OFFERED_MW": 10,
    "OFFER_PRICE": 5000,
    "OBLIGATED_MW": 10,
    "CAPACITY_RATE": 1000000,
    "DELIVERY_PERIOD": "2026-08",
    "AMOUNT_CENTS": 100000,
    "MARKET_DATE": "2026-08-03",
    "GATE_CLOSE": "2026-08-02T10:30:00Z",
    "AWARDED_MW": 5,
    "CAPACITY_PRICE": 1200,
}


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "credit_rating_tier": "INVESTMENT_GRADE",
    }
    defaults.update(overrides)
    return defaults


def create_generator_payload(**overrides) -> dict:
    defaults = {
        "market_participant_id": "",
        "unit_name": DEFAULTS["UNIT_NAME"],
        "pricing_node": DEFAULTS["PRICING_NODE"],
        "capacity_mw": DEFAULTS["CAPACITY_MW"],
    }
    defaults.update(overrides)
    return defaults


def create_operating_day_payload(**overrides) -> dict:
    defaults = {
        "market_date": DEFAULTS["MARKET_DATE"],
        "da_gate_close_at": DEFAULTS["GATE_CLOSE"],
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "generator_asset_id": "",
        "offered_mw": DEFAULTS["OFFERED_MW"],
        "offer_price_cents_per_mwh": DEFAULTS["OFFER_PRICE"],
        "expected_operating_day_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_telemetry_payload(**overrides) -> dict:
    defaults = {
        "operating_day_id": "",
        "readings": [],
        "expected_generator_asset_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_outage_payload(**overrides) -> dict:
    defaults = {
        "outage_type": "PARTIAL",
        "derate_pct": 50,
        "start_at": "2026-08-05T00:00:00Z",
        "end_at": "2026-08-06T00:00:00Z",
        "reason": "test outage",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "dispute_reason": "PRICE_ERROR",
        "disputed_line_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(**overrides) -> dict:
    defaults = {
        "generator_asset_id": "",
        "service_type": "SYNC_RESERVE",
        "awarded_mw": DEFAULTS["AWARDED_MW"],
        "capacity_price_cents": DEFAULTS["CAPACITY_PRICE"],
        "start_interval": 1,
        "end_interval": 4,
    }
    defaults.update(overrides)
    return defaults


def create_obligation_payload(**overrides) -> dict:
    defaults = {
        "generator_asset_id": "",
        "delivery_period": DEFAULTS["DELIVERY_PERIOD"],
        "obligated_mw": DEFAULTS["OBLIGATED_MW"],
        "capacity_rate_cents_per_mw": DEFAULTS["CAPACITY_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_performance_event_payload(**overrides) -> dict:
    defaults = {
        "start_interval": 1,
        "end_interval": 2,
    }
    defaults.update(overrides)
    return defaults


def create_posting_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "instrument_type": "CASH",
    }
    defaults.update(overrides)
    return defaults


def uniform_readings_24(actual_mw) -> list:
    """Build a 24-interval uniform readings array."""
    return [{"interval_index": i, "actual_mw": actual_mw} for i in range(1, 25)]


def partial_readings(pairs) -> list:
    """Build readings from a list of (interval_index, actual_mw) tuples."""
    return [{"interval_index": i, "actual_mw": mw} for i, mw in pairs]
