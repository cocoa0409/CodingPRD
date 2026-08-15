"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_nonprofit_partner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["reputation_score"] is None or isinstance(data["reputation_score"], (int, float))
    assert isinstance(data["survey_count"], int)
    assert isinstance(data["completed_event_count"], int)


def assert_service_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in (
        "PLANNING", "REGISTRATION_OPEN", "REGISTRATION_LOCKED",
        "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED",
    )
    assert data["readiness_posture"] in ("BLOCKED", "PARTIAL", "READY")
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 0
    assert isinstance(data["waiver_document_version"], int) and data["waiver_document_version"] >= 1
    assert isinstance(data["projected_spend_cents"], int)
    assert isinstance(data["committed_spend_cents"], int)
    assert isinstance(data["available_budget_cents"], int)
    assert isinstance(data["sponsorship_credit_cents"], int)
    assert isinstance(data["net_event_cost_cents"], int)
    assert isinstance(data["registered_headcount"], int)
    assert isinstance(data["confirmed_headcount"], int)
    assert isinstance(data["checked_in_headcount"], int)
    assert isinstance(data["total_scheduled_hours"], (int, float))
    assert isinstance(data["total_verified_hours"], (int, float))
    assert isinstance(data["repeat_booking_bonus"], bool)


def assert_service_project(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("nonprofit_id", "")), "nonprofit_id must be a UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in ("PROPOSED", "VETTED", "MATCHED", "LOCKED", "COMPLETED", "CANCELLED")
    assert isinstance(data["min_volunteers"], int) and data["min_volunteers"] >= 1
    assert isinstance(data["max_volunteers"], int)
    assert isinstance(data["confirmed_volunteer_count"], int)
    assert isinstance(data["required_staff_leads"], int)
    assert isinstance(data["active_staff_leads"], int)
    assert isinstance(data["site_prep_complete"], bool)


def assert_employee_volunteer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["department"], str)
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["is_staff_lead"], bool)


def assert_registration(data: dict):
    _assert_common_fields(data)
    assert data["rsvp_status"] in ("REGISTERED", "CONFIRMED", "CHECKED_IN", "CANCELLED", "NO_SHOW")
    assert data["waiver_status"] in ("WAIVER_PENDING", "WAIVER_SIGNED", "WAIVER_VERIFIED", "WAIVER_VOIDED")
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["media_consent"], bool)
    assert isinstance(data["wants_transport"], bool)
    assert isinstance(data["wants_meal"], bool)
    assert isinstance(data["scheduled_hours_credit"], (int, float))
    assert isinstance(data["verified_hours_credit"], (int, float))


def assert_procurement_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "RECEIVED", "REJECTED", "CANCELLED")
    assert isinstance(data["order_total_cents"], int)
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert isinstance(data["created_by_user_id"], str)


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1


def assert_transport_manifest(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("BOOKED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert isinstance(data["assigned_seats"], int)


def assert_meal_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_name"], str) and len(data["vendor_name"]) > 0
    assert isinstance(data["per_person_cost_cents"], int) and data["per_person_cost_cents"] >= 1
    assert data["status"] in ("DRAFT", "ORDERED", "FULFILLED", "CANCELLED")


def assert_supervision_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "WITHDRAWN")


def assert_sponsorship(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sponsor_name"], str) and len(data["sponsor_name"]) > 0
    assert data["match_type"] in ("FLAT", "PER_CHECK_IN", "PER_VERIFIED_HOUR")
    assert isinstance(data["rate_cents"], int) and data["rate_cents"] >= 1
    assert isinstance(data["pledge_cap_cents"], int) and data["pledge_cap_cents"] >= 1
    assert data["status"] in ("PLEDGED", "COMMITTED", "SETTLED", "WITHDRAWN")
    assert isinstance(data["effective_cap_cents"], int)
    assert isinstance(data["provisional_amount_cents"], int)


def assert_impact_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["hours_attended"], (int, float)) and data["hours_attended"] > 0
    assert data["status"] in ("SUBMITTED", "VERIFIED", "PUBLISHED", "REJECTED")
    assert isinstance(data["photo_count"], int) and data["photo_count"] >= 0


def assert_feedback_survey(data: dict):
    """Append-only entity: id + created_at present; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "feedback survey must not carry updated_at"
    assert "version" not in data, "feedback survey must not carry version"
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert isinstance(data["would_repeat"], bool)


def assert_event_spend_invariants(data: dict):
    """available_budget_cents == budget_cents - projected_spend_cents (PRD §2.8)."""
    assert data["available_budget_cents"] == data["budget_cents"] - data["projected_spend_cents"], (
        f"available {data['available_budget_cents']} != budget {data['budget_cents']} "
        f"- projected {data['projected_spend_cents']}"
    )
