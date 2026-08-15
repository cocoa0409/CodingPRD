"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_district(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ii_reduction_target_pct"], (int, float))
    assert isinstance(data["notice_lead_hours"], int)
    assert isinstance(data["warranty_months"], int)
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["budget_committed_cents"], int)
    assert 0 <= data["budget_committed_cents"] <= max(data["budget_cents"], data["budget_committed_cents"])


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["nassco_cert_number"], str) and data["nassco_cert_number"]
    assert isinstance(data["capabilities"], list)
    assert set(data["capabilities"]) <= {"CODER", "QA_REVIEWER", "CREW_LEAD"}
    assert isinstance(data["active"], bool)


def assert_inspection_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")


def assert_segment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["segment_ref"], str) and data["segment_ref"]
    assert isinstance(data["diameter_mm"], int)
    assert data["material"] in ("VCP", "RCP", "PVC", "HDPE", "CI", "BRICK")
    assert data["length_m"] > 0
    assert data["structural_grade"] in (0, 1, 2, 3, 4, 5)
    assert data["om_grade"] in (0, 1, 2, 3, 4, 5)
    assert data["rehab_status"] in ("NONE", "PLANNED", "IN_PROGRESS", "REHABILITATED", "WARRANTY")


def assert_lateral(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["address"], str) and data["address"]
    assert data["connection_type"] in ("DIRECT", "WYE", "SADDLE")
    assert isinstance(data["active"], bool)
    assert isinstance(data["reinstated"], bool)


def assert_cctv_inspection(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "CODING", "QA_REVIEW", "CERTIFIED", "VOIDED")
    assert data["purpose"] in ("BASELINE", "PRE_REHAB", "POST_CIPP", "WARRANTY_RE")
    assert isinstance(data["reject_count"], int) and 0 <= data["reject_count"] <= 3


def assert_defect_observation(data: dict):
    """Append-only record: id + created_at only; no updated_at, no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DefectObservation must not carry updated_at"
    assert "version" not in data, "DefectObservation must not carry version"
    assert data["family"] in ("STRUCTURAL", "OM")
    assert data["grade"] in (1, 2, 3, 4, 5)
    assert 0 <= data["clock_position"] <= 12


def assert_rehab_plan(data: dict):
    _assert_common_fields(data)
    assert data["method"] in ("CIPP_LINING", "SPOT_REPAIR", "FULL_REPLACE")
    assert data["status"] in ("DRAFT", "PROPOSED", "APPROVED", "EXECUTING", "COMPLETED", "CANCELLED")
    assert isinstance(data["provisional_total_cents"], int)


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert data["execution_status"] in ("ISSUED", "MOBILIZED", "IN_WORK", "PUNCH_LIST", "COMPLETED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID")
    assert data["mobilization_tier"] in ("MOB_SMALL", "MOB_STANDARD", "MOB_LARGE")


def assert_line_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pay_item_code"], str) and data["pay_item_code"]
    assert data["scheduled_qty"] > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["provisional_line_cents"], int)


def assert_bypass_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "ACTIVE", "DEMOBILIZED", "CLOSED", "REJECTED")
    assert isinstance(data["pump_capacity_gpm"], int)


def assert_customer_notice(data: dict):
    _assert_common_fields(data)
    assert data["channel"] in ("DOOR_HANGER", "MAIL", "SMS", "EMAIL")
    assert data["status"] in ("QUEUED", "SENT", "ACKNOWLEDGED", "EXPIRED")


def assert_warranty_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPENED", "RE_INSPECTION", "UNDER_REPAIR", "RESOLVED", "DENIED", "WITHDRAWN")


def assert_flow_period(data: dict):
    _assert_common_fields(data)
    assert data["phase"] in ("PRE_REHAB", "POST_REHAB")
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED", "ANALYZED")
