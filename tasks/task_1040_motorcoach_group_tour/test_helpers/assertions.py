"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_departure(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "PLANNING", "OPEN", "GUARANTEED", "DEPARTED", "SETTLED", "CANCELLED"
    ], f"unexpected departure status {data.get('status')!r}"
    assert isinstance(data["confirmed_pax"], int)
    assert data["occupancy_band"] in ["SMALL", "STANDARD", "LARGE"]


def assert_coach(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["AVAILABLE", "ASSIGNED"]
    assert isinstance(data["seat_capacity"], int)


def assert_booking(data: dict):
    assert_common_fields(data)
    assert data["reservation_status"] in ["DRAFT", "CONFIRMED", "TRAVELED", "CANCELLED"]
    assert data["payment_status"] in ["UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED"]
    assert isinstance(data["pax_count"], int) and data["pax_count"] >= 1


def assert_payment(data: dict):
    """Payment is append-only: id + created_at only (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "payment id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ["DEPOSIT", "BALANCE", "REFUND"]


def assert_voucher(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ISSUED", "REDEEMED", "VOIDED"]
    assert data["kind"] == "MEAL"
