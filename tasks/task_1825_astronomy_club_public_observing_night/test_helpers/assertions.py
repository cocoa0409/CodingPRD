"""Entity assertions and domain invariant checkers.

Every assert_* validates the system-managed fields and the entity-specific
field types the PRD guarantees. DuesPayment and SkyQualityReading are
append-only: they must NOT carry updated_at or version.
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# Canonical enum value sets for membership checks
_MEMBER_STATUSES = {"ACTIVE", "SUSPENDED", "LAPSED", "RESIGNED"}
_INVOICE_STATUSES = {"OPEN", "PAID", "VOID"}
_TELESCOPE_STATUSES = {"AVAILABLE", "RESERVED", "ON_LOAN", "MAINTENANCE", "RETIRED"}
_CERT_STATUSES = {"ACTIVE", "EXPIRED", "REVOKED"}
_LOAN_STATUSES = {"RESERVED", "CHECKED_OUT", "RETURNED", "OVERDUE", "CANCELLED"}
_TICKET_STATUSES = {"OPEN", "IN_PROGRESS", "VERIFICATION", "CLOSED"}
_EVENT_STATUSES = {"DRAFT", "SCHEDULED", "CONFIRMED", "CANCELLED", "COMPLETED"}
_ASSIGNMENT_STATUSES = {"INVITED", "CONFIRMED", "DECLINED", "NO_SHOW", "WITHDRAWN"}
_BOOKING_STATUSES = {"PENDING", "CONFIRMED", "CANCELLED", "COMPLETED", "NO_SHOW"}
_REPORT_STATUSES = {"OPEN", "FINALIZED"}
_EQUIPMENT_CLASSES = {"REFRACTOR", "REFLECTOR", "SCT", "DOBSONIAN", "SOLAR_SCOPE"}
_TIER_CODES = {"STUDENT", "INDIVIDUAL", "FAMILY", "PATRON"}
_EVENT_KINDS = {"PUBLIC_NIGHT", "MEMBER_NIGHT", "SOLAR_SESSION"}
_GRADES = {"A", "B", "C", "D", "F"}


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer")


def assert_membership_tier(data):
    _assert_common_fields(data, "MembershipTier")
    assert data["code"] in _TIER_CODES
    assert isinstance(data["annual_dues_cents"], int)
    assert data["annual_dues_cents"] >= 0
    assert data["observatory_access_level"] in (1, 2, 3)
    assert isinstance(data["loan_privilege"], bool)
    assert isinstance(data["max_concurrent_loans"], int)
    assert data["max_concurrent_loans"] >= 0


def assert_member(data):
    _assert_common_fields(data, "Member")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert is_valid_uuid(data.get("tier_id", "")), "Member.tier_id must be a UUID"
    assert data["status"] in _MEMBER_STATUSES
    assert is_iso8601_timestamp(data.get("joined_at", "")), (
        "Member.joined_at must be ISO 8601")
    assert isinstance(data["effective_access_level"], int)
    assert data["effective_access_level"] in (0, 1, 2, 3)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_dues_invoice(data):
    _assert_common_fields(data, "DuesInvoice")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in _INVOICE_STATUSES


def assert_dues_payment(data):
    # Append-only record: id + created_at only — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "DuesPayment.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "DuesPayment is append-only: no updated_at"
    assert "version" not in data, "DuesPayment is append-only: no version"
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert is_iso8601_timestamp(data.get("posted_at", ""))
    assert isinstance(data["credit_applied_cents"], int)
    assert data["credit_applied_cents"] >= 0


def assert_telescope(data):
    _assert_common_fields(data, "Telescope")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["equipment_class"] in _EQUIPMENT_CLASSES
    assert data["status"] in _TELESCOPE_STATUSES
    assert is_iso8601_timestamp(data.get("collimation_due_at", ""))
    assert isinstance(data["condition_score"], int)
    assert 0 <= data["condition_score"] <= 100


def assert_training_certification(data):
    _assert_common_fields(data, "TrainingCertification")
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["equipment_class"] in _EQUIPMENT_CLASSES
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["status"] in _CERT_STATUSES


def assert_loan_reservation(data):
    _assert_common_fields(data, "LoanReservation")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("telescope_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in _LOAN_STATUSES
    assert isinstance(data["overdue_fees_cents"], int)
    assert data["overdue_fees_cents"] >= 0


def assert_maintenance_ticket(data):
    _assert_common_fields(data, "MaintenanceTicket")
    assert is_valid_uuid(data.get("telescope_id", ""))
    assert data["kind"] in {"COLLIMATION", "REPAIR", "CLEANING"}
    assert data["severity"] in {"LOW", "MEDIUM", "HIGH"}
    assert data["status"] in _TICKET_STATUSES
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert isinstance(data["condition_delta"], int)


def assert_observing_event(data):
    _assert_common_fields(data, "ObservingEvent")
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["event_kind"] in _EVENT_KINDS
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in _EVENT_STATUSES
    assert isinstance(data["moon_illumination_pct"], int)
    assert 0 <= data["moon_illumination_pct"] <= 100
    assert isinstance(data["weather_cancellation_pct"], int)
    assert 0 <= data["weather_cancellation_pct"] <= 100
    assert isinstance(data["min_operators"], int) and data["min_operators"] >= 1
    assert isinstance(data["confirmed_operator_count"], int)
    assert data["confirmed_operator_count"] >= 0


def assert_operator_assignment(data):
    _assert_common_fields(data, "EventOperatorAssignment")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("telescope_id", ""))
    assert data["status"] in _ASSIGNMENT_STATUSES
    assert is_iso8601_timestamp(data.get("invited_at", ""))


def assert_group_visit_booking(data):
    _assert_common_fields(data, "GroupVisitBooking")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["group_name"], str) and len(data["group_name"]) > 0
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert is_valid_uuid(data.get("contact_member_id", ""))
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in _BOOKING_STATUSES


def assert_sky_quality_reading(data):
    # Append-only record: id + created_at only — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), (
        "SkyQualityReading.id must be a valid UUID")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, (
        "SkyQualityReading is append-only: no updated_at")
    assert "version" not in data, "SkyQualityReading is append-only: no version"
    assert is_valid_uuid(data.get("taken_by_member_id", ""))
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["sqm_value"], (int, float))
    assert 10.00 <= data["sqm_value"] <= 22.99
    assert is_iso8601_timestamp(data.get("taken_at", ""))


def assert_dark_sky_report(data):
    _assert_common_fields(data, "DarkSkyReport")
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["status"] in _REPORT_STATUSES
    assert isinstance(data["reading_count"], int) and data["reading_count"] >= 0
    if data.get("median_sqm") is not None:
        assert isinstance(data["median_sqm"], (int, float))
        assert data["advocacy_grade"] in _GRADES
