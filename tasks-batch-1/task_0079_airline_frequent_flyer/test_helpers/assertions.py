"""Entity assertions and domain invariant checkers.

Built on the framework's generic validators. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data):
    """id (UUID), created_at, updated_at (ISO8601), integer version >= 1 (PRD §2.4)."""
    assert is_valid_uuid(data["id"]), f"bad id: {data.get('id')}"
    assert is_iso8601_timestamp(data["created_at"]), f"bad created_at: {data.get('created_at')}"
    assert is_iso8601_timestamp(data["updated_at"]), f"bad updated_at: {data.get('updated_at')}"
    assert isinstance(data["version"], int) and data["version"] >= 1, f"bad version: {data.get('version')}"


def assert_member(data):
    assert_common_fields(data)
    assert data["tier"] in ("BASE", "SILVER", "GOLD", "PLATINUM"), f"bad tier: {data.get('tier')}"
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0
    assert isinstance(data["qualifying_segments_ytd"], int) and data["qualifying_segments_ytd"] >= 0
    assert isinstance(data["status_match_active"], bool)
    assert isinstance(data["status_match_used"], bool)


def assert_flight_segment(data):
    assert_common_fields(data)
    assert data["status"] in ("BOOKED", "FLOWN", "ACCRUED", "CANCELLED")


def assert_award_booking(data):
    assert_common_fields(data)
    assert data["status"] in ("QUOTED", "ISSUED", "CANCELLED", "FLOWN")
    assert isinstance(data["points_price"], int)


def assert_flight_pool(data):
    assert_common_fields(data)
    assert isinstance(data["premium_capacity"], int)
    assert isinstance(data["seats_cleared"], int)
    assert isinstance(data["seats_remaining"], int)
    # PRD §3.8: cleared plus remaining always equals capacity.
    assert data["seats_cleared"] + data["seats_remaining"] == data["premium_capacity"], (
        f"seat invariant broken: {data['seats_cleared']}+{data['seats_remaining']}!={data['premium_capacity']}"
    )


def assert_upgrade_request(data):
    assert_common_fields(data)
    assert data["status"] in ("WAITLISTED", "CLEARED", "DENIED", "WITHDRAWN")
    assert isinstance(data["priority_score"], int)


def assert_companion_certificate(data):
    assert_common_fields(data)
    assert data["status"] in ("ISSUED", "RESERVED", "REDEEMED", "EXPIRED")


def assert_points_gift(data):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "SETTLED", "REVERSED")


def assert_status_match(data):
    assert_common_fields(data)
    assert data["status"] in ("GRANTED", "EXPIRED")
    assert data["matched_tier"] in ("BASE", "SILVER", "GOLD", "PLATINUM")


def assert_ledger_row(data):
    """PointsLedger carries only id + created_at (PRD §2.4); never updated_at/version."""
    assert is_valid_uuid(data["id"]), f"bad ledger id: {data.get('id')}"
    assert is_iso8601_timestamp(data["created_at"]), f"bad ledger created_at: {data.get('created_at')}"
    assert isinstance(data["delta"], int) and data["delta"] != 0, f"delta must be non-zero: {data.get('delta')}"
