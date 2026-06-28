"""Entity assertions and domain invariant checkers for the Paint & Sip Event
Studio API. Generic UUID / timestamp validators come from the framework."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_studio(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["room_capacity_seats"], int) and data["room_capacity_seats"] >= 1
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_artist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["credit_redeemed_cents"], int)
    assert data["credit_balance_cents"] >= 0, "credit_balance_cents must never go negative"


def assert_event(data: dict):
    _assert_common(data)
    assert data["event_type"] in ("PUBLIC_CLASS", "PRIVATE_PARTY", "FUNDRAISER", "CORPORATE")
    assert data["status"] in ("DRAFT", "SCHEDULED", "OPEN", "FULL", "CLOSED", "CANCELLED")
    assert isinstance(data["seats_capacity"], int) and data["seats_capacity"] >= 1
    assert isinstance(data["price_cents_per_seat"], int) and data["price_cents_per_seat"] >= 0
    assert isinstance(data["seats_reserved"], int)
    assert isinstance(data["seats_available"], int)
    assert isinstance(data["walk_in_seats"], int)


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["booking_mode"] in ("PUBLIC", "PRIVATE")
    assert data["status"] in ("HELD", "CONFIRMED", "CHECKED_IN", "CANCELLED", "NO_SHOW")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert isinstance(data["seats"], int) and data["seats"] >= 1
    assert isinstance(data["total_cents"], int)


def assert_walk_in(data: dict):
    _assert_common(data)
    assert data["status"] in ("REGISTERED", "CHECKED_IN", "CANCELLED")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1


def assert_gift_card(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DEPLETED")
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert isinstance(data["redeemed_cents"], int)


def assert_attendee_shape(data: dict):
    """Attendee is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "Attendee id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Attendee must NOT carry a version field"
    assert "updated_at" not in data, "Attendee must NOT carry an updated_at field"


# ─── Domain invariants ─────────────────────────────────────────────────────

def assert_seat_ledger_consistent(event: dict):
    """capacity == seats_available + seats_reserved + walk_in_seats, with
    seats_available floored at zero (so this holds only when not oversold)."""
    cap = event["seats_capacity"]
    reserved = event["seats_reserved"]
    walk = event["walk_in_seats"]
    avail = event["seats_available"]
    assert avail >= 0, "seats_available is floored at 0"
    assert cap == avail + reserved + walk, (
        f"Seat conservation violated: capacity {cap} != available {avail} "
        f"+ reserved {reserved} + walk_in {walk}")


def assert_gift_card_value_conserved(card: dict):
    """balance_cents + redeemed_cents == issued_value_cents (no value drift)."""
    assert card["balance_cents"] + card["redeemed_cents"] == card["issued_value_cents"], (
        f"Gift-card value not conserved: balance {card['balance_cents']} + "
        f"redeemed {card['redeemed_cents']} != issued {card['issued_value_cents']}")
