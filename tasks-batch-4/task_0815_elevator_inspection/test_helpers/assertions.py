"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_CATEGORIES = ["PASSENGER_ELEVATOR", "FREIGHT_ELEVATOR", "ESCALATOR", "MOVING_WALK", "DUMBWAITER"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str)
    assert isinstance(data["license_expiry_period"], int)
    assert isinstance(data["certified_categories"], list)
    assert isinstance(data["active_assignment_count"], int)


def assert_device(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["owner_id"])
    assert data["category"] in _CATEGORIES
    assert data["risk_class"] in ["HIGH", "MEDIUM", "LOW"]
    assert data["status"] in ["REGISTERED", "ACTIVE", "OUT_OF_SERVICE", "DECOMMISSIONED"]
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert isinstance(data["accident_risk_score"], int)
    assert isinstance(data["active_oos_count"], int)


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert data["type"] in ["ANNUAL", "PERIODIC", "REINSPECTION", "ACCIDENT_FOLLOWUP"]
    assert data["status"] in [
        "SCHEDULED", "ASSIGNED", "IN_PROGRESS", "PASSED", "FAILED", "CONDITIONAL", "CANCELLED",
    ]


def assert_deficiency(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["inspection_id"])
    assert is_valid_uuid(data["device_id"])
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["status"] in ["OPEN", "CITED", "RESOLVED", "WAIVED"]


def assert_citation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["deficiency_id"])
    assert is_valid_uuid(data["device_id"])
    assert isinstance(data["fine_amount_cents"], int)
    assert isinstance(data["surcharged_amount_cents"], int)
    assert isinstance(data["contest_count"], int)
    assert data["status"] in ["ISSUED", "CONTESTED", "PAID", "DISMISSED"]


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert isinstance(data["issue_period"], int)
    assert isinstance(data["expiry_period"], int)
    assert data["status"] in ["ISSUED", "POSTED", "SUSPENDED", "REVOKED", "SUPERSEDED", "EXPIRED"]


def assert_oos_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert data["reason"] in ["CRITICAL_DEFICIENCY", "ACCIDENT", "NONPAYMENT", "EXPIRED_CERTIFICATE"]
    assert data["status"] in ["ACTIVE", "LIFTED"]


def assert_fee_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert data["type"] in ["REGISTRATION", "ANNUAL_RENEWAL", "REINSPECTION", "LATE_PENALTY"]
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["PENDING", "OVERDUE", "PAID"]


def assert_accident_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert data["severity"] in ["MINOR", "MODERATE", "SEVERE", "FATAL"]
    assert isinstance(data["provisional_risk_score"], int)
    assert data["status"] in ["REPORTED", "UNDER_INVESTIGATION", "SUBSTANTIATED", "UNSUBSTANTIATED"]
