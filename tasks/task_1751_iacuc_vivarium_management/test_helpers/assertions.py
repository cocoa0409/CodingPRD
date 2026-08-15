"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _assert_common_fields(data: dict):
    """Common system-managed fields present on every resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_investigator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["department"], str) and data["department"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DEACTIVATED")


def assert_grant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["grant_number"], str) and data["grant_number"]
    assert is_valid_uuid(data["investigator_id"])
    assert isinstance(data["budget_total_cents"], int)
    assert isinstance(data["budget_remaining_cents"], int)
    assert data["budget_total_cents"] >= 0
    assert is_iso8601_timestamp(data["expires_on"])


def assert_personnel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["role_on_protocols"] in ("TECHNICIAN", "CO_PI", "STUDENT")
    assert isinstance(data["training_completed"], bool)
    assert isinstance(data["occ_health_cleared"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_training_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["personnel_id"])
    assert data["course_code"] in (
        "ANIMAL_HANDLING", "ASEPTIC_TECHNIQUE", "EUTHANASIA", "SPECIES_SPECIFIC",
    )
    assert data["state"] in ("ENROLLED", "COMPLETED", "EXPIRED")
    if data["state"] == "ENROLLED":
        assert data.get("expires_at") is None, "expires_at null until COMPLETED"
    else:
        assert is_iso8601_timestamp(data["completed_at"])
        assert is_iso8601_timestamp(data["expires_at"])


def assert_occ_health_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["personnel_id"])
    assert data["state"] in ("ENROLLED", "CLEARED", "EXPIRED")
    if data["state"] == "ENROLLED":
        assert data.get("expires_at") is None, "expires_at null until CLEARED"
    else:
        assert is_iso8601_timestamp(data["cleared_at"])
        assert is_iso8601_timestamp(data["expires_at"])


def assert_protocol(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["protocol_number"], str) and data["protocol_number"]
    assert is_valid_uuid(data["investigator_id"])
    assert is_valid_uuid(data["grant_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["species"] in ("MOUSE", "RAT", "RABBIT", "ZEBRAFISH")
    assert isinstance(data["max_animals_justified"], int)
    assert data["max_animals_justified"] > 0
    assert data["pain_category"] in ("B", "C", "D", "E")
    assert data["review_path"] in ("DMR", "FCR")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "DMR_REVIEW", "FCR_REVIEW",
        "APPROVED", "SUSPENDED", "EXPIRED", "WITHDRAWN",
    )
    assert isinstance(data["animals_used_count"], int)
    assert data["animals_used_count"] >= 0


def assert_protocol_reviewer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["protocol_id"])
    assert data["reviewer_kind"] in ("DESIGNATED_MEMBER", "COMMITTEE_MEMBER")
    assert data["decision"] in (
        "PENDING", "APPROVE", "REQUIRE_MODIFICATIONS", "WITHHOLD",
    )


def assert_cage(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cage_barcode"], str) and data["cage_barcode"]
    assert isinstance(data["room_code"], str) and data["room_code"]
    assert data["species"] in ("MOUSE", "RAT", "RABBIT", "ZEBRAFISH")
    assert data["cage_kind"] in ("STANDARD", "BREEDING")
    assert isinstance(data["capacity_adults"], int) and data["capacity_adults"] > 0
    assert data["status"] in ("EMPTY", "OCCUPIED", "OVER_CAPACITY", "DECOMMISSIONED")
    assert is_valid_uuid(data["protocol_id"])


def assert_animal(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["animal_tag"], str) and data["animal_tag"]
    assert is_valid_uuid(data["cage_id"])
    assert is_valid_uuid(data["protocol_id"])
    assert data["species"] in ("MOUSE", "RAT", "RABBIT", "ZEBRAFISH")
    assert is_iso8601_timestamp(data["date_of_birth"])
    assert data["sex"] in ("M", "F")
    assert data["status"] in ("ALIVE", "RETIRED", "EUTHANIZED", "TRANSFERRED_OUT")


def assert_litter(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["cage_id"])
    assert is_valid_uuid(data["protocol_id"])
    assert is_iso8601_timestamp(data["born_on"])
    assert isinstance(data["pup_count"], int) and data["pup_count"] > 0
    assert isinstance(data["weaned_count"], int) and data["weaned_count"] >= 0
    assert data["state"] in ("NURSING", "WEANED", "CLOSED")


def assert_census_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["cage_id"])
    assert is_iso8601_timestamp(data["census_date"])
    assert isinstance(data["physical_count"], int) and data["physical_count"] >= 0
    assert isinstance(data["system_count"], int)
    assert isinstance(data["discrepancy"], int)
    assert data["discrepancy"] == data["physical_count"] - data["system_count"], (
        "discrepancy must equal physical_count - system_count (PRD §3.6)"
    )


def assert_billing_run(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert parse_instant(data["period_end"]) > parse_instant(data["period_start"])
    assert data["state"] in ("DRAFT", "PROVISIONAL", "FINALIZED", "POSTED", "VOIDED")


def assert_per_diem_charge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_run_id"])
    assert is_valid_uuid(data["cage_id"])
    assert is_valid_uuid(data["protocol_id"])
    assert is_valid_uuid(data["grant_id"])
    assert isinstance(data["cage_days"], int) and data["cage_days"] >= 0
    assert isinstance(data["rate_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["variant"] in ("PROVISIONAL", "FINAL")


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert data["inspection_kind"] in ("FACILITY", "PROGRAM_REVIEW")
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert is_iso8601_timestamp(data["due_by"])
    assert data["state"] in ("SCHEDULED", "COMPLETED", "LAPSED")
    assert isinstance(data["deficiency_count"], int)
    assert data["deficiency_count"] >= 0


def assert_adverse_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["protocol_id"])
    assert is_valid_uuid(data["animal_id"])
    assert is_valid_uuid(data["reported_by_personnel_id"])
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE", "MORBUND")
    assert isinstance(data["description"], str)
    assert data["state"] in ("OPEN", "UNDER_TREATMENT", "RESOLVED", "ESCALATED")
    assert is_iso8601_timestamp(data["reported_at"])


def assert_protocol_deviation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["protocol_id"])
    assert is_valid_uuid(data["reported_by_personnel_id"])
    assert isinstance(data["description"], str)
    assert data["seriousness"] in ("MINOR", "SERIOUS")
    assert data["state"] in (
        "REPORTED", "UNDER_REVIEW", "CLOSED", "SUSPENSION_IMPOSED",
    )


def assert_room_booking(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["room_code"], str) and data["room_code"]
    assert is_valid_uuid(data["protocol_id"])
    assert is_valid_uuid(data["booked_by_personnel_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["state"] in ("CONFIRMED", "CANCELLED")


def assert_grant_invariant(grant: dict, posted_amounts: list):
    """budget_remaining_cents == budget_total_cents - sum(POSTED charges).

    PRD §3.1 / §3.7: the remaining budget falls only as posted per-diem
    charges debit it.
    """
    expected = grant["budget_total_cents"] - sum(posted_amounts)
    assert grant["budget_remaining_cents"] == expected, (
        f"budget invariant violated: remaining {grant['budget_remaining_cents']} "
        f"!= total {grant['budget_total_cents']} - posted {sum(posted_amounts)}"
    )
