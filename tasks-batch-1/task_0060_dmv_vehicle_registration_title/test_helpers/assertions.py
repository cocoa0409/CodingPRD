"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_owner(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["residence_county_code"], str)
    assert data["credential_type"] in ("STANDARD", "REAL_ID")
    assert data["real_id_status"] in ("NONE", "PENDING", "UPGRADED")


def assert_vehicle(data: dict):
    _common(data)
    assert isinstance(data["owner_id"], str)
    assert isinstance(data["vin"], str)
    assert data["vin_status"] in ("UNVERIFIED", "VERIFIED", "FLAGGED")
    assert data["title_status"] in ("NONE", "CLEAR", "REBUILT")
    assert data["vehicle_class"] in ("PASSENGER", "TRUCK", "MOTORCYCLE")
    assert isinstance(data["active_lien_count"], int) and data["active_lien_count"] >= 0


def assert_vin_verification(data: dict):
    # Write-once record: id + created_at only, no updated_at / version.
    _common(data, versioned=False)
    assert data["outcome"] in ("MATCH", "MISMATCH", "NHTSA_FLAG")
    assert "updated_at" not in data, "VinVerification must not carry updated_at"
    assert "version" not in data, "VinVerification must not carry version"


def assert_title_application(data: dict):
    _common(data)
    assert data["application_type"] in ("INITIAL", "TRANSFER")
    assert data["status"] in ("DRAFT", "SUBMITTED", "SALVAGE_HOLD", "APPROVED", "ISSUED", "REJECTED")
    assert isinstance(data["requires_salvage_path"], bool)


def assert_salvage_inspection(data: dict):
    _common(data)
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] == "RECORDED"


def assert_lien(data: dict):
    _common(data)
    assert data["status"] in ("FILED", "PERFECTED", "RELEASED")
    assert isinstance(data["principal_cents"], int)


def assert_emissions_inspection(data: dict):
    _common(data)
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] == "RECORDED"
    assert is_iso8601_timestamp(data["inspected_at"])
    assert is_iso8601_timestamp(data["valid_until"])


def assert_fee_assessment(data: dict):
    _common(data)
    assert data["status"] in ("ASSESSED", "PAID", "VOIDED")
    for f in ("use_tax_cents", "registration_fee_cents", "real_id_surcharge_cents", "total_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative int"
    assert data["total_cents"] == (
        data["use_tax_cents"] + data["registration_fee_cents"] + data["real_id_surcharge_cents"]
    ), "total_cents must equal sum of components"


def assert_registration(data: dict):
    _common(data)
    assert data["registration_type"] in ("INITIAL", "TRANSFER")
    assert data["status"] in ("PENDING_FEES", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["plate_assigned"], bool)


def assert_license_plate(data: dict):
    _common(data)
    assert data["plate_type"] in ("PHYSICAL", "ELECTRONIC")
    assert data["status"] in ("ISSUED", "ACTIVE", "DEACTIVATED", "SURRENDERED")


def assert_real_id_application(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")
    assert isinstance(data["documents_complete"], bool)
