"""Payload factories — one per entity, input fields only."""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "email": f"{_uniq('user')}@example.com",
        "display_name": "Test Account",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(tier: str = "PRO", **overrides) -> dict:
    defaults = {"tier": tier}
    defaults.update(overrides)
    return defaults


def create_credit_adjustment_payload(delta: int, reason: str = "MANUAL_ADJUST", **overrides) -> dict:
    defaults = {"delta": delta, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_contact_payload(account_id: str, region: str = "CA", **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "full_name": "Recipient Name",
        "address_line1": "1 Test Street",
        "city": "Testville",
        "region": region,
        "postal_code": "90001",
        "country_code": "US",
    }
    defaults.update(overrides)
    return defaults


def create_card_payload(base_price_cents: int = 200, weight_grams: int = 10,
                        category: str = "BIRTHDAY", **overrides) -> dict:
    defaults = {
        "sku": _uniq("CARD"),
        "title": "Test Card",
        "category": category,
        "base_price_cents": base_price_cents,
        "weight_grams": weight_grams,
    }
    defaults.update(overrides)
    return defaults


def create_gift_item_payload(price_cents: int = 800, weight_grams: int = 40,
                             kind: str = "CHOCOLATE", **overrides) -> dict:
    defaults = {
        "sku": _uniq("GIFT"),
        "title": "Test Gift",
        "kind": kind,
        "price_cents": price_cents,
        "weight_grams": weight_grams,
    }
    defaults.update(overrides)
    return defaults


def create_artist_payload(daily_capacity: int = 5, region_code: str = "CA", **overrides) -> dict:
    defaults = {
        "name": _uniq("Artist"),
        "daily_capacity": daily_capacity,
        "region_code": region_code,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(account_id: str, contact_id: str, card_id: str,
                         message_text: str = "Happy day!",
                         scheduled_send_at: str = "2026-04-01T00:00:00Z",
                         **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "contact_id": contact_id,
        "card_id": card_id,
        "message_text": message_text,
        "scheduled_send_at": scheduled_send_at,
    }
    defaults.update(overrides)
    return defaults


def create_important_date_payload(occasion_type: str = "BIRTHDAY",
                                  event_date: str = "2026-05-10T00:00:00Z",
                                  lead_days: int = 5, **overrides) -> dict:
    defaults = {
        "occasion_type": occasion_type,
        "event_date": event_date,
        "lead_days": lead_days,
    }
    defaults.update(overrides)
    return defaults


def import_row(**overrides) -> dict:
    defaults = {
        "full_name": "Imported Name",
        "address_line1": "1 Import Way",
        "city": "Testville",
        "region": "CA",
        "postal_code": "90001",
        "country_code": "US",
    }
    defaults.update(overrides)
    return defaults
