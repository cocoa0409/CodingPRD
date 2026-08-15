"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert data["status"] in ("PRE_REGISTERED", "REGISTERED", "MERGED", "INACTIVE")
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert isinstance(data["last_name"], str) and data["last_name"]
    assert isinstance(data["primary_phone"], str) and data["primary_phone"]


def assert_insurance_policy(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "TERMINATED", "VOIDED")
    assert data["plan_type"] in (
        "HMO", "PPO", "EPO", "POS", "MEDICARE", "MEDICAID", "SELF_PAY"
    )
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert isinstance(data["deductible_remaining_cents"], int)
    assert data["deductible_remaining_cents"] >= 0
    assert isinstance(data["oop_max_remaining_cents"], int)
    assert data["oop_max_remaining_cents"] >= 0


def assert_eligibility_check(data: dict):
    _assert_common_fields(data)
    assert data["coverage_status"] in ("ACTIVE", "INACTIVE", "NOT_FOUND", "UNKNOWN")
    assert data["result"] in ("VERIFIED", "VERIFIED_WITH_AUTH", "FAILED", "STALE")
    assert isinstance(data["copay_cents"], int) and data["copay_cents"] >= 0
    assert isinstance(data["coinsurance_pct"], int) and 0 <= data["coinsurance_pct"] <= 100
    assert isinstance(data["auth_required"], bool)


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "EXHAUSTED", "EXPIRED", "CLOSED")
    assert isinstance(data["visits_authorized"], int) and data["visits_authorized"] >= 1
    assert isinstance(data["visits_consumed"], int) and data["visits_consumed"] >= 0


def assert_authorization(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("APPROVED", "CONSUMED", "EXPIRED", "VOIDED")
    assert isinstance(data["authorized_units"], int) and data["authorized_units"] >= 1


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED", "PRE_CHECKED", "READY", "ARRIVED",
        "IN_ROOM", "COMPLETED", "CANCELLED", "NO_SHOW",
    )
    assert data["registration_gate"] in ("CLEAR", "CLEAR_WITH_PAYMENT", "BLOCKED")
    assert data["visit_type"] in ("NEW", "ESTABLISHED", "PROCEDURE", "IMAGING")
    assert isinstance(data["amount_collected_cents"], int)
    assert isinstance(data["estimated_patient_responsibility_cents"], int)
    assert isinstance(data["auth_satisfied"], bool)
    assert isinstance(data["late_minutes"], int)
    assert isinstance(data["no_show_risk_strikes"], int)
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 5


def assert_copay_estimate(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PROVISIONAL", "FINAL", "SUPERSEDED")
    assert data["method"] in ("PAYER_VERIFIED", "FEE_SCHEDULE")
    assert isinstance(data["allowed_amount_cents"], int) and data["allowed_amount_cents"] >= 0
    assert isinstance(data["estimated_patient_responsibility_cents"], int)
    assert data["estimated_patient_responsibility_cents"] >= 0
    assert isinstance(data["deposit_required_cents"], int)
    assert data["deposit_required_cents"] >= 0


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("POSTED", "VOIDED")
    assert data["method"] in ("CASH", "CARD", "CHECK", "WALLET")
    assert data["kind"] in ("POST", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_queue_ticket(data: dict):
    _assert_common_fields(data)
    assert data["state"] in ("WAITING", "CALLED", "SERVED", "SKIPPED", "REMOVED")
    assert data["priority"] in ("STAT", "ACCOMMODATION", "STANDARD")
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1


def assert_accommodation_flag(data: dict):
    _assert_common_fields(data)
    assert data["flag_type"] in ("INTERPRETER", "MOBILITY", "SENSORY", "COGNITIVE")
    assert isinstance(data["active"], bool)


def assert_appointment_invariants(data: dict):
    """Money invariants of PRD §2.6/§3.5: collected totals never fall below zero."""
    assert data["amount_collected_cents"] >= 0, (
        f"amount_collected_cents must be clamped at 0, got {data['amount_collected_cents']}"
    )
    assert data["estimated_patient_responsibility_cents"] >= 0
