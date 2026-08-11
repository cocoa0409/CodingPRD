"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §2.10)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_frc_event(data: dict):
    _assert_common_fields(data)
    for field in ("event_code", "event_name", "status", "posture"):
        assert isinstance(data.get(field), str) and data[field], f"{field} must be a non-empty string"
    for field in ("season_year", "team_capacity", "match_cycle_minutes", "field_count",
                  "championship_slots", "registered_team_count", "cleared_mentor_count",
                  "outstanding_violation_count"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert data["status"] in (
        "SETUP", "REGISTRATION_OPEN", "REGISTRATION_LOCKED", "BUILD_SEASON",
        "INSPECTION", "MATCHES_RUNNING", "ALLIANCE_SELECTION", "AWARDS", "CLOSED",
    )
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")


def assert_team(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("team_number"), int) and data["team_number"] > 0
    assert isinstance(data.get("nickname"), str) and data["nickname"]
    assert isinstance(data.get("event_id"), str)
    assert data.get("registration_status") in (
        "PENDING_PAYMENT", "PAYMENT_CLEARED", "ROSTER_SUBMITTED",
        "CONFIRMED", "WITHDRAWN", "DISQUALIFIED",
    )
    assert data.get("robot_inspection_status") in (
        "NOT_SUBMITTED", "SUBMITTED", "PASSED", "FAILED", "WAIVED",
    )


def assert_person(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert data.get("role_kind") in ("MENTOR", "VOLUNTEER", "JUDGE", "STUDENT")
    assert data.get("screening_status") in ("PENDING", "IN_REVIEW", "CLEARED", "REJECTED", "EXPIRED")


def assert_screening_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("person_id"), str)
    assert data.get("submission_channel") in ("FIRST_YPP", "VENDOR_API", "MANUAL_UPLOAD")
    assert data.get("decision") in ("PENDING", "APPROVE", "REJECT", "EXPIRE")


def assert_milestone(data: dict):
    _assert_common_fields(data)
    assert data.get("kind") in ("KICKOFF", "STOP_BUILD", "BAG_DAY", "SHIP_DATE", "UNBAG_WINDOW")
    assert data.get("status") in ("SCHEDULED", "ARMED", "PASSED", "CANCELLED")
    assert isinstance(data.get("window_minutes"), int)


def assert_part_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("sku"), str) and data["sku"]
    assert isinstance(data.get("quantity"), int) and data["quantity"] > 0
    assert isinstance(data.get("unit_cost_cents"), int) and data["unit_cost_cents"] >= 0
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "APPROVED", "VENDOR_PLACED", "RECEIVED", "REJECTED", "CANCELLED",
    )
    assert isinstance(data.get("order_total_cents"), int)
    assert data["order_total_cents"] == data["quantity"] * data["unit_cost_cents"], (
        "order_total_cents is quantity * unit_cost_cents (PRD §2.10)"
    )


def assert_robot_inspection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("inspector_id"), str)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "PASSED", "FAILED", "SUPERSEDED")


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert data.get("source_kind") in ("INSPECTION", "MATCH_REVIEW", "FIELD_SAFETY", "JUDGE_REFERRAL")
    assert data.get("severity") in ("MINOR", "MAJOR", "CRITICAL")
    assert data.get("resolution_status") in ("OPEN", "ACKED", "RESOLVED", "ESCALATED")


def assert_match(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("match_number"), int) and data["match_number"] >= 1
    assert data.get("series") in ("QUALIFICATION", "PLAYOFF")
    assert data.get("status") in (
        "SCHEDULED", "QUEUED", "ON_FIELD", "SCORED", "FINALIZED", "REPLAYED", "CANCELLED",
    )


def assert_alliance(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("captain_team_id"), str)
    assert data.get("status") in ("FORMING", "SEALED", "ELIMINATED", "CHAMPION")


def assert_selection_round(data: dict):
    _assert_common_fields(data)
    assert data.get("round_index") in (1, 2)
    assert data.get("status") in ("PENDING", "OPEN", "COMPLETE")


def assert_score_breakdown(data: dict):
    """MatchScoreBreakdown carries only id + created_at (no updated_at/version)."""
    _assert_common_fields(data, with_version=False)
    assert "updated_at" not in data or data.get("updated_at") is None
    assert data.get("alliance_color") in ("RED", "BLUE")
    for field in ("auto_points", "teleop_points", "endgame_points",
                  "foul_points_awarded", "tech_foul_count"):
        assert isinstance(data.get(field), int) and data[field] >= 0
    assert data.get("card_issued") in ("NONE", "YELLOW", "RED")


def assert_queue_slot(data: dict):
    _assert_common_fields(data)
    assert data.get("position") in ("RED_1", "RED_2", "RED_3", "BLUE_1", "BLUE_2", "BLUE_3")
    assert data.get("status") in ("STAGED", "AT_FIELD", "ON_FIELD", "RELEASED", "NO_SHOW")


def assert_field_reset_log(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("field_index"), int)
    assert data.get("status") in ("IN_PROGRESS", "COMPLETE", "ABORTED")


def assert_award(data: dict):
    _assert_common_fields(data)
    assert data.get("award_kind") in (
        "CHAIRMANS", "ENGINEERING_INSPIRATION", "ROOKIE_ALL_STAR", "WOODIE_FLOWERS",
        "DEANS_LIST", "SAFETY", "CREATIVITY", "QUALITY", "INNOVATION", "GRACIOUS_PROFESSIONALISM",
    )
    assert data.get("status") in ("OPEN", "JUDGING", "DECIDED", "PRESENTED")


def assert_interview_slot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("duration_minutes"), int) and data["duration_minutes"] >= 5
    assert data.get("status") in ("PROPOSED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_travel_booking(data: dict):
    _assert_common_fields(data)
    assert data.get("mode") in ("AIR", "RAIL", "BUS", "SELF_DRIVE")
    assert isinstance(data.get("cost_cents"), int) and data["cost_cents"] >= 0
    assert data.get("reimbursement_status") in ("PENDING", "APPROVED", "PAID", "DENIED")
