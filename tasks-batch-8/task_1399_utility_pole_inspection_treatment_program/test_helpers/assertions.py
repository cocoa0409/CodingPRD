"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual, expected_iso, label="timestamp"):
    """Instant-equality comparison tolerant of fractional-digit rendering."""
    assert isinstance(actual, str) and actual, (
        f"{label} must be a non-empty ISO 8601 string, got {actual!r}"
    )
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program_budget(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["spent_cents"], int)
    assert isinstance(data["available_cents"], int)


def assert_budget_invariant(data: dict):
    """PRD §3.1: the total always equals available plus committed plus spent."""
    assert data["total_cents"] == (
        data["available_cents"] + data["committed_cents"] + data["spent_cents"]
    ), (
        f"Budget invariant violated: total {data['total_cents']} != "
        f"available {data['available_cents']} + committed {data['committed_cents']} "
        f"+ spent {data['spent_cents']}"
    )


def assert_inspection_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["cycle_length_years"], int) and data["cycle_length_years"] >= 1
    assert data["status"] in ["DRAFT", "OPEN", "RECONCILED"]
    assert data["strength_variant_policy"] in ["CONSERVATIVE", "STATISTICAL"]
    assert isinstance(data["sample_pool_size"], int)
    assert isinstance(data["tasks_total"], int)
    assert isinstance(data["tasks_terminal"], int)
    assert isinstance(data["pending_replacement_count"], int)


def assert_pole(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pole_number"], str) and data["pole_number"]
    assert data["species"] in ["SOUTHERN_PINE", "DOUGLAS_FIR", "WESTERN_RED_CEDAR", "LARCH"]
    assert data["original_class"] in ["H1", "1", "2", "3", "4", "5"]
    assert data["status"] in ["IN_SERVICE", "MONITOR", "PRIORITY_REJECT", "REPLACED"]
    assert data["current_classification"] in [
        "NONE", "SERVICEABLE", "MONITOR", "REJECT_ROUTINE", "REJECT_PRIORITY",
    ]
    assert isinstance(data["joint_use"], bool)
    assert isinstance(data["attachment_count_declared"], int)
    assert isinstance(data["open_treatment_count"], int)


def assert_inspection_task(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a valid UUID"
    assert is_valid_uuid(data.get("pole_id", "")), "pole_id must be a valid UUID"
    assert data["status"] in ["OPEN", "SUBMITTED", "REJECTED", "ACCEPTED", "WAIVED", "ESCALATED"]
    assert isinstance(data["rework_count"], int)
    assert isinstance(data["photos"], list)


def assert_treatment_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pole_id", "")), "pole_id must be a valid UUID"
    assert data["product_code"] in ["CCA_WRAP", "PENTA_GEL", "COPPER_NAPHTHENATE"]
    assert data["status"] in ["CREATED", "SCHEDULED", "APPLIED", "VERIFIED", "FAILED_QA"]
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert isinstance(data["qa_fail_events"], int)


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("treatment_order_id", "")), (
        "treatment_order_id must be a valid UUID"
    )
    assert data["claim_reason"] in ["DECAY_RECURRENCE", "PRODUCT_FAILURE"]
    assert data["status"] in ["FILED", "HONORED", "DENIED"]


def assert_contractor_crew(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["qa_pass_count"], int)
    assert isinstance(data["qa_fail_count"], int)
    assert isinstance(data["qa_event_log"], list)
    assert isinstance(data["quality_score_lifetime"], (int, float))
    assert isinstance(data["quality_score_rolling"], (int, float))


def assert_replacement_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pole_id", "")), "pole_id must be a valid UUID"
    assert data["status"] in ["QUEUED", "FUNDED", "DEFERRED", "COMPLETED"]
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] > 0
    assert isinstance(data["deferral_count"], int) and data["deferral_count"] >= 0
    assert isinstance(data["escalated_cost_cents"], int)
    assert isinstance(data["priority_score"], int)


def assert_attachment_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pole_id", "")), "pole_id must be a valid UUID"
    assert is_valid_uuid(data.get("inspection_task_id", "")), (
        "inspection_task_id must be a valid UUID"
    )
    assert data["audit_status"] in ["SUBMITTED", "ADJUDICATED"]
    assert data["violation_status"] in ["NONE", "DETECTED", "NOTIFIED", "CURED", "ESCALATED"]
    assert isinstance(data["found_attachment_count"], int)
    assert isinstance(data["unauthorized_count"], int) and data["unauthorized_count"] >= 0


def assert_backlog_snapshot(data: dict):
    """PRD §2.4: a snapshot carries id and created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "BacklogSnapshot must not carry updated_at"
    assert "version" not in data, "BacklogSnapshot must not carry version"
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a valid UUID"
    assert is_valid_uuid(data.get("budget_id", "")), "budget_id must be a valid UUID"
    assert isinstance(data["snapshot_seq"], int) and data["snapshot_seq"] >= 1
    assert isinstance(data["queued_count"], int)
    assert isinstance(data["queued_escalated_cost_cents"], int)
    assert isinstance(data["funded_count"], int)
    assert isinstance(data["budget_available_cents"], int)
    assert isinstance(data["budget_committed_cents"], int)
    assert isinstance(data["crew_billings"], list)
