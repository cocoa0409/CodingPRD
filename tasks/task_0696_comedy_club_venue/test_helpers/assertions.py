"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape and field domains of a single
resource as the PRD describes it. Money invariants use integer-cent checks.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')}"


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["settlement_currency"], str) and len(data["settlement_currency"]) > 0
    assert 0.0 <= data["house_fee_pct"] <= 1.0, "house_fee_pct must be in [0,1]"
    assert data["posture"] in ("OPEN", "RECONCILING", "CLOSED"), \
        f"unexpected posture {data['posture']}"


def assert_show(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["venue_id"]), "venue_id must be a UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert is_iso8601_timestamp(data["starts_at"]), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data["ends_at"]), "ends_at must be ISO 8601"
    assert isinstance(data["doors_buffer_minutes"], int)
    assert data["status"] in (
        "DRAFT", "ON_SALE", "PRIVATE_HELD", "SOLD_OUT",
        "CANCELLED", "SETTLING", "SETTLED",
    ), f"unexpected show status {data['status']}"
    assert isinstance(data["is_private"], bool)
    assert isinstance(data["ga_sold_count"], int) and data["ga_sold_count"] >= 0


def assert_section(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["show_id"]), "show_id must be a UUID"
    assert data["kind"] in ("GA", "RESERVED", "TABLE"), f"unexpected kind {data['kind']}"
    assert isinstance(data["label"], str)
    if data["kind"] in ("GA", "RESERVED"):
        assert isinstance(data["ga_capacity"], int) and data["ga_capacity"] >= 1, \
            "capacity-tracked section must carry a positive ga_capacity"
    else:
        assert data["ga_capacity"] is None, "TABLE section must have null ga_capacity"


def assert_table(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["section_id"]), "section_id must be a UUID"
    assert isinstance(data["table_number"], str)
    assert isinstance(data["seats"], int) and data["seats"] >= 1
    assert isinstance(data["min_items_per_seat"], int) and data["min_items_per_seat"] >= 0
    assert data["status"] in ("AVAILABLE", "HELD", "OCCUPIED", "RETIRED"), \
        f"unexpected table status {data['status']}"


def assert_performer(data: dict):
    _assert_common(data)
    assert isinstance(data["stage_name"], str) and len(data["stage_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["standard_fee_cents"], int) and data["standard_fee_cents"] >= 0


def assert_lineup_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["show_id"]), "show_id must be a UUID"
    assert is_valid_uuid(data["performer_id"]), "performer_id must be a UUID"
    assert isinstance(data["slot_order"], int)
    assert data["role"] in ("HOST", "OPENER", "FEATURE", "HEADLINER")
    assert isinstance(data["offered_fee_cents"], int)
    assert data["contract_status"] in ("OFFERED", "COUNTERED", "SIGNED", "DROPPED")
    assert isinstance(data["counter_rounds"], int) and data["counter_rounds"] >= 0


def assert_tier(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["show_id"]), "show_id must be a UUID"
    assert is_valid_uuid(data["section_id"]), "section_id must be a UUID"
    assert isinstance(data["name"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["show_id"]), "show_id must be a UUID"
    assert is_valid_uuid(data["section_id"]), "section_id must be a UUID"
    assert is_valid_uuid(data["tier_id"]), "tier_id must be a UUID"
    assert isinstance(data["patron_id"], str) and len(data["patron_id"]) > 0
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["is_comp"], bool)
    assert data["booking_status"] in (
        "BOOKED", "SEATED", "CHECKED_IN", "NO_SHOW", "CANCELLED", "EXCHANGED",
    ), f"unexpected booking_status {data['booking_status']}"
    assert data["settlement_status"] in (
        "UNCOLLECTED", "TICKET_PAID", "MINIMUM_MET", "REFUNDED",
    ), f"unexpected settlement_status {data['settlement_status']}"
    assert isinstance(data["ticket_charge_cents"], int) and data["ticket_charge_cents"] >= 0
    assert isinstance(data["minimum_due_cents"], int) and data["minimum_due_cents"] >= 0
    assert isinstance(data["items_consumed_cents"], int) and data["items_consumed_cents"] >= 0
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0


def assert_ticket(data: dict):
    """Ticket is immutable: carries only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "ticket id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["reservation_id"]), "reservation_id must be a UUID"
    assert isinstance(data["seat_label"], str)
    assert data["scan_state"] in ("ISSUED", "SCANNED", "VOID"), \
        f"unexpected scan_state {data['scan_state']}"


def assert_guest_list_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["show_id"]), "show_id must be a UUID"
    assert is_valid_uuid(data["host_performer_id"]), "host_performer_id must be a UUID"
    assert isinstance(data["guest_name"], str)
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["minimum_waived"], bool)
    assert data["status"] in ("LISTED", "CONVERTED", "REVOKED"), \
        f"unexpected guest-list status {data['status']}"


def assert_server(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["max_tables"], int) and data["max_tables"] >= 1
    assert isinstance(data["assigned_table_count"], int) and data["assigned_table_count"] >= 0


def assert_private_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["show_id"]), "show_id must be a UUID"
    assert isinstance(data["client_name"], str)
    assert isinstance(data["buyout_fee_cents"], int) and data["buyout_fee_cents"] >= 0
    assert 0.0 <= data["deposit_pct"] <= 1.0, "deposit_pct must be in [0,1]"
    assert data["status"] in ("HELD", "CONFIRMED", "CANCELLED"), \
        f"unexpected private-event status {data['status']}"
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["show_id"]), "show_id must be a UUID"
    assert data["status"] in ("OPEN", "FINALIZED"), \
        f"unexpected settlement status {data['status']}"
    for f in (
        "gross_ticket_cents", "gross_minimum_cents", "buyout_cents",
        "performer_payout_cents", "house_cut_cents", "net_to_venue_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer cent value"
