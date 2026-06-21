"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the structural contract the PRD promises for a
fetched/returned resource. Lean entities (Payer, ComplianceCheck, ClockState) carry
only id + created_at — their assertions deliberately do NOT demand updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_full(data: dict):
    """id + created_at + updated_at + version (entities with common_fields)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def _assert_common_lean(data: dict):
    """id + created_at only (lean entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lean entity must not carry updated_at"
    assert "version" not in data, "lean entity must not carry version"


def assert_physician(data: dict):
    _assert_common_full(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["npi"], str)
    assert isinstance(data["home_state_code"], str)
    assert isinstance(data["active_license_count"], int)
    assert data["status"] in ("ACTIVE", "DEACTIVATED")


def assert_state_license(data: dict):
    _assert_common_full(data)
    assert isinstance(data["physician_id"], str)
    assert isinstance(data["state_code"], str)
    assert data["issuance_type"] in ("FULL", "COMPACT_EXPEDITED")
    assert isinstance(data["controlled_substance_authority"], bool)
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED")


def assert_patient(data: dict):
    _assert_common_full(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["residence_state_code"], str)


def assert_payer(data: dict):
    _assert_common_lean(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["copay_cents"], int)
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["covered_state_codes"], list)


def assert_visit(data: dict):
    _assert_common_full(data)
    assert isinstance(data["physician_id"], str)
    assert isinstance(data["patient_id"], str)
    assert data["modality"] in ("VIDEO", "AUDIO_ONLY")
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["determined_state_code"], str)
    assert isinstance(data["list_fee_cents"], int)
    assert data["status"] in (
        "REQUESTED", "COMPLIANCE_CLEARED", "APPROVED_INSURANCE",
        "APPROVED_SELF_PAY", "COMPLETED", "CANCELLED", "VOIDED",
    )
    assert isinstance(data["prescription_version"], int)


def assert_compliance_check(data: dict):
    _assert_common_lean(data)
    assert isinstance(data["visit_id"], str)
    assert data["outcome"] in ("CLEARED", "BLOCKED", "OVERRIDDEN")
    assert data["reason_code"] in (
        "LICENSE_MATCH", "NO_LICENSE_IN_STATE", "LICENSE_NOT_ACTIVE",
        "AUDIO_ONLY_NOT_PERMITTED", "OFFICER_OVERRIDE",
    )


def assert_prescription(data: dict):
    _assert_common_full(data)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["drug_name"], str) and len(data["drug_name"]) > 0
    assert data["dea_schedule"] in ("NONE", "II", "III", "IV", "V")
    assert isinstance(data["days_supply"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "VOIDED")


def assert_claim(data: dict):
    _assert_common_full(data)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["payer_id"], str)
    assert isinstance(data["billed_cents"], int)
    assert data["status"] in ("SUBMITTED", "ADJUDICATED", "DENIED", "REVERSED")


def assert_follow_up(data: dict):
    _assert_common_full(data)
    assert isinstance(data["source_visit_id"], str)
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("OPEN", "FULFILLED", "LAPSED")
