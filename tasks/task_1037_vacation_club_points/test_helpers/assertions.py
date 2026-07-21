"""Entity assertions and domain invariant checkers (PRD §1, §2.5, §2.6)."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_MEMBER_TIERS = {"STANDARD", "SILVER", "GOLD", "PLATINUM"}
_MEMBER_STATUSES = {"ACTIVE", "SUSPENDED"}
_BUCKET_STATUSES = {"OPEN", "CLOSED"}
_RESERVATION_STATUSES = {"HELD", "CONFIRMED", "COMPLETED", "CANCELLED"}
_GUEST_CERT_STATUSES = {"ISSUED", "USED", "REVOKED"}
_WAITLIST_STATUSES = {"ACTIVE", "PROMOTED", "CANCELLED", "EXPIRED"}
_PAYMENT_STATUSES = {"UNPAID", "PARTIALLY_PAID", "PAID"}
_AGING_STATUSES = {"CURRENT", "PAST_DUE"}
_TRANSFER_STATUSES = {"PENDING", "COMPLETED", "REJECTED"}
_LISTING_STATUSES = {"LISTED", "WITHDRAWN", "EXPIRED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["owned_points"], int) and data["owned_points"] >= 0
    assert data["tier"] in _MEMBER_TIERS, f"unexpected tier {data['tier']!r}"
    assert data["account_status"] in _MEMBER_STATUSES
    assert isinstance(data["current_use_year"], int)


def assert_points_bucket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["use_year"], int)
    for counter in (
        "annual_allotment", "banked_in", "banked_out", "borrowed_in", "borrowed_out",
        "transferred_in", "transferred_out", "points_used", "points_available",
    ):
        assert isinstance(data[counter], int), f"{counter} must be int"
    assert data["status"] in _BUCKET_STATUSES
    assert_bucket_available_invariant(data)


def assert_bucket_available_invariant(data: dict):
    """points_available = allotment + credits - debits, clamped at 0 (PRD §2.6)."""
    raw = (
        data["annual_allotment"]
        + data["banked_in"] + data["borrowed_in"] + data["transferred_in"]
        - data["banked_out"] - data["borrowed_out"] - data["transferred_out"]
        - data["points_used"]
    )
    expected = max(raw, 0)
    assert data["points_available"] == expected, (
        f"points_available should be max(0, {raw}) == {expected}, got {data['points_available']}"
    )
    assert data["points_available"] >= 0, "points_available is never negative"


def assert_resort(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str)


def assert_unit_type(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["resort_id"])
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    for cell in (
        "points_weekday_low", "points_weekend_low", "points_weekday_high", "points_weekend_high",
    ):
        assert isinstance(data[cell], int) and data[cell] >= 1


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["unit_type_id"])
    assert is_valid_uuid(data["points_bucket_id"])
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["points_cost"], int) and data["points_cost"] >= 0
    assert data["status"] in _RESERVATION_STATUSES
    assert isinstance(data["refunded_points"], int)


def assert_guest_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["reservation_id"])
    assert isinstance(data["guest_name"], str)
    assert isinstance(data["fee_points"], int)
    assert data["status"] in _GUEST_CERT_STATUSES


def assert_waitlist(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["unit_type_id"])
    assert data["status"] in _WAITLIST_STATUSES


def assert_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    for cents in (
        "maintenance_fee_cents", "club_dues_cents", "special_assessment_cents",
        "total_due_cents", "amount_paid_cents",
    ):
        assert isinstance(data[cents], int), f"{cents} must be int cents"
    assert data["payment_status"] in _PAYMENT_STATUSES
    assert data["aging_status"] in _AGING_STATUSES
    assert (
        data["total_due_cents"]
        == data["maintenance_fee_cents"] + data["club_dues_cents"] + data["special_assessment_cents"]
    ), "total_due_cents must equal the sum of the three lines (PRD §2.7)"


def assert_transfer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["from_member_id"])
    assert is_valid_uuid(data["to_member_id"])
    assert isinstance(data["points"], int) and data["points"] >= 1
    assert data["status"] in _TRANSFER_STATUSES


def assert_listing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["reservation_id"])
    assert data["listing_type"] in {"EXCHANGE", "RENTAL"}
    assert data["status"] in _LISTING_STATUSES
