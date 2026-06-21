"""Entity assertions and domain invariant checkers (PRD-exact field names)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """id (prefix-free UUID), created_at, updated_at (ISO 8601), version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-free UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_audit_row_fields(data: dict):
    """Append-only rows (CheckIn, NoShowEvent) carry only id + created_at —
    no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-free UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only row must not carry updated_at"
    assert "version" not in data, "append-only row must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["timezone"], str) and len(data["timezone"]) > 0
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_floor(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["level"], int)
    assert isinstance(data["workday_start_minute"], int)
    assert isinstance(data["workday_end_minute"], int)
    assert data["workday_start_minute"] < data["workday_end_minute"]
    assert data["capacity_minutes"] == data["workday_end_minute"] - data["workday_start_minute"]
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_neighborhood(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["floor_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["team_code"] is None or isinstance(data["team_code"], str)
    assert 1 <= data["capacity_cap_pct"] <= 100
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 0
    assert isinstance(data["effective_cap_seats"], int) and data["effective_cap_seats"] >= 0


def assert_seat(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["neighborhood_id"])
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["is_standing"], bool)
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE", "RETIRED")


def assert_room(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["floor_id"])
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["seats_capacity"], int) and data["seats_capacity"] >= 1
    assert isinstance(data["turnover_buffer_minute"], int) and data["turnover_buffer_minute"] >= 0
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE", "RETIRED")


def assert_employee(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["team_code"], str)
    assert isinstance(data["strike_score"], int) and data["strike_score"] >= 0
    assert data["booking_privilege"] in ("ACTIVE", "SUSPENDED")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_reservation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["resource_type"] in ("SEAT", "ROOM")
    assert isinstance(data["booking_date"], str)
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert data["start_minute"] < data["end_minute"]
    assert data["occupancy_status"] in (
        "BOOKED", "CHECKED_IN", "COMPLETED", "NO_SHOW_RELEASED", "CANCELLED")
    assert data["billing_status"] in ("NONE", "PROVISIONAL", "FINALIZED", "VOID")
    assert isinstance(data["provisional_chargeback_cents"], int)
    assert isinstance(data["final_chargeback_cents"], int)
    assert isinstance(data["occupied_minutes"], int)


def assert_check_in(data: dict):
    assert_audit_row_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert isinstance(data["checked_in_at_minute"], int)
    assert isinstance(data["within_grace"], bool)


def assert_amenity_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["reservation_id"])
    assert isinstance(data["amenity_code"], str) and len(data["amenity_code"]) > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_status"] in ("REQUESTED", "APPROVED", "DENIED", "CANCELLED")
    assert data["line_total_cents"] == data["unit_price_cents"] * data["quantity"]


def assert_no_show_event(data: dict):
    assert_audit_row_fields(data)
    assert is_valid_uuid(data["employee_id"])
    assert data["kind"] in ("NO_SHOW", "GOOD_CHECKIN")
    assert isinstance(data["delta"], int)


def assert_capacity_policy(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["floor_id"])
    assert isinstance(data["max_active_reservations_per_employee"], int)
    assert data["max_active_reservations_per_employee"] >= 1
    assert isinstance(data["grace_minutes"], int) and data["grace_minutes"] >= 0
    assert isinstance(data["enforce_team_zoning"], bool)


def assert_visitor_pass(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["host_employee_id"])
    assert is_valid_uuid(data["seat_id"])
    assert isinstance(data["visitor_name"], str) and len(data["visitor_name"]) > 0
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert data["status"] in (
        "REQUESTED", "CHANGES_REQUESTED", "APPROVED", "CHECKED_IN", "COMPLETED", "CANCELLED")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_employee_privilege_consistent(data: dict, suspend_threshold: int = 30):
    """PRD §3.6: booking_privilege is SUSPENDED when strike_score >= 30, else ACTIVE."""
    if data["strike_score"] >= suspend_threshold:
        assert data["booking_privilege"] == "SUSPENDED", \
            f"score {data['strike_score']} >= {suspend_threshold} must be SUSPENDED"
    else:
        assert data["booking_privilege"] == "ACTIVE", \
            f"score {data['strike_score']} < {suspend_threshold} must be ACTIVE"
