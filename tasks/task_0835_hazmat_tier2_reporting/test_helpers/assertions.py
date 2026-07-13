"""Entity assertions and domain invariant checkers for the Hazmat Tier II API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["epa_facility_id"], str) and data["epa_facility_id"]
    assert data["erp_status"] in ("NONE", "ACTIVE")
    assert data["compliance_posture"] in ("COMPLIANT", "DEFICIENT", "ENFORCEMENT")
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert isinstance(data["total_outstanding_fee_cents"], int)
    assert data["total_outstanding_fee_cents"] >= 0
    assert isinstance(data["is_rmp_required"], bool)


def assert_chemical(data: dict):
    _assert_common(data)
    assert isinstance(data["cas_number"], str) and data["cas_number"]
    assert isinstance(data["is_ehs"], bool)
    assert data["physical_state"] in ("SOLID", "LIQUID", "GAS")


def assert_chemical_inventory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["chemical_id"])
    assert data["storage_type"] in ("TANK", "CYLINDER", "DRUM", "BULK")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["is_reportable"], bool)
    assert isinstance(data["exceeds_tpq"], bool)


def assert_tier_ii_filing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "RETURNED_FOR_REVISION"
    )
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["assessed_fee_cents"], int)
    assert isinstance(data["fee_paid_cents"], int)
    assert isinstance(data["revision_count"], int)


def assert_sds(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["chemical_id"])
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_release_notification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["reporting_status"] in ("PENDING_VERBAL", "VERBAL_GIVEN", "WRITTEN_FILED")
    assert data["remediation_status"] in ("ONGOING", "CONTAINED", "CLOSED")
    assert data["medium"] in ("AIR", "WATER", "SOIL")
    assert isinstance(data["exceeds_rq"], bool)
    assert isinstance(data["requires_lepc"], bool)


def assert_lepc_notice(data: dict):
    _assert_common(data)
    assert data["notice_type"] in ("VERBAL", "WRITTEN")
    assert data["recipient"] in ("LEPC", "SERC", "NRC")
    assert isinstance(data["acknowledged"], bool)


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["permit_type"] in ("OPERATING", "STORAGE", "AIR")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED")
    assert data["result"] in (None, "PASS", "FAIL")


def assert_compliance_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["origin"] in ("RELEASE_RQ_EXCEEDED", "INSPECTION_FAILED", "LATE_FILING", "MANUAL")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED")


def assert_risk_management_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["program_level"] in (1, 2, 3)
    assert data["status"] in ("ACTIVE", "DUE", "OVERDUE")
