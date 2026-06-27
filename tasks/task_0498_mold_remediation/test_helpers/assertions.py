"""Entity assertions and domain invariant checkers (Mold Remediation PRD)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (mutable, audit-tracked entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["site_name"], str) and len(data["site_name"]) > 0
    assert data["hazard_class"] in ("ASBESTOS", "LEAD", "MOLD")
    assert isinstance(data["structure_sqft"], int) and data["structure_sqft"] > 0
    assert isinstance(data["jurisdiction_code"], str)
    assert data["posture"] in (
        "ASSESSMENT", "CONTAINED", "ABATING", "CLEARANCE_PENDING", "VERIFIED", "FROZEN",
    )
    assert isinstance(data["neshap_required"], bool)
    assert data["status"] in ("OPEN", "SIGNED_OFF", "ABANDONED")
    assert isinstance(data["open_finding_count"], int) and data["open_finding_count"] >= 0


def assert_worker(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["cert_type"] in ("ASBESTOS", "LEAD", "MOLD", "HYGIENIST")
    assert is_iso8601_timestamp(data["cert_expires_at"])
    assert is_iso8601_timestamp(data["ppe_fit_test_at"])
    assert isinstance(data["is_cert_current"], bool)


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert data["finding_level"] in ("CLEAN", "ELEVATED", "HAZARDOUS")
    assert data["status"] in ("DRAFT", "SAMPLED", "ANALYZED", "CLEARED")


def assert_sample(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["assessment_id"])
    assert is_valid_uuid(data["project_id"])
    assert data["sample_type"] in ("AIR", "SURFACE")
    assert data["status"] in ("PENDING", "ANALYZED", "VOIDED")


def assert_containment_zone(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["required_pressure_pa"], (int, float))
    assert isinstance(data["latest_pressure_pa"], (int, float))
    assert isinstance(data["is_compliant"], bool)
    assert data["status"] in ("SETUP", "ACTIVE", "BREACHED", "DISMANTLED")


def assert_pressure_log(data: dict):
    """PressureLog is append-only: id + created_at only — NO version, NO updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "PressureLog is append-only and carries no version"
    assert "updated_at" not in data, "PressureLog is append-only and carries no updated_at"


def assert_abatement_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["zone_id"])
    assert data["abatement_type"] in ("ASBESTOS", "LEAD", "MOLD")
    assert isinstance(data["planned_weight_kg"], (int, float)) and data["planned_weight_kg"] > 0
    assert isinstance(data["revision_index"], int) and data["revision_index"] >= 0
    assert data["status"] in (
        "PLANNED", "IN_PROGRESS", "COMPLETED", "REOPENED", "CANCELLED",
    )


def assert_disposal_manifest(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["abatement_order_id"])
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["manifest_weight_kg"], (int, float))
    assert isinstance(data["disposal_fee_cents"], int) and data["disposal_fee_cents"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "VOIDED")


def assert_clearance_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["abatement_order_id"])
    assert is_valid_uuid(data["sampler_worker_id"])
    assert data["status"] in ("DRAFT", "ANALYZED", "PASSED", "FAILED", "SIGNED_OFF")


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert data["permit_type"] in ("NESHAP_NOTIFICATION", "DEMOLITION", "TRANSPORT")
    assert isinstance(data["notice_days"], int) and data["notice_days"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED", "EXPIRED")


def assert_insurance_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert isinstance(data["coverage_limit_cents"], int) and data["coverage_limit_cents"] > 0
    assert isinstance(data["estimated_amount_cents"], int)
    assert isinstance(data["settled_amount_cents"], int)
    assert data["status"] in ("OPEN", "SUBMITTED", "SETTLED", "DENIED")


def assert_worker_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["abatement_order_id"])
    assert is_valid_uuid(data["worker_id"])
    assert data["status"] in ("ACTIVE", "RELEASED")
