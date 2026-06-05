"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the shape and field types/enums of a
returned resource. Immutable entities (Certificate, Attestation) must NOT carry
updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CATEGORIES = ["ETHICS", "SUBSTANCE", "GENERAL"]
CREDIT_UNITS = ["CEU", "CME", "CLE"]


def _assert_common(data: dict):
    """id/created_at/updated_at/version present for full-lifecycle entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight(data: dict):
    """id + created_at only; immutable entities must not expose updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable entity must not carry a version field"
    assert "updated_at" not in data, "immutable entity must not carry an updated_at field"


def assert_license_board(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["jurisdiction_code"], str) and len(data["jurisdiction_code"]) == 2
    assert data["jurisdiction_code"] == data["jurisdiction_code"].upper()
    assert data["credit_unit"] in CREDIT_UNITS
    assert isinstance(data["cycle_length_months"], int) and data["cycle_length_months"] >= 1
    assert float(data["total_required_hours"]) >= 0
    assert float(data["carryover_cap_hours"]) >= 0
    assert int(data["audit_cooldown_days"]) >= 0
    assert int(data["reminder_lead_days"]) >= 0


def assert_credit_requirement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("board_id", "")), "board_id must be a UUID"
    assert data["category"] in CATEGORIES
    assert float(data["min_hours"]) >= 0


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data.get("board_id", "")), "board_id must be a UUID"
    assert data["status"] in ["APPLIED", "ACCREDITED", "SUSPENDED", "REVOKED"]


def assert_course(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_id", "")), "provider_id must be a UUID"
    assert isinstance(data["title"], str)
    assert data["category"] in CATEGORIES
    assert float(data["credit_hours"]) > 0
    assert data["status"] in ["ACTIVE", "DEACTIVATED"]


def assert_licensee(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_valid_uuid(data.get("home_board_id", "")), "home_board_id must be a UUID"
    assert isinstance(data["license_number"], str)
    score = data["audit_risk_score"]
    assert isinstance(score, int) or float(score).is_integer(), "audit_risk_score is integer-valued"
    assert 0 <= float(score) <= 100, "audit_risk_score clamped to [0, 100]"


def assert_renewal_cycle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("licensee_id", "")), "licensee_id must be a UUID"
    assert is_valid_uuid(data.get("board_id", "")), "board_id must be a UUID"
    assert is_iso8601_timestamp(data["cycle_start"])
    assert is_iso8601_timestamp(data["cycle_end"])
    assert data["status"] in ["OPEN", "REQUIREMENTS_MET", "AUDIT_HOLD", "RENEWED", "LAPSED"]
    assert float(data["carryover_in_hours"]) >= 0
    assert float(data["carryover_out_hours"]) >= 0
    assert data["reminder_status"] in ["NOT_DUE", "DUE", "OVERDUE"]
    # provisional is always >= final (provisional set is a superset of final).
    assert float(data["provisional_earned_hours"]) >= float(data["final_earned_hours"]), (
        "provisional_earned_hours must be >= final_earned_hours"
    )


def assert_completion(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("licensee_id", "")), "licensee_id must be a UUID"
    assert is_valid_uuid(data.get("course_id", "")), "course_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert is_iso8601_timestamp(data["completed_at"])
    assert float(data["awarded_hours"]) >= 0
    assert data["category"] in CATEGORIES
    assert data["status"] in ["PENDING_VERIFICATION", "VERIFIED", "REJECTED", "INVALIDATED"]
    assert isinstance(data["is_late"], bool)


def assert_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert is_valid_uuid(data.get("licensee_id", "")), "licensee_id must be a UUID"
    assert isinstance(data["initiated_by_user_id"], str) and len(data["initiated_by_user_id"]) > 0
    assert data["status"] in ["INITIATED", "ATTESTATION_PENDING", "UNDER_REVIEW", "PASSED", "FAILED"]
    assert is_iso8601_timestamp(data["initiated_at"])


def assert_reciprocity_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("licensee_id", "")), "licensee_id must be a UUID"
    assert is_valid_uuid(data.get("target_cycle_id", "")), "target_cycle_id must be a UUID"
    assert isinstance(data["source_jurisdiction_code"], str)
    assert data["category"] in CATEGORIES
    assert float(data["credit_hours"]) > 0
    assert data["status"] in ["REQUESTED", "APPROVED", "DENIED"]


def assert_certificate(data: dict):
    _assert_lightweight(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert float(data["total_hours_certified"]) >= 0
    assert is_iso8601_timestamp(data["issued_at"])


def assert_attestation(data: dict):
    _assert_lightweight(data)
    assert is_valid_uuid(data.get("audit_id", "")), "audit_id must be a UUID"
    assert isinstance(data["statement"], str)
    assert float(data["attested_hours"]) >= 0
