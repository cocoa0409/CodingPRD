"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_REGISTRY_STATES = ["PROPOSED", "PERMITTED", "ACTIVE", "INACTIVE", "DECOMMISSIONED"]
_POTABILITY_STATES = ["UNKNOWN", "POTABLE", "ADVISORY", "UNSAFE"]
_PERMIT_STATES = ["SUBMITTED", "APPROVED", "ISSUED", "COMPLETED", "DENIED", "EXPIRED"]
_SAMPLE_STATES = ["SUBMITTED", "RECEIVED", "IN_ANALYSIS", "RESULTED", "INVALIDATED"]
_ADVISORY_LEVELS = ["SAFE", "ADVISORY", "UNSAFE"]


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _mutable_common(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_applicant(data: dict):
    _mutable_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str)
    assert isinstance(data["mailing_state"], str)
    assert isinstance(data["net_fees_paid_cents"], int)


def assert_driller(data: dict):
    _mutable_common(data)
    assert isinstance(data["license_number"], str)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_aquifer(data: dict):
    _common(data)
    assert data["sensitivity"] in ["HIGH", "MODERATE", "LOW"]
    # Immutable config record: no updated_at / no version.
    assert "version" not in data, "Aquifer must not carry a version field"
    assert "updated_at" not in data, "Aquifer must not carry an updated_at field"


def assert_well(data: dict):
    _mutable_common(data)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["aquifer_id"], str)
    assert data["intended_use"] in ["DOMESTIC", "IRRIGATION", "LIVESTOCK"]
    assert data["registry_status"] in _REGISTRY_STATES
    assert data["potability_status"] in _POTABILITY_STATES
    assert isinstance(data["active_advisory_count"], int)


def assert_construction_permit(data: dict):
    _mutable_common(data)
    assert data["status"] in _PERMIT_STATES
    assert isinstance(data["fee_estimate_cents"], int)
    assert isinstance(data["fee_charged_cents"], int)
    assert isinstance(data["fee_refunded_cents"], int)
    assert isinstance(data["fee_paid"], bool)


def assert_driller_log(data: dict):
    _mutable_common(data)
    assert isinstance(data["total_depth_ft"], int)
    assert data["grout_type"] in ["BENTONITE", "CEMENT", "NEAT_CEMENT"]


def assert_water_sample(data: dict):
    _mutable_common(data)
    assert data["sample_type"] in ["ROUTINE", "REAL_ESTATE", "CONTAMINATION_FOLLOWUP"]
    assert isinstance(data["requested_analytes"], list) and len(data["requested_analytes"]) > 0
    assert data["status"] in _SAMPLE_STATES
    assert isinstance(data["panel_fee_cents"], int)


def assert_sample_result(data: dict):
    _common(data)
    # Append-only record: no updated_at / no version.
    assert "version" not in data, "SampleResult must not carry a version field"
    assert "updated_at" not in data, "SampleResult must not carry an updated_at field"
    assert data["advisory_level_provisional"] in _ADVISORY_LEVELS
    assert data["advisory_level_confirmed"] in _ADVISORY_LEVELS
    assert isinstance(data["exceedances"], list)


def assert_advisory(data: dict):
    _mutable_common(data)
    assert data["advisory_type"] in ["BOIL_WATER", "DO_NOT_DRINK", "NITRATE", "LEAD"]
    assert data["status"] in ["ACTIVE", "LIFTED"]


def assert_contamination_case(data: dict):
    _mutable_common(data)
    assert data["severity"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    assert data["status"] in ["OPEN", "INVESTIGATING", "MITIGATION", "RESOLVED", "CLOSED"]


def assert_abandonment_permit(data: dict):
    _mutable_common(data)
    assert data["reason"] in ["DRY", "CONTAMINATED", "REPLACED", "CODE_VIOLATION"]
    assert data["method"] in ["PERFORATE_FILL", "OVERDRILL", "EXCAVATE"]
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "COMPLETED"]


def assert_real_estate_requirement(data: dict):
    _mutable_common(data)
    assert data["transaction_type"] in ["SALE", "REFINANCE"]
    assert data["status"] in ["OPEN", "SATISFIED", "EXPIRED", "WAIVED"]
