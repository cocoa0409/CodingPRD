"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_MEMBER_STATUSES = ["PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "LAPSED"]
_DOG_STATUSES = ["SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED"]
_MEMBERSHIP_STATUSES = ["ACTIVE", "SUSPENDED", "EXPIRED"]
_PASS_STATUSES = ["ISSUED", "REDEEMED", "VOID", "EXPIRED"]
_CLOSURE_STATUSES = ["SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED"]
_VISIT_STATUSES = ["OPEN", "CLOSED", "FORCE_CLOSED"]
_CLOSE_REASONS = ["VOLUNTARY", "MEMBER_SUSPENDED", "NIGHTLY_SWEEP"]
_SEVERITIES = ["MINOR", "MAJOR", "SEVERE"]
_REPORT_STATUSES = ["FILED", "UNDER_REVIEW", "CONFIRMED", "DISMISSED"]
_STATION_STATUSES = ["OK", "NEEDS_SERVICE"]
_SIZE_CLASSES = ["SMALL", "LARGE"]


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating 'Z' and fractional digits."""
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Two ISO 8601 strings denote the same UTC instant regardless of whether
    fractional digits are rendered."""
    actual_dt = _parse_instant(actual).astimezone(timezone.utc)
    expected_dt = _parse_instant(expected_iso).astimezone(timezone.utc)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version begins at 1 and increments on every mutation"


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data.get("phone") is None or isinstance(data["phone"], str)
    assert isinstance(data["is_steward"], bool)
    assert data["status"] in _MEMBER_STATUSES
    assert isinstance(data["strike_points"], int) and data["strike_points"] >= 0
    assert isinstance(data["provisional_strike_score"], int) \
        and data["provisional_strike_score"] >= 0
    assert isinstance(data["guest_passes_used_this_month"], int) \
        and data["guest_passes_used_this_month"] >= 0


def assert_dog(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["size_class"] in _SIZE_CLASSES
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["vaccination_expires_on"], str)
    assert data["verification_status"] in _DOG_STATUSES
    assert data.get("rejection_reason") is None \
        or isinstance(data["rejection_reason"], str)


def assert_membership(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["member_id"], str) and data["member_id"]
    _parse_instant(data["term_start"])  # must be an ISO 8601 instant
    _parse_instant(data["term_end"])
    assert isinstance(data["charged_fee_cents"], int) \
        and data["charged_fee_cents"] >= 0
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    assert data["status"] in _MEMBERSHIP_STATUSES


def assert_guest_pass(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sponsor_member_id"], str)
    assert data["guest_dog_size_class"] in _SIZE_CLASSES
    assert isinstance(data["valid_on"], str) and data["valid_on"]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in _PASS_STATUSES


def assert_park_area(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["size_class_restriction"] in _SIZE_CLASSES
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["peak_capacity"], int)
    assert data["peak_capacity"] <= data["capacity"]
    assert isinstance(data["peak_windows"], list)
    assert isinstance(data["current_occupancy"], int) \
        and data["current_occupancy"] >= 0
    assert isinstance(data["effective_capacity"], int) \
        and data["effective_capacity"] >= 0


def assert_area_closure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["area_id"], str) and data["area_id"]
    assert isinstance(data["starts_at"], str) and data["starts_at"]
    assert isinstance(data["ends_at"], str) and data["ends_at"]
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in _CLOSURE_STATUSES


def assert_park_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert data.get("dog_id") is None or isinstance(data["dog_id"], str)
    assert data.get("guest_pass_id") is None \
        or isinstance(data["guest_pass_id"], str)
    # Exactly one of dog_id / guest_pass_id is set (PRD §3.5).
    assert (data.get("dog_id") is None) != (data.get("guest_pass_id") is None)
    assert isinstance(data["area_id"], str) and data["area_id"]
    assert isinstance(data["checked_in_at"], str) and data["checked_in_at"]
    assert data.get("checked_out_at") is None \
        or isinstance(data["checked_out_at"], str)
    assert data["status"] in _VISIT_STATUSES
    if data["status"] == "OPEN":
        assert data.get("checked_out_at") is None
        assert data.get("close_reason") is None
    else:
        assert data.get("close_reason") in _CLOSE_REASONS


def assert_incident_report(data: dict):
    _assert_common_fields(data)
    assert data.get("reporter_member_id") is None \
        or isinstance(data["reporter_member_id"], str)
    assert isinstance(data["subject_member_id"], str)
    assert data.get("subject_dog_id") is None \
        or isinstance(data["subject_dog_id"], str)
    assert data.get("area_id") is None or isinstance(data["area_id"], str)
    assert data["severity"] in _SEVERITIES
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["occurred_at"], str) and data["occurred_at"]
    assert data["status"] in _REPORT_STATUSES
    assert data.get("resolution_note") is None \
        or isinstance(data["resolution_note"], str)


def assert_waste_station(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["area_id"], str) and data["area_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fill_pct"], int) and 0 <= data["fill_pct"] <= 100
    assert data["status"] in _STATION_STATUSES
    assert data.get("last_serviced_at") is None \
        or isinstance(data["last_serviced_at"], str)
    # fill_pct >= 80 implies NEEDS_SERVICE (PRD §3.8).
    if data["fill_pct"] >= 80:
        assert data["status"] == "NEEDS_SERVICE"
