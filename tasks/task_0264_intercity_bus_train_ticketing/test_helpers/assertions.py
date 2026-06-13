"""Entity assertions and domain invariant checkers for the Intercity Ticketing API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_audit(data: dict):
    """id + created_at + updated_at + version triple (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def assert_operator(data: dict):
    _common_audit(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["mode"] in ("RAIL", "BUS")
    assert isinstance(data["default_connection_buffer_min"], int)
    assert data["default_connection_buffer_min"] >= 0
    assert isinstance(data["exchange_fee_cents"], int) and data["exchange_fee_cents"] >= 0


def assert_fare_class(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("operator_id", ""))
    assert data["code"] in ("ECONOMY", "BUSINESS")
    assert data["seating_mode"] in ("RESERVED", "OPEN")
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0
    assert isinstance(data["refundable"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_route(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("operator_id", ""))
    assert isinstance(data["origin_code"], str)
    assert isinstance(data["destination_code"], str)
    assert 0 <= data["depart_minute_of_day"] <= 1439
    assert 0 <= data["arrive_minute_of_day"] <= 1439
    assert data["status"] in ("DRAFT", "PUBLISHED")


def assert_service_date(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data["departure_date"], str)
    assert isinstance(data["seats_total"], int) and data["seats_total"] >= 1
    assert isinstance(data["base_fare_cents"], int) and data["base_fare_cents"] >= 0
    assert data["lifecycle"] in ("SCHEDULED", "DELAYED", "DEPARTED", "CANCELLED")
    assert data["sales"] in ("OPEN", "SUSPENDED")
    assert_service_date_inventory(data)


def assert_service_date_inventory(data: dict):
    """Seat-ledger invariants (PRD §2.6)."""
    held = data["seats_held"]
    sold = data["seats_sold"]
    avail = data["seats_available"]
    total = data["seats_total"]
    assert held >= 0 and sold >= 0 and avail >= 0, "seat counters never negative"
    assert avail == total - held - sold, (
        f"seats_available {avail} must equal {total} - {held} - {sold}"
    )
    # load_factor is seats_sold / seats_total (confirmed legs only).
    expected_lf = sold / total if total else 0.0
    assert abs(data["load_factor"] - expected_lf) < 1e-9, (
        f"load_factor {data['load_factor']} must equal seats_sold/seats_total {expected_lf}"
    )


def assert_passenger(data: dict):
    _common_audit(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["needs_accessibility"], bool)


def assert_travel_pass(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("passenger_id", ""))
    assert is_valid_uuid(data.get("operator_id", ""))
    assert isinstance(data["rides_total"], int) and data["rides_total"] >= 1
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")
    assert_pass_rides_invariant(data)


def assert_pass_rides_invariant(data: dict):
    """rides_remaining = rides_total - rides_consumed, never negative (PRD §3.10)."""
    assert data["rides_consumed"] >= 0
    assert data["rides_remaining"] >= 0
    assert data["rides_remaining"] == data["rides_total"] - data["rides_consumed"], (
        "rides_remaining must equal rides_total - rides_consumed"
    )


def assert_booking(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("passenger_id", ""))
    assert data["booking_status"] in ("HELD", "CONFIRMED", "CANCELLED", "EXCHANGED")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED", "CREDITED")
    assert data["funding_kind"] in ("CASH", "PASS")
    assert isinstance(data["total_fare_cents"], int)
    assert isinstance(data["total_paid_cents"], int)


def assert_booking_leg(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("service_date_id", ""))
    assert is_valid_uuid(data.get("fare_class_id", ""))
    assert isinstance(data["leg_order"], int) and data["leg_order"] >= 1
    assert data["leg_state"] in ("ACTIVE", "RELEASED")
    assert isinstance(data["fare_cents"], int)


def assert_ticket(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("booking_leg_id", ""))
    assert isinstance(data["barcode"], str) and len(data["barcode"]) > 0
    assert data["state"] in ("ISSUED", "SCANNED", "VOID")


def assert_baggage_item(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert data["weight_kg"] > 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_accessibility_request(data: dict):
    _common_audit(data)
    assert is_valid_uuid(data.get("booking_leg_id", ""))
    assert data["accommodation"] in ("WHEELCHAIR_SPACE", "COMPANION_SEAT", "SERVICE_ANIMAL")
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED")


def assert_settlement_note(data: dict):
    """Append-only, immutable: only id + created_at audit fields; NO updated_at,
    NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("booking_id", ""))
    assert data["settlement_kind"] in ("CASH", "TRAVEL_CREDIT")
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["net_cents"] == data["gross_cents"] - data["penalty_cents"], (
        "net_cents must equal gross_cents - penalty_cents"
    )
