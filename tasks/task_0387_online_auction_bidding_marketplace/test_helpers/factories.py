"""Payload factories — one per mutating endpoint, input fields only.

Field names match the PRD exactly. Optional fields are only included when the
caller overrides them, so default-value tests can observe server defaults.
"""

_email_counter = [0]


def unique_email(prefix="u") -> str:
    """Generate a unique email for account creation within a single test."""
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


# --- Account ---
def create_account_payload(roles=None, **overrides) -> dict:
    defaults = {
        "email": unique_email("acct"),
        "display_name": "Test Account",
        "roles": roles if roles is not None else ["SELLER", "BUYER"],
    }
    defaults.update(overrides)
    return defaults


# --- Listing ---
def create_listing_payload(seller_account_id: str, format: str = "BUY_NOW", **overrides) -> dict:
    """Build a listing payload. Only declared input fields are set; computed and
    optional fields appear only via overrides so default behavior is observable."""
    defaults = {
        "seller_account_id": seller_account_id,
        "title": "Test Item",
        "format": format,
    }
    if format in ("BUY_NOW", "HYBRID"):
        defaults.setdefault("buy_now_price_cents", 30000)
    if format in ("AUCTION", "HYBRID"):
        defaults.setdefault("start_price_cents", 10000)
        defaults.setdefault("scheduled_end_at", "2026-12-31T00:00:00Z")
    defaults.update(overrides)
    return defaults


# --- Bid ---
def create_bid_payload(bidder_account_id: str, max_proxy_cents: int, **overrides) -> dict:
    defaults = {
        "bidder_account_id": bidder_account_id,
        "max_proxy_cents": max_proxy_cents,
    }
    defaults.update(overrides)
    return defaults


# --- Buy now ---
def buy_now_payload(buyer_account_id: str, **overrides) -> dict:
    defaults = {"buyer_account_id": buyer_account_id}
    defaults.update(overrides)
    return defaults


# --- Watch ---
def create_watch_payload(watcher_account_id: str, **overrides) -> dict:
    defaults = {"watcher_account_id": watcher_account_id}
    defaults.update(overrides)
    return defaults


# --- Offer ---
def create_offer_payload(buyer_account_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "buyer_account_id": buyer_account_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def counter_offer_payload(amount_cents: int, expected_offer_version: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_offer_version": expected_offer_version,
    }
    defaults.update(overrides)
    return defaults


def accept_offer_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


# --- Order ---
def pay_order_payload(expected_order_version: int, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


# --- Feedback ---
def create_feedback_payload(rater_account_id: str, rating: str, **overrides) -> dict:
    defaults = {
        "rater_account_id": rater_account_id,
        "rating": rating,
    }
    defaults.update(overrides)
    return defaults


# --- Dispute ---
def create_dispute_payload(opener_account_id: str, reason: str, requested_amount_cents: int, **overrides) -> dict:
    defaults = {
        "opener_account_id": opener_account_id,
        "reason": reason,
        "requested_amount_cents": requested_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def respond_dispute_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(approved_amount_cents: int, **overrides) -> dict:
    defaults = {"approved_amount_cents": approved_amount_cents}
    defaults.update(overrides)
    return defaults


# --- Clock ---
def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
