"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version must start at 1 and only increase"


def assert_hazard_plan(data: dict):
    _assert_common_fields(data)
    assert data["hazard_type"] in [
        "PANDEMIC_INFLUENZA", "BIOTERRORISM_ANTHRAX", "RADIOLOGICAL_INCIDENT",
        "CHEMICAL_RELEASE", "NATURAL_DISASTER", "OUTBREAK_OTHER",
    ]
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["jurisdiction_code"], str) and len(data["jurisdiction_code"]) > 0
    assert isinstance(data["target_population"], int) and data["target_population"] >= 0
    assert data["status"] in ["DRAFT", "ACTIVATED", "STOOD_DOWN"]
    assert isinstance(data["readiness_score"], (int, float))
    assert 0 <= data["readiness_score"] <= 100


def assert_pod(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("hazard_plan_id", ""))
    assert isinstance(data["site_name"], str) and len(data["site_name"]) > 0
    assert data["site_type"] in ["FIXED_POD", "MOBILE_POD", "DRIVE_THROUGH", "CLOSED_POD"]
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert isinstance(data["staffing_capacity_lanes"], int) and data["staffing_capacity_lanes"] > 0
    assert isinstance(data["lane_throughput_rate_per_hour"], int) and data["lane_throughput_rate_per_hour"] > 0
    assert data["operational_status"] in ["STAGING", "OPERATIONAL", "RESTRICTED", "CLOSED"]
    assert data["risk_tier"] in ["STANDARD", "ELEVATED", "CRITICAL"]
    assert isinstance(data["queue_backlog_count"], int) and data["queue_backlog_count"] >= 0
    assert isinstance(data["open_allocation_request_count"], int) and data["open_allocation_request_count"] >= 0
    assert isinstance(data["committed_staff_hours"], (int, float)) and data["committed_staff_hours"] >= 0


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["primary_role"] in [
        "CLINICAL_LEAD", "SCREENER", "VACCINATOR", "RUNNER", "TRAFFIC_CONTROL", "GREETER",
    ]
    assert isinstance(data["mrc_unit"], str) and len(data["mrc_unit"]) > 0
    assert data["credential_type"] in [
        "RN_LICENSE", "MD_LICENSE", "EMT_CERT", "NIMS_IS100_700", "BACKGROUND_CHECK", "PODS_TRAINING",
    ]
    assert is_iso8601_timestamp(data["credential_expires_at"])
    assert data["credential_status"] in ["PENDING", "VERIFIED", "REVOKED"]


def assert_shift_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pod_id", ""))
    assert is_valid_uuid(data.get("staff_member_id", ""))
    assert data["assigned_role"] in [
        "CLINICAL_LEAD", "SCREENER", "VACCINATOR", "RUNNER", "TRAFFIC_CONTROL", "GREETER",
    ]
    assert is_iso8601_timestamp(data["start_time"])
    assert is_iso8601_timestamp(data["end_time"])
    assert data["status"] in ["PENDING", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED"]


def assert_countermeasure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["countermeasure_type"] in ["VACCINE", "ANTIVIRAL", "ANTIBIOTIC_PEP"]
    assert isinstance(data["doses_required"], int) and data["doses_required"] > 0
    assert isinstance(data["dose_interval_days"], int) and data["dose_interval_days"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["reorder_point_quantity"], int) and data["reorder_point_quantity"] >= 0


def assert_inventory_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("countermeasure_id", ""))
    assert data.get("pod_id") is None or is_valid_uuid(data["pod_id"])
    assert isinstance(data["lot_number"], str) and len(data["lot_number"]) > 0
    assert isinstance(data["on_hand_quantity"], int) and data["on_hand_quantity"] >= 0
    assert isinstance(data["reserved_quantity"], int) and data["reserved_quantity"] >= 0
    assert isinstance(data["available_quantity"], int)
    assert data["available_quantity"] == data["on_hand_quantity"] - data["reserved_quantity"]
    assert is_iso8601_timestamp(data["expiration_date"])


def assert_allocation_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pod_id", ""))
    assert is_valid_uuid(data.get("countermeasure_id", ""))
    assert data["source_type"] in ["SNS_CACHE", "MUTUAL_AID"]
    assert data.get("partner_pod_id") is None or is_valid_uuid(data["partner_pod_id"])
    assert isinstance(data["requested_quantity"], int) and data["requested_quantity"] > 0
    assert data["status"] in ["REQUESTED", "RESERVED", "FULFILLED", "DENIED", "CANCELLED"]
    assert isinstance(data["reserved_quantity"], int) and data["reserved_quantity"] >= 0
    assert isinstance(data["fulfilled_quantity"], int) and data["fulfilled_quantity"] >= 0
    assert isinstance(data["priority_score"], (int, float))
    assert isinstance(data["reimbursement_cost_usd"], (int, float))


def assert_dispensing_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pod_id", ""))
    assert is_valid_uuid(data.get("countermeasure_id", ""))
    assert isinstance(data["registrant_full_name"], str) and len(data["registrant_full_name"]) > 0
    assert data["registrant_risk_group"] in [
        "GENERAL_PUBLIC", "HEALTHCARE_WORKER", "FIRST_RESPONDER", "HIGH_RISK_MEDICAL",
    ]
    assert isinstance(data["dose_count"], int) and data["dose_count"] > 0
    assert data["status"] in ["REGISTERED", "SCREENED", "DEFERRED", "REFUSED", "DISPENSED"]


def assert_drill(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("hazard_plan_id", ""))
    assert data["drill_type"] in ["TABLETOP", "FUNCTIONAL", "FULL_SCALE"]
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert data["corrective_action_status"] in ["NONE", "OPEN", "CLOSED"]


def assert_situation_report(data: dict):
    """SituationReport carries only id + created_at (common_fields: false, an
    immutable point-in-time snapshot never modified after creation)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data.get("hazard_plan_id", ""))
    assert isinstance(data["report_period_label"], str) and len(data["report_period_label"]) > 0
    assert isinstance(data["pods_operational_count"], int) and data["pods_operational_count"] >= 0
    assert isinstance(data["pods_restricted_count"], int) and data["pods_restricted_count"] >= 0
    assert isinstance(data["total_doses_dispensed"], int) and data["total_doses_dispensed"] >= 0
    assert isinstance(data["total_on_hand_inventory"], int) and data["total_on_hand_inventory"] >= 0
    assert isinstance(data["staffing_fill_rate_pct"], (int, float))
    assert isinstance(data["total_mutual_aid_reimbursement_usd"], (int, float))
    assert data["readiness_status"] in ["GREEN", "YELLOW", "RED"]


def assert_inventory_conservation(lot: dict):
    """Invariant (PRD §2.9): reserved_quantity + available_quantity == on_hand_quantity."""
    assert lot["reserved_quantity"] + lot["available_quantity"] == lot["on_hand_quantity"], (
        f"Inventory conservation violated: reserved({lot['reserved_quantity']}) + "
        f"available({lot['available_quantity']}) != on_hand({lot['on_hand_quantity']})"
    )
