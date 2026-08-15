"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso8601(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime for
    instant comparisons (PRD pins instants, not string spellings)."""
    assert is_iso8601_timestamp(ts), f"not an ISO 8601 timestamp: {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

PROGRAM_STATUSES = ["DRAFT", "VALIDATED", "RELEASED", "OBSOLETE"]
FIXTURE_STATUSES = ["COMMISSIONING", "AVAILABLE", "UNDER_MAINTENANCE", "DECOMMISSIONED"]
CHAMBER_STATUSES = ["ONLINE", "MAINTENANCE", "OFFLINE"]
RESERVATION_STATUSES = ["RESERVED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
LOT_STATUSES = [
    "RECEIVED", "QUEUED", "IN_TEST", "AWAITING_DISPOSITION",
    "CONTAINED", "SHIPPED", "SCRAPPED",
]
UNIT_STATUSES = ["UNTESTED", "PASSED", "FAILED"]
AUTHORIZATION_STATUSES = ["ACTIVE", "CONSUMED", "REVOKED", "EXPIRED"]
EQUIPMENT_STATUSES = ["IN_SERVICE", "CALIBRATION_DUE", "IN_MAINTENANCE", "RETURNED"]
MAINTENANCE_ORDER_STATUSES = ["OPEN", "IN_PROGRESS", "DONE", "CANCELLED"]
ESD_AUDIT_STATUSES = ["OPEN", "CLOSED"]
RMA_FA_STATUSES = ["INTAKE", "FA_IN_PROGRESS", "FA_COMPLETE", "CLOSED"]
REVIEW_STATUSES = ["PENDING", "DECIDED"]
DISPOSITIONS = ["SHIP", "MRB_REVIEW", "SCRAP_REVIEW"]


def _assert_common_fields(data: dict):
    """PRD §2.4: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["tier"] in ["STANDARD", "STRATEGIC"]
    assert isinstance(data["requires_esd_certification"], bool)
    assert data["account_status"] in ["ACTIVE", "SUSPENDED"]


def assert_test_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["part_number"], str) and len(data["part_number"]) > 0
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data.get("supersedes_program_id") is None or isinstance(data["supersedes_program_id"], str)
    assert isinstance(data["bin_map"], dict) and len(data["bin_map"]) > 0
    assert all(v in ["PASS", "SOFT_FAIL", "HARD_FAIL"] for v in data["bin_map"].values())
    assert isinstance(data["max_retests_per_unit"], int)
    assert isinstance(data["burn_profile"], list)
    assert data["status"] in PROGRAM_STATUSES


def assert_fixture(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["serial_number"], str)
    assert isinstance(data["site_count"], int) and data["site_count"] >= 1
    assert data["status"] in FIXTURE_STATUSES


def assert_chamber(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["area_code"], str)
    assert isinstance(data["slot_count"], int) and data["slot_count"] >= 1
    assert isinstance(data["supported_profile_classes"], list)
    assert data["status"] in CHAMBER_STATUSES
    assert isinstance(data["available_slots"], int)


def assert_chamber_reservation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["chamber_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["fixture_id"], str)
    assert data["profile_class"] in ["A", "B", "C"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["slot_count"], int) and data["slot_count"] >= 1
    assert isinstance(data["planned_duration_minutes"], int)
    assert data["status"] in RESERVATION_STATUSES


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["part_number"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in LOT_STATUSES
    for field in (
        "units_registered", "units_untested", "units_passed",
        "units_failed", "retested_unit_count", "escape_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, field
    assert data.get("suggested_disposition") is None or data["suggested_disposition"] in DISPOSITIONS


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["serial_number"], str)
    assert data["test_status"] in UNIT_STATUSES
    assert data.get("current_bin") is None or isinstance(data["current_bin"], int)
    assert isinstance(data["retest_count"], int) and data["retest_count"] >= 0


def assert_test_result(data: dict):
    """PRD §2.4: a TestResult carries only id and created_at — no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TestResult must not carry updated_at"
    assert "version" not in data, "TestResult must not carry version"
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["fixture_id"], str)
    assert isinstance(data["bin_code"], int)
    assert isinstance(data["passed"], bool)
    assert isinstance(data["insertion_index"], int) and data["insertion_index"] >= 1
    assert isinstance(data["recorded_by_user_id"], str)
    assert isinstance(data["voided"], bool)
    assert isinstance(data["excluded_from_tally"], bool)


def assert_retest_authorization(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["reason"], str)
    assert isinstance(data["authorized_by_user_id"], str)
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in AUTHORIZATION_STATUSES


def assert_customer_equipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert data["equipment_type"] in ["TESTER", "HANDLER", "PROBER"]
    assert isinstance(data["serial_number"], str)
    assert isinstance(data["calibration_interval_days"], int) and data["calibration_interval_days"] >= 1
    assert is_iso8601_timestamp(data["last_calibrated_at"])
    assert is_iso8601_timestamp(data["next_calibration_due"])
    assert data["status"] in EQUIPMENT_STATUSES


def assert_maintenance_order(data: dict):
    _assert_common_fields(data)
    assert data["target_type"] in ["EQUIPMENT", "CHAMBER"]
    assert isinstance(data["target_id"], str)
    assert data["kind"] in ["CALIBRATION", "REPAIR", "PREVENTIVE"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in MAINTENANCE_ORDER_STATUSES


def assert_esd_audit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["area_code"], str)
    assert isinstance(data["findings"], list)
    assert isinstance(data["corrective_actions"], list)
    assert data.get("outcome") is None or data["outcome"] in ["PASS", "PASS_WITH_MINOR", "FAIL"]
    assert isinstance(data["auditor_user_id"], str)
    assert data["status"] in ESD_AUDIT_STATUSES


def assert_rma_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["failure_mode"], str)
    assert data["fa_status"] in RMA_FA_STATUSES
    assert data.get("fa_conclusion") is None or data["fa_conclusion"] in [
        "TEST_ESCAPE", "CUSTOMER_INDUCED", "NO_TROUBLE_FOUND",
    ]
    assert isinstance(data["created_by_customer_id"], str)


def assert_lot_disposition_review(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lot_id"], str)
    assert data.get("suggested_disposition") is None or data["suggested_disposition"] in DISPOSITIONS
    assert data.get("decision") is None or data["decision"] in ["SHIP", "SCRAP", "REWORK"]
    assert data["status"] in REVIEW_STATUSES


def assert_lot_tally_invariant(lot: dict):
    """PRD §3.5: units_untested + units_passed + units_failed always sum to quantity."""
    total = lot["units_untested"] + lot["units_passed"] + lot["units_failed"]
    assert total == lot["quantity"], (
        f"Lot tally invariant violated: {lot['units_untested']} untested + "
        f"{lot['units_passed']} passed + {lot['units_failed']} failed "
        f"!= quantity {lot['quantity']}"
    )


def assert_chamber_slot_invariant(chamber: dict):
    """PRD §2.8: available_slots never exceeds slot_count and never goes negative."""
    assert 0 <= chamber["available_slots"] <= chamber["slot_count"], (
        f"available_slots {chamber['available_slots']} out of [0, {chamber['slot_count']}]"
    )
