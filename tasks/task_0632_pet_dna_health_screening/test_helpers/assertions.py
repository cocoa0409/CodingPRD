"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the shape and field types the PRD promises
for that resource. Versioned entities must expose id/created_at/updated_at/version;
the two append-only records expose only id/created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_common_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_account(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["data_residency"] in ("US", "EU")
    assert isinstance(data["relative_finder_opt_in"], bool)
    assert isinstance(data["pet_count"], int)
    assert isinstance(data["purge_pending"], bool)


def assert_pet(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["name"], str)
    assert data["species"] in ("DOG", "CAT")
    assert isinstance(data["birth_year"], int)
    assert isinstance(data["relative_finder_opt_in"], bool)
    assert data["status"] in ("REGISTERED", "ARCHIVED")


def assert_kit(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["barcode"], str) and len(data["barcode"]) > 0
    assert data["product_tier"] in ("BREED", "BREED_HEALTH")
    assert data["status"] in ("ORDERED", "ACTIVATED", "RECEIVED", "CONSUMED", "VOIDED")


def assert_sample(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["kit_id"], str)
    assert data["status"] in ("RECEIVED", "GENOTYPING", "PASS", "QNS", "FAILED", "RETESTED")


def assert_genotyping_run(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["sample_id"], str)
    if data.get("outcome") is not None:
        assert data["outcome"] in ("PASS", "QNS", "FAILED")


def assert_report(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["sample_id"], str)
    assert isinstance(data["pet_id"], str)
    assert isinstance(data["includes_health"], bool)
    assert data["status"] in ("PRELIMINARY", "FINALIZED", "REVOKED")
    assert isinstance(data["breed_composition"], list)
    assert isinstance(data["at_risk_marker_count"], int)


def assert_health_marker_result(data: dict):
    _assert_common_append_only(data)
    assert isinstance(data["report_id"], str)
    assert isinstance(data["marker_code"], str)
    assert data["genotype"] in ("CLEAR", "CARRIER", "AT_RISK")
    assert data["review_status"] in ("PASS", "REVIEWED")
    # Append-only record: must NOT carry version/updated_at.
    assert "version" not in data, "HealthMarkerResult must not carry a version field"
    assert "updated_at" not in data, "HealthMarkerResult must not carry an updated_at field"


def assert_relative_match(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["pet_id"], str)
    assert isinstance(data["relative_pet_id"], str)
    assert data["status"] in ("ESTIMATED", "CONFIRMED", "WITHDRAWN")


def assert_share_link(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["report_id"], str)
    assert isinstance(data["vet_email"], str)
    assert isinstance(data["token"], str) and len(data["token"]) > 0
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_subscription(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["account_id"], str)
    assert data["tier"] in ("BASIC", "PREMIUM")
    assert data["status"] in ("ACTIVE", "GRACE", "CANCELLED", "SUPERSEDED")
    assert isinstance(data["annual_fee_cents"], int)
    assert isinstance(data["last_charge_cents"], int)


def assert_data_request(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["account_id"], str)
    assert data["kind"] in ("DOWNLOAD", "DELETE")
    assert data["status"] in ("PENDING", "READY", "GRACE", "PURGING", "PURGED", "CANCELLED")


def assert_marker_catalog_entry(data: dict):
    _assert_common_append_only(data)
    assert isinstance(data["marker_code"], str)
    assert data["category"] in ("HEALTH", "TRAIT")
    assert data["species"] in ("DOG", "CAT")
    assert "version" not in data, "MarkerCatalogEntry must not carry a version field"
    assert "updated_at" not in data, "MarkerCatalogEntry must not carry an updated_at field"


def assert_breed_composition_sums_to_100(breed_composition: list):
    """breed_composition pct values must sum to exactly 100.00 (PRD §3.4)."""
    if not breed_composition:
        return
    total = round(sum(seg["pct"] for seg in breed_composition), 2)
    assert total == 100.00, f"breed_composition pct must sum to 100.00, got {total}"
