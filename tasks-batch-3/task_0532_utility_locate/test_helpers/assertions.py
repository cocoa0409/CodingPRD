"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_excavator(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["state_code"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_member_utility(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["facility_type"] in ("GAS", "ELECTRIC", "WATER", "SEWER", "TELECOM", "OIL")
    poly = data["service_polygon"]
    for k in ("min_x", "min_y", "max_x", "max_y"):
        assert k in poly
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_locate_tech(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["certified_facility_types"], list)
    assert isinstance(data["active_assignment_count"], int)
    assert data["status"] in ("AVAILABLE", "OFF_DUTY")


def assert_locate_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["ticket_type"] in ("NORMAL", "EMERGENCY")
    assert data["status"] in (
        "INTAKE", "SUBMITTED", "RESPONSES_COMPLETE", "MARKED", "CLOSED", "CANCELLED", "EXPIRED",
    )
    assert data["response_posture"] in (
        "INTAKE", "AWAITING_RESPONSES", "ALL_CLEAR", "CONFLICT", "SLA_BREACHED",
    )
    assert isinstance(data["is_white_lined"], bool)
    assert isinstance(data["notified_member_count"], int)
    assert isinstance(data["open_response_count"], int)


def assert_utility_notification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["response_status"] in ("PENDING", "CLEAR", "CONFLICT", "MARKED_BY_OWNER")
    assert isinstance(data["is_high_priority"], bool)


def assert_positive_response(data: dict):
    """PositiveResponse is append-only: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["outcome"] in ("CLEAR", "CONFLICT", "MARKED_BY_OWNER")
    assert isinstance(data["was_late"], bool)
    assert "updated_at" not in data, "PositiveResponse must not carry updated_at"
    assert "version" not in data, "PositiveResponse must not carry version"


def assert_locate_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("DISPATCHED", "EN_ROUTE", "COMPLETED", "CANCELLED", "BREACHED")
    assert isinstance(data["sla_breached"], bool)


def assert_mark_out(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("IN_PROGRESS", "COMPLETE", "SUPERSEDED", "EXPIRED")
    assert isinstance(data["is_refresh"], bool)
    assert isinstance(data["marks_count"], int)


def assert_meet_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("REQUESTED", "SCHEDULED", "COMPLETED", "DECLINED")


def assert_damage_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("FILED", "UNDER_REVIEW", "SETTLED", "DISPUTED")
    assert isinstance(data["repair_cost_cents"], int)
    assert isinstance(data["dug_within_marks"], bool)


def assert_liability_sums_to_cost(data: dict):
    """The two liability shares always sum exactly to repair_cost_cents (PRD §2.10, §3.8)."""
    assert data["excavator_liability_cents"] + data["member_liability_cents"] == data["repair_cost_cents"], (
        "excavator_liability_cents + member_liability_cents must equal repair_cost_cents"
    )
