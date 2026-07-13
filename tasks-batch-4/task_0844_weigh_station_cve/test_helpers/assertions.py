"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["usdot_number"], str) and data["usdot_number"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["irp_status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert data["ifta_status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert data["ucr_status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert isinstance(data["oos_points"], int)
    assert isinstance(data["unpaid_fines_cents"], int)
    assert isinstance(data["iss_score"], int)
    assert isinstance(data["certified_iss_score"], int)
    assert isinstance(data["prism_flagged"], bool)
    assert isinstance(data["registration_hold"], bool)
    assert data["status"] in ("ACTIVE", "UNDER_REVIEW", "OOS_ORDERED")


def assert_driver(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["carrier_id"])
    assert isinstance(data["cdl_number"], str) and data["cdl_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["hos_status"] in ("COMPLIANT", "VIOLATION")
    assert isinstance(data["driving_minutes_window"], int)
    assert data["status"] in ("ACTIVE", "OOS")


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str)
    assert isinstance(data["gross_weight_limit_lbs"], int)
    assert isinstance(data["single_axle_limit_lbs"], int)
    assert isinstance(data["iss_bypass_threshold"], int)


def assert_bay(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["label"], str)
    assert isinstance(data["reserved_minutes"], int)
    assert data["status"] in ("AVAILABLE", "OUT_OF_ORDER")


def assert_screening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert is_valid_uuid(data["driver_id"])
    assert isinstance(data["vehicle_plate"], str)
    assert isinstance(data["axle_count"], int) and data["axle_count"] >= 2
    assert isinstance(data["gross_weight_lbs"], int)
    assert isinstance(data["heaviest_axle_lbs"], int)
    assert isinstance(data["hazmat_placarded"], bool)
    assert isinstance(data["oversize"], bool)
    assert isinstance(data["overweight"], bool)
    assert isinstance(data["credentials_valid"], bool)
    assert data["decision"] in ("BYPASS", "PULL_IN")
    assert data["referral_reason"] in (
        "NONE", "PRISM_TARGET", "OVERWEIGHT", "OVERSIZE", "CREDENTIAL", "HAZMAT")
    assert data["status"] in ("SCREENED", "CLEARED", "REFERRED", "INSPECTED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["screening_id"])
    assert is_valid_uuid(data["driver_id"])
    assert is_valid_uuid(data["bay_id"])
    assert data["level"] in ("LEVEL_I", "LEVEL_II", "LEVEL_III")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["result"] in ("NONE", "CLEAR", "OOS")
    assert isinstance(data["oos_flag"], bool)
    assert isinstance(data["reinspection_count"], int)
    assert isinstance(data["oos_points_applied"], int)
    assert data["status"] in (
        "IN_PROGRESS", "CLEARED", "OOS_ISSUED", "REINSPECTION", "CANCELLED")


def assert_violation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["inspection_id"])
    assert isinstance(data["code"], str)
    assert data["category"] in ("VEHICLE", "DRIVER", "HAZMAT", "HOS", "CREDENTIAL", "WEIGHT")
    assert isinstance(data["severity_weight"], int) and 1 <= data["severity_weight"] <= 10
    assert isinstance(data["oos"], bool)


def assert_citation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["inspection_id"])
    assert is_valid_uuid(data["carrier_id"])
    assert data["kind"] in ("OVERWEIGHT", "CREDENTIAL", "HAZMAT", "HOS", "EQUIPMENT")
    assert isinstance(data["assessed_fine_cents"], int)
    assert isinstance(data["final_fine_cents"], int)
    assert isinstance(data["certified_gross_lbs"], int)
    assert isinstance(data["certified_axle_lbs"], int)
    assert isinstance(data["issued_by_user_id"], str)
    assert data["status"] in ("ASSESSED", "CONTESTED", "UPHELD", "DISMISSED", "SETTLED")


def assert_duty_log(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["driver_id"])
    assert data["entry_type"] in ("DRIVING", "ON_DUTY", "OFF_DUTY", "SLEEPER")
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])


def assert_score_snapshot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["carrier_id"])
    assert data["method"] in ("PROVISIONAL", "CERTIFIED")
    assert isinstance(data["iss_score"], int) and 0 <= data["iss_score"] <= 100
    assert isinstance(data["inspection_count"], int)
    assert isinstance(data["is_current"], bool)
    assert is_iso8601_timestamp(data["computed_at"])
