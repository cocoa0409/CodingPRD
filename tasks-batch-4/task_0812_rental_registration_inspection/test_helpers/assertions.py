"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_PROPERTY_STATES = ["REGISTERED", "SUSPENDED", "CONDEMNED"]
_LICENSE_STATES = ["PENDING_PAYMENT", "ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED"]
_INSPECTION_STATES = ["SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED"]
_VIOLATION_STATES = ["OPEN", "REMEDIATION_SUBMITTED", "ESCALATED",
                     "VERIFIED_RESOLVED", "CONDEMNED_BASIS"]
_NOTICE_STATES = ["SENT", "ACKNOWLEDGED", "EXPIRED"]
_COMPLAINT_STATES = ["FILED", "INSPECTION_SCHEDULED", "RESOLVED"]
_CONDEMNATION_STATES = ["DRAFT", "ISSUED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_landlord(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["certification_level"] in ["STANDARD", "SENIOR", "LEAD_CERTIFIED"]
    assert isinstance(data["active"], bool)


def assert_property(data: dict):
    _assert_common(data)
    assert data["registration_status"] in _PROPERTY_STATES
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert isinstance(data["year_built"], int)
    assert isinstance(data["has_lead_risk"], bool)
    assert isinstance(data["open_violation_count"], int) and data["open_violation_count"] >= 0
    assert isinstance(data["open_critical_violation_count"], int) \
        and data["open_critical_violation_count"] >= 0
    assert isinstance(data["total_penalty_cents"], int) and data["total_penalty_cents"] >= 0
    assert isinstance(data["total_fees_paid_cents"], int) and data["total_fees_paid_cents"] >= 0


def assert_license(data: dict):
    _assert_common(data)
    assert data["status"] in _LICENSE_STATES
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["lead_surcharge_applied"], bool)
    assert data["term_years"] in (1, 2, 3)
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in _INSPECTION_STATES
    assert data["inspection_type"] in ["PERIODIC", "COMPLAINT", "REINSPECTION"]
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0


def assert_violation(data: dict):
    _assert_common(data)
    assert data["status"] in _VIOLATION_STATES
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["category"] in ["LIFE_SAFETY", "HABITABILITY", "LEAD_PAINT", "STRUCTURAL"]
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0


def assert_notice(data: dict):
    _assert_common(data)
    assert data["status"] in _NOTICE_STATES
    assert data["notice_type"] in ["LEAD_PAINT_DISCLOSURE", "INSPECTION_NOTICE",
                                   "VIOLATION_NOTICE", "CONDEMNATION_NOTICE"]


def assert_complaint(data: dict):
    _assert_common(data)
    assert data["status"] in _COMPLAINT_STATES


def assert_condemnation_order(data: dict):
    _assert_common(data)
    assert data["status"] in _CONDEMNATION_STATES


def assert_checklist_item(data: dict):
    """Append-only resource: only id + created_at, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["result"] in ["PASS", "FAIL", "NOT_APPLICABLE"]


def assert_checklist_item_is_append_only(data: dict):
    """PRD §2.4: the checklist item carries only id and created_at."""
    assert "updated_at" not in data, "checklist item must not carry updated_at"
    assert "version" not in data, "checklist item must not carry version"
