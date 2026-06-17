"""Payload factories — one per entity, input fields only.

Only fields the PRD declares as client-supplied input appear here. System,
computed, and OCC-version fields are never sent except where an endpoint
explicitly requires them (expected_listing_version on accept,
expected_offer_version on meetup create), which callers pass explicitly.
"""
import itertools

_email_seq = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_email_seq)}@example.com"


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email("member"),
        "display_name": "Test Member",
    }
    defaults.update(overrides)
    return defaults


def create_category_payload(**overrides) -> dict:
    defaults = {
        "slug": "furniture",
        "name": "Furniture",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(seller_id, **overrides) -> dict:
    defaults = {
        "seller_id": seller_id,
        "category_slug": "furniture",
        "title": "Oak Desk",
        "description": "solid",
        "ask_price_cents": 10000,
        "min_acceptable_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_conversation_payload(listing_id, buyer_id, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
    }
    defaults.update(overrides)
    return defaults


def create_message_payload(conversation_id, sender_id, **overrides) -> dict:
    defaults = {
        "conversation_id": conversation_id,
        "sender_id": sender_id,
        "body": "Is this still available?",
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(conversation_id, amount_cents=9000, **overrides) -> dict:
    defaults = {
        "conversation_id": conversation_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_safe_trade_spot_payload(**overrides) -> dict:
    defaults = {
        "name": "City Hall Lobby",
        "is_police_verified": False,
        "open_minute_of_day": 480,
        "close_minute_of_day": 1080,
    }
    defaults.update(overrides)
    return defaults


def create_meetup_payload(offer_id, spot_id, expected_offer_version,
                          start_at="2026-06-02T14:00:00Z",
                          end_at="2026-06-02T15:00:00Z", **overrides) -> dict:
    defaults = {
        "offer_id": offer_id,
        "spot_id": spot_id,
        "start_at": start_at,
        "end_at": end_at,
        "expected_offer_version": expected_offer_version,
    }
    defaults.update(overrides)
    return defaults


def create_flag_payload(reporter_id, target_type, reason="SPAM", **overrides) -> dict:
    defaults = {
        "reporter_id": reporter_id,
        "target_type": target_type,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_saved_search_payload(owner_id, category_slug="furniture", **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "category_slug": category_slug,
    }
    defaults.update(overrides)
    return defaults
