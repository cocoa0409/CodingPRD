"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["target_district_count"], int)
    assert data["target_district_count"] >= 1
    assert data["total_population"] >= 0
    assert data["voting_age_population_total"] >= 0
    assert data["ideal_district_population"] >= 0


def assert_census_block(data: dict):
    _assert_common(data)
    assert isinstance(data["geoid"], str)
    assert data["population"] >= 0
    assert 0 <= data["voting_age_population"] <= data["population"]
    assert 0 <= data["minority_vap"] <= data["voting_age_population"]
    assert data["registered_voters"] >= 0


def assert_plan(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "COMMENT_OPEN", "HEARING_SCHEDULED",
        "ADOPTED", "REJECTED", "SUPERSEDED",
    ]
    assert isinstance(data["is_compliant"], bool)
    assert isinstance(data["majority_minority_district_count"], int)


def assert_district(data: dict):
    _assert_common(data)
    assert data["district_number"] >= 1
    assert isinstance(data["is_contiguous"], bool)
    assert isinstance(data["is_majority_minority"], bool)
    assert isinstance(data["incumbent_retained"], bool)


def assert_block_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "REMOVED"]


def assert_precinct(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SPLIT", "MERGED", "RETIRED"]
    assert data["voter_count_basis"] in ["PROVISIONAL", "CERTIFIED"]
    assert data["registered_voters"] >= 0


def assert_polling_place(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "CLOSED"]
    assert data["capacity"] >= 1
    assert data["assigned_registered_voters"] >= 0
    assert isinstance(data["is_over_capacity"], bool)


def assert_polling_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_venue(data: dict):
    _assert_common(data)
    assert data["capacity"] >= 1


def assert_hearing(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "HELD", "CANCELLED"]


def assert_public_comment(data: dict):
    _assert_common(data)
    assert data["disposition"] in ["PENDING", "ACKNOWLEDGED", "INCORPORATED", "DISMISSED"]


def assert_compliance_check(data: dict):
    """ComplianceCheck is an immutable snapshot (PRD §2.4): id + created_at only,
    NO version and NO updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ComplianceCheck must NOT carry a version field"
    assert "updated_at" not in data, "ComplianceCheck must NOT carry an updated_at field"
    assert data["result_status"] in ["PASS", "WARN", "FAIL"]


def assert_gis_export(data: dict):
    _assert_common(data)
    assert data["status"] in ["COMPLETE", "FAILED"]
    assert data["export_format"] in ["GEOJSON", "SHAPEFILE"]
