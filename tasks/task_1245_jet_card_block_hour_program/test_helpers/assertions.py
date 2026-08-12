"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_card_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["aircraft_category"] in ["LIGHT", "MIDSIZE", "SUPER_MID", "HEAVY"]
    assert isinstance(data["hours_purchased"], int)
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["expiry_months"], int)
    assert isinstance(data["taxi_minutes_per_leg"], int)
    assert isinstance(data["min_billable_minutes_per_leg"], int)
    assert isinstance(data["availability_window_hours"], int)
    assert data["version"] >= 1


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["member_status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["tier"] in ["INDIVIDUAL", "FAMILY", "CORPORATE"]
    assert data["version"] >= 1


def assert_jet_card(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a valid UUID"
    assert data["card_status"] in [
        "PENDING_PAYMENT", "ACTIVE", "SUSPENDED", "EXPIRED", "CLOSED", "REFUNDED",
    ]
    assert isinstance(data["hours_total"], int)
    assert isinstance(data["hours_remaining"], (int, float))
    assert isinstance(data["hours_consumed"], (int, float))
    assert isinstance(data["hours_expired"], (int, float))
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["peak_hours_used"], (int, float))
    assert data["version"] >= 1


def assert_ledger_entry(data: dict):
    """HourBankLedger is append-only: only id + created_at, never updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entries must not carry updated_at"
    assert "version" not in data, "append-only ledger entries must not carry version"
    assert data["entry_kind"] in [
        "PURCHASE_GRANT", "TRIP_DEBIT", "EXPIRATION_DEBIT",
        "REFUND_DEBIT", "UPGRADE_DEBIT", "SWAP_ADJUSTMENT",
    ]
    assert isinstance(data["hours_delta"], (int, float))


def assert_aircraft(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert data["category"] in ["LIGHT", "MIDSIZE", "SUPER_MID", "HEAVY"]
    assert data["aircraft_status"] in ["AVAILABLE", "IN_SERVICE", "MAINTENANCE", "GROUNDED"]
    assert isinstance(data["seats"], int)
    assert data["version"] >= 1


def assert_trip(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("card_id", "")), "card_id must be a valid UUID"
    assert data["trip_kind"] in ["ONE_WAY", "ROUND_TRIP"]
    assert data["trip_status"] in [
        "QUOTE", "CONFIRMED", "DISPATCHED", "IN_FLIGHT",
        "COMPLETED", "CANCELED", "NO_SHOW", "DENIED",
    ]
    assert data["requested_category"] in ["LIGHT", "MIDSIZE", "SUPER_MID", "HEAVY"]
    assert isinstance(data["pax_count"], int)
    assert isinstance(data["is_peak_period"], bool)
    assert isinstance(data["quoted_hours"], (int, float))
    assert data["version"] >= 1


def assert_trip_leg(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("trip_id", "")), "trip_id must be a valid UUID"
    assert data["leg_seq"] in [1, 2]
    assert data["leg_status"] in ["PLANNED", "FLOWN", "CANCELED"]
    assert data["version"] >= 1


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("trip_id", "")), "trip_id must be a valid UUID"
    assert data["invoice_status"] in ["DRAFT", "ISSUED", "PAID", "DISPUTED", "WRITTEN_OFF"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["peak_surcharge_cents"], int)
    assert isinstance(data["round_trip_discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["version"] >= 1


def assert_escrow_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("card_id", "")), "card_id must be a valid UUID"
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert isinstance(data["released_cents"], int)
    assert isinstance(data["forfeited_cents"], int)
    assert data["version"] >= 1


def assert_refund(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("card_id", "")), "card_id must be a valid UUID"
    assert data["refund_status"] in ["DRAFT", "SUBMITTED", "APPROVED", "DENIED", "SETTLED"]
    assert data["version"] >= 1


def assert_fractional_upgrade(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("card_id", "")), "card_id must be a valid UUID"
    assert data["upgrade_status"] in ["PENDING", "APPLIED", "CANCELED"]
    assert data["version"] >= 1


def assert_hour_bank_conservation(card: dict):
    """Total block hours are conserved across consumed / remaining / expired."""
    total = card["hours_total"]
    consumed = card["hours_consumed"]
    remaining = card["hours_remaining"]
    expired = card["hours_expired"]
    assert abs(total - (consumed + remaining + expired)) < 0.005, (
        f"hours_total {total} != consumed {consumed} + remaining {remaining} + expired {expired}"
    )


def assert_escrow_conservation(escrow: dict):
    """Escrow principal is conserved across available / released / forfeited."""
    principal = escrow["principal_cents"]
    available = escrow["available_cents"]
    released = escrow["released_cents"]
    forfeited = escrow["forfeited_cents"]
    assert principal == available + released + forfeited, (
        f"principal {principal} != available {available} + released {released} + forfeited {forfeited}"
    )
