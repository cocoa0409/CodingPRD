"""Entity assertions and domain invariant checkers for the National Cemetery API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Full common fields: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_cemetery(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["country_code"], str)
    assert isinstance(data["is_overseas"], bool)
    assert isinstance(data["honors_squad_capacity"], int)


def assert_section(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ("IN_GROUND", "COLUMBARIUM")
    assert isinstance(data["capacity_units"], int)
    assert isinstance(data["available_units"], int)
    assert isinstance(data["interred_units"], int)


def assert_gravesite(data: dict):
    assert_common_fields(data)
    assert data["gravesite_class"] in ("STANDARD", "OVERSIZE", "CREMATION")
    assert isinstance(data["depth_capacity"], int)
    assert isinstance(data["interment_count"], int)
    assert data["status"] in ("AVAILABLE", "RESERVED", "OCCUPIED", "DECOMMISSIONED")


def assert_niche(data: dict):
    assert_common_fields(data)
    assert isinstance(data["urn_capacity"], int)
    assert isinstance(data["inurnment_count"], int)
    assert data["status"] in ("AVAILABLE", "RESERVED", "OCCUPIED", "DECOMMISSIONED")


def assert_burial_case(data: dict):
    assert_common_fields(data)
    assert data["case_type"] in ("AT_NEED", "PRE_NEED")
    assert data["applicant_role"] in ("VETERAN", "SPOUSE", "DEPENDENT")
    assert data["requested_class"] in ("STANDARD", "OVERSIZE", "CREMATION")
    assert data["status"] in (
        "SUBMITTED", "ELIGIBLE", "INELIGIBLE", "ASSIGNED",
        "SCHEDULED", "INTERRED", "CANCELLED",
    )


def assert_eligibility_determination(data: dict):
    """Immutable audit record: id + created_at only, NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["decision"] in ("APPROVED", "DENIED")


def assert_pmc(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "RESERVED", "EXPIRED")


def assert_interment_schedule(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_marker_order(data: dict):
    assert_common_fields(data)
    assert data["marker_type"] in (
        "UPRIGHT_MARBLE", "FLAT_GRANITE", "FLAT_BRONZE", "NICHE_COVER"
    )
    assert data["status"] in ("DRAFT", "SUBMITTED", "ENGRAVED", "CANCELLED")


def assert_military_honors(data: dict):
    assert_common_fields(data)
    assert data["detail_size"] in ("TWO_PERSON", "FULL_SQUAD")
    assert isinstance(data["flag_issued"], bool)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "RENDERED", "CANCELLED")
