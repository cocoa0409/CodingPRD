"""Entity assertions and domain invariant checkers (PRD §2.5, §2.10, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Instant comparison (representations may differ in fractional digits; PRD
# §2.10 pins instants to ISO 8601 UTC with three fractional digits, but tests
# compare the instant, not the string rendering).
# ---------------------------------------------------------------------------

def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instants_equal(actual: str, expected: str) -> None:
    """Compare two ISO 8601 instants semantically."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def _assert_common_fields(data: dict) -> None:
    """PRD §2.5: id, created_at, updated_at, version on every primary resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_handler(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ["APPLICANT", "ACTIVE", "SUSPENDED", "RETIRED", "REJECTED"]
    assert isinstance(data["lifetime_minutes"], int) and data["lifetime_minutes"] >= 0
    assert data["recognition_tier"] in ["NONE", "BRONZE", "SILVER", "GOLD", "PLATINUM"]


def assert_animal(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("handler_id", "")), "handler_id must be a UUID"
    assert data["species"] in ["DOG", "CAT", "RABBIT", "GUINEA_PIG", "BIRD", "MINIATURE_HORSE"]
    assert data["status"] in ["REGISTERED", "ACTIVE", "WELFARE_HOLD", "RETIRED"]
    assert isinstance(data["forward_workload_minutes"], int)
    assert isinstance(data["audit_workload_minutes"], int)


def assert_team(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("handler_id", "")), "handler_id must be a UUID"
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be a UUID"
    assert data["status"] in ["FORMING", "ACTIVE", "SUSPENDED", "DISSOLVED"]
    for counter in ("late_cancel_count", "no_show_count", "warning_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_evaluator(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["specializations"], list) and len(data["specializations"]) > 0
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_evaluation(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert data["status"] in [
        "REQUESTED", "SCHEDULED", "PASSED", "FAILED", "APPEALED", "CANCELLED", "EXPIRED",
    ]
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1


def assert_certification(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert data["status"] in [
        "PROVISIONAL", "ACTIVE", "RENEWAL_DUE", "SUSPENDED", "EXPIRED", "REVOKED",
    ]


def assert_vaccination_record(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("animal_id", "")), "animal_id must be a UUID"
    assert data["vaccine_type"] in [
        "RABIES", "DISTEMPER", "BORDETELLA", "CANINE_INFLUENZA", "FELINE_FVRCP",
    ]
    assert data["status"] in ["VALID", "EXPIRED", "VOIDED"]


def assert_facility(data: dict) -> None:
    _assert_common_fields(data)
    assert data["facility_type"] in ["HOSPITAL", "SCHOOL", "NURSING_HOME", "REHAB_CENTER", "HOSPICE"]
    assert isinstance(data["allowed_species"], list) and len(data["allowed_species"]) > 0
    assert data["status"] in ["PROSPECT", "ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_facility_agreement(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert data["status"] in [
        "DRAFT", "PENDING_FACILITY_SIGNATURE", "PENDING_PROGRAM_SIGNATURE",
        "ACTIVE", "EXPIRED", "TERMINATED", "WITHDRAWN",
    ]


def assert_orientation_record(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert data["status"] in ["ASSIGNED", "COMPLETED", "EXPIRED"]


def assert_insurance_policy(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("handler_id", "")), "handler_id must be a UUID"
    assert isinstance(data["coverage_cents"], int) and data["coverage_cents"] > 0
    assert data["status"] in ["PENDING", "ACTIVE", "EXPIRED", "CANCELLED"]


def assert_liability_waiver(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert data["status"] in ["SIGNED", "VOIDED"]


def assert_visit_request(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert data["visit_program"] in ["READING", "REHAB", "STRESS_RELIEF", "GENERAL"]
    assert data["priority"] in ["ROUTINE", "HIGH", "URGENT"]
    assert data["status"] in ["OPEN", "OFFERED", "ACCEPTED", "FULFILLED", "WITHDRAWN", "EXPIRED"]
    assert isinstance(data["decline_count"], int) and data["decline_count"] >= 0


def assert_visit(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("team_id", "")), "team_id must be a UUID"
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert data["lifecycle_status"] in [
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW",
    ]
    assert data["verification_status"] in ["UNVERIFIED", "VERIFIED", "DISPUTED"]


def assert_incident_report(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("visit_id", "")), "visit_id must be a UUID"
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["category"] in [
        "ANIMAL_STRESS", "BITE_SCRATCH", "INJURY", "PROPERTY_DAMAGE", "PROTOCOL_BREACH",
    ]
    assert data["status"] in ["FILED", "UNDER_REVIEW", "ESCALATED", "RESOLVED"]


def assert_hour_credit(data: dict) -> None:
    """Ledger rows are immutable (PRD §2.5): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "HourCredit must NOT carry updated_at"
    assert "version" not in data, "HourCredit must NOT carry version"
    assert is_valid_uuid(data.get("handler_id", "")), "handler_id must be a UUID"
    assert data["kind"] in ["PROVISIONAL", "FINAL", "REVERSAL", "ADJUSTMENT"]
    assert isinstance(data["minutes"], int)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_recognition_summary(data: dict, handler_id: str) -> None:
    """PRD §3.8 recognition summary shape."""
    assert data["handler_id"] == handler_id
    assert isinstance(data["lifetime_minutes"], int) and data["lifetime_minutes"] >= 0
    assert isinstance(data["lifetime_hours"], (int, float))
    assert data["recognition_tier"] in ["NONE", "BRONZE", "SILVER", "GOLD", "PLATINUM"]
    assert isinstance(data["next_tier"], str)
    assert isinstance(data["minutes_to_next_tier"], int)


def assert_demand_summary(data: dict, facility_id: str) -> None:
    """PRD §3.8 demand summary shape."""
    assert data["facility_id"] == facility_id
    for field in ("open_request_count", "expired_last_90d", "fulfilled_last_90d",
                  "unmet_demand_index"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_ledger_consistency(rows: list, expected_lifetime: int) -> None:
    """The handler's derived lifetime equals the algebraic ledger sum (PRD §2.9)."""
    total = sum(row["minutes"] for row in rows)
    assert total == expected_lifetime, (
        f"Ledger sum {total} != expected lifetime {expected_lifetime}"
    )
