"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 on creation"


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) > 0
    assert isinstance(data["declared_state_code"], str)
    assert data["residency_status"] in ("UNVERIFIED", "RESIDENT", "NONRESIDENT")
    assert isinstance(data["education_certified"], bool)
    assert isinstance(data["preference_points"], int)
    assert 0 <= data["preference_points"] <= 12
    assert isinstance(data["bonus_points"], int)
    assert data["bonus_points"] >= 0


def assert_residency_verification(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_id"], str)
    assert data["proof_type"] in ("DRIVERS_LICENSE", "UTILITY_BILL", "TAX_RECORD", "TRIBAL_ID")
    assert isinstance(data["proof_state_code"], str)
    assert isinstance(data["continuous_months"], int) and data["continuous_months"] >= 0
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")
    assert data["resulting_residency"] in (None, "RESIDENT", "NONRESIDENT")


def assert_education_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["course_code"], str)
    assert isinstance(data["completion_date"], str)
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED")


def assert_license_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str)
    assert data["product_kind"] in ("LICENSE", "TAG", "STAMP")
    assert isinstance(data["requires_education"], bool)
    assert data["residency_restriction"] in ("ANY", "RESIDENT_ONLY", "NONRESIDENT_ONLY")
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert isinstance(data["min_age_years"], int) and data["min_age_years"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_species_season(data: dict):
    _assert_common(data)
    assert isinstance(data["species"], str)
    assert isinstance(data["season_open"], str)
    assert isinstance(data["season_close"], str)
    assert isinstance(data["bag_limit"], int) and data["bag_limit"] >= 0
    assert isinstance(data["draw_required"], bool)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")


def assert_draw_pool(data: dict):
    _assert_common(data)
    assert isinstance(data["species_season_id"], str)
    assert isinstance(data["license_product_id"], str)
    assert isinstance(data["quota"], int) and data["quota"] >= 0
    assert data["scoring_model"] in ("SQUARED", "LINEAR")
    assert data["status"] in ("ACCEPTING", "CLOSED", "DRAWN")
    assert isinstance(data["awarded_count"], int) and data["awarded_count"] >= 0
    assert isinstance(data["entry_deadline"], str)


def assert_draw_application(data: dict):
    _assert_common(data)
    assert isinstance(data["draw_pool_id"], str)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["points_at_entry"], int)
    assert isinstance(data["bonus_at_entry"], int)
    assert isinstance(data["priority_score"], int)
    assert data["status"] in ("SUBMITTED", "AWARDED", "UNSUCCESSFUL", "WITHDRAWN")


def assert_license(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["license_product_id"], str)
    assert data["issued_via"] in ("OVER_THE_COUNTER", "DRAW_AWARD")
    assert isinstance(data["fee_charged_cents"], int) and data["fee_charged_cents"] >= 0
    assert data["status"] in ("ISSUED", "VOIDED")


def assert_harvest_report(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert isinstance(data["harvest_datetime"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")


def assert_replacement(data: dict):
    _assert_common(data)
    assert isinstance(data["original_license_id"], str)
    assert data["reason"] in ("LOST", "DAMAGED", "STOLEN")
    assert isinstance(data["admin_fee_cents"], int) and data["admin_fee_cents"] >= 0
