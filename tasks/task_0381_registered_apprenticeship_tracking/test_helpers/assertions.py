"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the structural contract the PRD promises for a
response object: server-minted UUID id, ISO 8601 timestamps, the common fields
where the entity carries them, and field types. The two immutable artifacts
(certificate, EEO report) are checked to NOT expose updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_PROGRAM_STATES = {"DRAFT", "ACTIVE", "ARCHIVED"}
_JW_STATES = {"PROBATIONARY", "QUALIFIED", "INACTIVE"}
_AGREEMENT_STATES = {"DRAFT", "REGISTERED", "ACTIVE", "SUSPENDED", "COMPLETED", "CANCELLED"}
_OJT_STATES = {"PENDING", "APPROVED", "REJECTED"}
_ATTAINMENT_STATES = {"SUBMITTED", "APPROVED", "REJECTED"}
_COMPLETION_TYPES = {"HOURS_BASED", "COMPETENCY_BASED", "HYBRID"}
_GENDERS = {"MALE", "FEMALE", "NONBINARY", "UNDISCLOSED"}
_RACES = {"HISPANIC", "WHITE", "BLACK", "ASIAN", "NATIVE_AMERICAN",
          "PACIFIC_ISLANDER", "TWO_OR_MORE", "UNDISCLOSED"}


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_artifact_fields(data: dict):
    """Immutable artifact: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable artifact must not expose a version field"
    assert "updated_at" not in data, "immutable artifact must not expose an updated_at field"


def assert_sponsor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ein"], str) and data["ein"]
    assert isinstance(data["contact_email"], str)


def assert_program(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sponsor_id"])
    assert data["completion_type"] in _COMPLETION_TYPES
    assert data["status"] in _PROGRAM_STATES
    assert isinstance(data["ojt_hours_required"], int)
    assert isinstance(data["rti_hours_required"], int)
    assert isinstance(data["base_journeyworker_wage_cents"], int)
    assert isinstance(data["journeyman_ratio"], int) and data["journeyman_ratio"] >= 1
    assert isinstance(data["active_agreement_count"], int) and data["active_agreement_count"] >= 0
    assert isinstance(data["available_apprentice_slots"], int) and data["available_apprentice_slots"] >= 0


def assert_wage_step(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["step_number"], int) and data["step_number"] >= 1
    assert isinstance(data["ojt_hours_threshold"], int) and data["ojt_hours_threshold"] >= 0
    assert isinstance(data["wage_pct"], (int, float))


def assert_milestone(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["title"], str)
    assert isinstance(data["required_for_completion"], bool)


def assert_journeyworker(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sponsor_id"])
    assert isinstance(data["full_name"], str)
    assert data["status"] in _JW_STATES
    assert isinstance(data["active_apprentice_count"], int) and data["active_apprentice_count"] >= 0


def assert_apprentice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["sponsor_id"])
    assert isinstance(data["full_name"], str)
    assert data["gender"] in _GENDERS
    assert data["race_ethnicity"] in _RACES
    assert isinstance(data["is_veteran"], bool)
    assert isinstance(data["has_disability"], bool)


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["apprentice_id"])
    assert is_valid_uuid(data["journeyworker_id"])
    assert data["status"] in _AGREEMENT_STATES
    assert isinstance(data["current_wage_step"], int) and data["current_wage_step"] >= 1
    assert isinstance(data["current_hourly_wage_cents"], int)
    assert isinstance(data["milestones_attained_count"], int) and data["milestones_attained_count"] >= 0
    assert isinstance(data["completion_eligible"], bool)
    assert isinstance(data["ojt_hours_completed"], (int, float))
    assert isinstance(data["rti_hours_completed"], (int, float))


def assert_ojt_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["status"] in _OJT_STATES
    assert isinstance(data["start_time"], int)
    assert isinstance(data["end_time"], int)
    assert isinstance(data["credited_hours"], (int, float))


def assert_rti_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["status"] == "RECORDED"
    assert isinstance(data["instruction_hours"], (int, float))


def assert_milestone_attainment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["milestone_id"])
    assert data["status"] in _ATTAINMENT_STATES


def assert_certificate(data: dict):
    _assert_artifact_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["occupation_code"], str)
    assert isinstance(data["certified_ojt_hours"], (int, float))
    assert isinstance(data["certified_rti_hours"], (int, float))


def assert_eeo_report(data: dict):
    _assert_artifact_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["cohort_basis"] in {"REGISTERED_COHORT", "ACTIVE_COHORT"}
    assert isinstance(data["total_apprentices"], int) and data["total_apprentices"] >= 0
    assert isinstance(data["completed_count"], int) and data["completed_count"] >= 0
    assert isinstance(data["completion_rate_pct"], (int, float))
    assert isinstance(data["gender_distribution_pct"], dict)
    assert isinstance(data["race_distribution_pct"], dict)
    assert isinstance(data["veteran_count"], int)
    assert isinstance(data["disability_count"], int)


def assert_distribution_sums_to_100(dist: dict):
    """A non-empty largest-remainder distribution map must sum to exactly 100."""
    assert sum(dist.values()) == 100, f"distribution must sum to 100, got {sum(dist.values())}: {dist}"
