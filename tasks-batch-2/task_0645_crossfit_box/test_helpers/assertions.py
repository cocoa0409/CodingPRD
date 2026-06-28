"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_membership_plan(data: dict):
    _common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["plan_type"] in ("UNLIMITED", "PUNCH")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_member(data: dict):
    _common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["home_box_member"], bool)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert isinstance(data["reservation_suspended"], bool)


def assert_membership(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in (
        "PENDING_PAYMENT", "ACTIVE", "FROZEN", "CANCEL_PENDING", "CANCELLED",
    )


def assert_coach(data: dict):
    _common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["certified"], bool)


def assert_program_track(data: dict):
    _common_fields(data)
    assert isinstance(data["name"], str)
    assert data["track_type"] in ("FOUNDATIONS", "REGULAR", "COMPETITION")
    assert is_valid_uuid(data["head_coach_id"])


def assert_class_session(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["track_id"])
    assert is_valid_uuid(data["coach_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 1
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] in ("SCHEDULED", "CANCELLED", "COMPLETED")
    assert isinstance(data["seats_reserved"], int) and data["seats_reserved"] >= 0
    assert isinstance(data["waitlist_count"], int) and data["waitlist_count"] >= 0


def assert_reservation(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["reservation_kind"] in ("MEMBERSHIP", "DROP_IN")
    assert data["status"] in (
        "RESERVED", "WAITLISTED", "CANCELLED", "NO_SHOW", "ATTENDED",
    )
    assert isinstance(data["punch_consumed"], bool)


def assert_benchmark_result(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["benchmark_name"] in (
        "FRAN", "GRACE", "MURPH", "BACK_SQUAT_1RM", "DEADLIFT_1RM",
    )
    assert data["metric_kind"] in ("TIME_SECONDS", "LOAD_KG")
    assert data["value"] > 0
    assert isinstance(data["verified"], bool)
    assert isinstance(data["is_pr"], bool)


def assert_competition_team(data: dict):
    _common_fields(data)
    assert isinstance(data["name"], str)
    assert is_valid_uuid(data["captain_member_id"])
    assert isinstance(data["max_roster_size"], int) and data["max_roster_size"] >= 1
    assert isinstance(data["roster_size"], int)
    assert data["status"] in ("FORMING", "LOCKED", "DISBANDED")


def assert_team_member(data: dict):
    _common_fields(data)
    assert is_valid_uuid(data["team_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in ("INVITED", "ACCEPTED", "DECLINED", "REMOVED")


# --- Domain invariant checkers --------------------------------------------

def assert_seat_count_consistent(session: dict, expected_seats_reserved: int):
    """ClassSession.seats_reserved equals the count of RESERVED reservation rows."""
    assert session["seats_reserved"] == expected_seats_reserved, (
        f"Expected seats_reserved={expected_seats_reserved}, "
        f"got {session['seats_reserved']}"
    )
