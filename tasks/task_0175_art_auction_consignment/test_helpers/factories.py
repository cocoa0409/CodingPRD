"""Payload factories — one per entity, input (client-supplied) fields only.

System/computed fields (id, version, status, hammer, balances, etc.) are
never sent in request bodies; the server mints them.
"""

# The Standard 3-tier buyer's-premium schedule used throughout the design
# index (26% / 20% / 14.5% marginal tiers).
STANDARD_TIERS = [
    {"upper_bound_cents": 3000000, "rate_bps": 2600},
    {"upper_bound_cents": 60000000, "rate_bps": 2000},
    {"upper_bound_cents": None, "rate_bps": 1450},
]

# A simple single open-tier flat schedule (20%) used where premium tiering
# is not the subject under test.
FLAT_TIERS = [{"upper_bound_cents": None, "rate_bps": 2000}]


_seq = {"n": 0}


def _uniq(prefix: str) -> str:
    _seq["n"] += 1
    return f"{prefix}{_seq['n']}"


def create_premium_schedule_payload(**overrides) -> dict:
    defaults = {
        "name": "Standard",
        "tiers": [dict(t) for t in STANDARD_TIERS],
    }
    defaults.update(overrides)
    return defaults


def create_seller_payload(**overrides) -> dict:
    n = _uniq("seller")
    defaults = {
        "legal_name": "Test Estate",
        "email": f"{n}@example.com",
        "country_code": "US",
        "payout_iban": "US00000000000000000000000",
    }
    defaults.update(overrides)
    return defaults


def create_bidder_payload(**overrides) -> dict:
    n = _uniq("bidder")
    defaults = {
        "legal_name": "Test Bidder",
        "email": f"{n}@example.com",
        "country_code": "US",
        "credit_limit_cents": 500000000,
    }
    defaults.update(overrides)
    return defaults


def create_consignment_payload(seller_id: str, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "seller_commission_bps": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_auction_sale_payload(buyers_premium_schedule_id: str, **overrides) -> dict:
    defaults = {
        "title": "Test Sale",
        "sale_date_utc": "2026-06-20T15:00:00Z",
        "currency": "USD",
        "buyers_premium_schedule_id": buyers_premium_schedule_id,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(consignment_id: str, **overrides) -> dict:
    defaults = {
        "consignment_id": consignment_id,
        "lot_number": 1,
        "title": "Test Work",
        "artist_name": "Test Artist",
        "artist_alive": False,
        "low_estimate_cents": 1300000,
        "high_estimate_cents": 1800000,
        "reserve_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_paddle_registration_payload(auction_sale_id: str, bidder_id: str, **overrides) -> dict:
    defaults = {
        "auction_sale_id": auction_sale_id,
        "bidder_id": bidder_id,
        "registration_type": "FLOOR",
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(paddle_registration_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "paddle_registration_id": paddle_registration_id,
        "amount_cents": amount_cents,
        "bid_channel": "FLOOR",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, expected_invoice_version: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults
