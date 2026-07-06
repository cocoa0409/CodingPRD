"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["category"] in ["LEADERSHIP", "TECHNICAL", "COMPLIANCE", "SALES"]
    assert data["delivery_mode"] in ["VIRTUAL", "ONSITE", "HYBRID"]
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_program_version(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be valid UUID"
    assert data["pricing_model"] in ["PER_SEAT", "FLAT"]
    assert data["status"] in ["DRAFT", "IN_REVIEW", "APPROVED", "SUPERSEDED"]
    assert isinstance(data["min_seats"], int) and data["min_seats"] >= 1


def assert_facilitator(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["certified_categories"], list)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_cohort(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_version_id", "")), "program_version_id must be valid UUID"
    assert is_valid_uuid(data.get("lead_facilitator_id", "")), "lead_facilitator_id must be valid UUID"
    assert data["status"] in [
        "SCHEDULED", "OPEN", "LOCKED", "RUNNING", "DELIVERED", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1


def assert_seat_ledger_nonnegative(data: dict):
    """Derived seat counters must never go negative."""
    assert data["seats_reserved"] >= 0, "seats_reserved must be >= 0"
    assert data["seats_confirmed"] >= 0, "seats_confirmed must be >= 0"
    assert data["seats_waitlisted"] >= 0, "seats_waitlisted must be >= 0"


def assert_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cohort_id", "")), "cohort_id must be valid UUID"
    assert data["status"] in [
        "WAITLISTED", "ENROLLED", "CONFIRMED", "ATTENDED", "NO_SHOW", "WITHDRAWN", "CANCELLED",
    ]


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("registration_id", "")), "registration_id must be valid UUID"
    assert data["outcome"] in ["PASS", "FAIL"]
    assert data["status"] in ["GRADED", "VOIDED"]


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("registration_id", "")), "registration_id must be valid UUID"
    assert is_valid_uuid(data.get("assessment_id", "")), "assessment_id must be valid UUID"
    assert data["status"] in ["ISSUED", "REVOKED"]


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 0
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "CLOSED"]


def assert_contract_ledger(data: dict):
    """Contract budget ledger invariant: remaining == budget - committed."""
    assert data["remaining_cents"] == data["budget_cents"] - data["committed_cents"], (
        "remaining_cents must equal budget_cents - committed_cents"
    )
    assert data["committed_cents"] >= 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cohort_id", "")), "cohort_id must be valid UUID"
    assert data["variant"] in ["PROVISIONAL", "FINAL"]
    assert data["status"] in ["PROVISIONAL", "FINAL", "VOID"]
    assert data["total_cents"] == (
        data["tuition_cents"] + data["materials_cents"] + data["travel_cents"]
    ), "total_cents must equal tuition + materials + travel"


def assert_evaluation(data: dict):
    """Evaluation is append-only (common_fields:false): only id + created_at among common fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
