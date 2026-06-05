"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_homeowner(data: dict):
    _assert_common(data)
    assert data["state_code"] in ["CA", "NJ", "MA", "TX", "AZ"]
    assert isinstance(data["annual_kwh_usage"], int) and data["annual_kwh_usage"] >= 0


def assert_installer(data: dict):
    _assert_common(data)
    assert isinstance(data["licensed_states"], list) and len(data["licensed_states"]) > 0


def assert_utility(data: dict):
    _assert_common(data)
    assert data["feeder_headroom_kw"] >= 0
    assert data["net_metering_rate_cents_per_kwh"] >= 0
    assert 0.0 <= data["export_credit_ratio"] <= 1.0


def assert_project(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "REQUESTED", "ASSESSED", "DESIGNED", "PERMIT_PENDING", "PERMIT_APPROVED",
        "INSTALLED", "FAILED_INSPECTION", "REMEDIATION", "PTO_PENDING",
        "OPERATIONAL", "CANCELLED",
    ]


def assert_financing_plan(data: dict):
    _assert_common(data)
    assert data["model"] in ["PPA", "LEASE", "LOAN"]
    assert data["status"] in ["DRAFT", "ACTIVE", "TERMINATED"]
    assert data["srec_owner"] in ["HOMEOWNER", "FINANCIER"]
    assert data["itc_beneficiary"] in ["HOMEOWNER", "FINANCIER"]


def assert_srec(data: dict):
    _assert_common(data)
    assert data["status"] in ["MINTED", "LISTED", "SOLD", "RETIRED"]
    assert data["owner_type"] in ["HOMEOWNER", "FINANCIER"]


def assert_net_meter_period(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "SETTLED"]


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["claim_type"] in ["PRODUCTION_SHORTFALL", "EQUIPMENT_DEFECT"]
    assert data["status"] in ["SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "REMEDIATED"]


def assert_interconnection_application(data: dict):
    _assert_common(data)
    assert data["status"] in ["FILED", "UNDER_REVIEW", "APPROVED", "PTO_GRANTED", "REJECTED"]


def assert_warranty_policy(data: dict):
    """WarrantyPolicy is an immutable artifact (PRD 2.4): only id + created_at,
    no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "WarrantyPolicy must NOT carry a version field"
    assert "updated_at" not in data, "WarrantyPolicy must NOT carry an updated_at field"
