"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5, §2.9, §2.10)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)

_VETTING_STATUSES = ["APPLIED", "REFERENCES_PENDING", "VETTED", "SUSPENDED", "REMOVED"]
_REFERENCE_STATUSES = ["PENDING", "ACCEPTED", "REJECTED", "WITHDRAWN"]
_REQUEST_STATUSES = ["OPEN", "CLAIMED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "EXPIRED"]
_CLAIM_STATUSES = ["PENDING", "ACCEPTED", "REJECTED", "WITHDRAWN"]
_ASSIGNMENT_STATUSES = [
    "CONFIRMED", "IN_PROGRESS", "COMPLETED_PENDING_REVIEW", "SETTLED",
    "CANCELLED_BY_OWNER", "CANCELLED_BY_SITTER", "DISPUTED",
]
_HANDOFF_STATUSES = ["PENDING", "HANDED_OFF", "RETURNED", "LOST"]
_INCIDENT_STATUSES = ["FILED", "UNDER_REVIEW", "RESOLVED_AT_FAULT", "RESOLVED_NO_FAULT", "DISMISSED"]
_DISPUTE_STATUSES = ["FILED", "MEDIATION", "RESOLVED_UPHELD", "RESOLVED_DISMISSED", "ESCALATED_REMOVAL"]
_ENTRY_TYPES = [
    "SIT_EARNED", "SIT_SPENT", "CANCELLATION_PENALTY",
    "INCIDENT_PENALTY", "MEDIATION_ADJUSTMENT", "JOINING_GRANT",
]
_EVENT_TYPES = ["CHECK_IN", "CHECK_OUT", "INCIDENT_NOTE", "PET_FED", "MEDICATION_GIVEN", "VET_VISIT"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    """Validate a Member response against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["vetting_status"] in _VETTING_STATUSES
    assert isinstance(data["mediator_flag"], bool)
    assert_cost_precision(data["credit_balance_hours"])
    assert_cost_precision(data["provisional_credit_hours"])
    assert_member_invariants(data)


def assert_member_invariants(data: dict):
    """Reliability standing stays clamped to [0, 100] (PRD §2.5)."""
    score = data["reliability_score"]
    assert isinstance(score, int), "reliability_score must be an integer"
    assert 0 <= score <= 100, f"reliability_score {score} outside [0, 100]"


def assert_reference(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _REFERENCE_STATUSES
    assert isinstance(data["relationship_years"], int)
    assert isinstance(data["attestation_text"], str)


def assert_pet_profile(data: dict):
    _assert_common_fields(data)
    assert data["species"] in ["DOG", "CAT", "BIRD", "RABBIT", "OTHER"]
    assert isinstance(data["active"], bool)
    assert isinstance(data["liability_waiver_accepted"], bool)


def assert_holiday_window(data: dict):
    _assert_common_fields(data)
    assert 1.0 <= data["demand_multiplier"] <= 3.0
    assert isinstance(data["enabled"], bool)


def assert_sitting_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _REQUEST_STATUSES
    assert_cost_precision(data["credit_hours_offered"])
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _CLAIM_STATUSES


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _ASSIGNMENT_STATUSES


def assert_handoff(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _HANDOFF_STATUSES


def assert_incident(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _INCIDENT_STATUSES
    assert data["severity"] in ["MINOR", "MAJOR", "EMERGENCY"]


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _DISPUTE_STATUSES
    assert data["dispute_type"] in ["SITTING_QUALITY", "CREDIT_BALANCE", "ACCESS_DAMAGE", "BEHAVIOR"]


def assert_entry_log(data: dict):
    """EntryLog is append-only: id + created_at only, never updated_at/version (PRD §2.9)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "EntryLog must not expose updated_at"
    assert "version" not in data, "EntryLog must not expose version"
    assert data["event_type"] in _EVENT_TYPES


def assert_ledger_entry(data: dict):
    """CreditLedgerEntry is append-only: id + created_at only (PRD §2.9)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CreditLedgerEntry must not expose updated_at"
    assert "version" not in data, "CreditLedgerEntry must not expose version"
    assert data["entry_type"] in _ENTRY_TYPES
    assert_cost_precision(data["delta_hours"])
