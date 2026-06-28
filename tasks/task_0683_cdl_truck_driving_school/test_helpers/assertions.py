"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["cdl_class"] in ("CLASS_A", "CLASS_B")
    assert data["classroom_required_hours"] >= 0
    assert data["range_required_hours"] >= 0
    assert data["road_required_hours"] >= 0
    assert data["tuition_cents"] >= 0
    assert 0 <= data["skills_pass_threshold"] <= 100
    assert isinstance(data["active"], bool)


def assert_truck(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_number"], str) and len(data["unit_number"]) > 0
    assert data["cdl_class"] in ("CLASS_A", "CLASS_B")
    assert data["turnaround_buffer_minutes"] >= 0
    assert data["status"] == "AVAILABLE"
    assert data["reserved_minutes"] >= 0


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["cdl_class"] in ("CLASS_A", "CLASS_B")
    assert isinstance(data["examiner_certified"], bool)
    assert data["status"] == "ACTIVE"
    assert data["reserved_minutes"] >= 0


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["commitment_months"] > 0
    assert data["reimbursement_cents"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["student_name"], str) and len(data["student_name"]) > 0
    assert isinstance(data["dot_medical_verified"], bool)
    assert isinstance(data["permit_verified"], bool)
    assert data["status"] in (
        "APPLIED", "PREREQ_PENDING", "TRAINING", "TEST_READY",
        "PASSED", "COMPLETED", "WITHDRAWN",
    )
    assert data["logged_classroom_hours"] >= 0
    assert data["logged_range_hours"] >= 0
    assert data["logged_road_hours"] >= 0
    assert data["projected_road_hours"] >= 0
    assert isinstance(data["fmcsa_reported"], bool)


def assert_prereq_document(data: dict):
    _assert_common(data)
    assert data["kind"] in ("DOT_MEDICAL", "CLP_PERMIT")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "EXPIRED")


def assert_clock_session(data: dict):
    _assert_common(data)
    assert data["phase"] in ("CLASSROOM", "RANGE", "ROAD")
    assert data["duration_minutes"] > 0
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")


def assert_skills_test(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "GRADED", "VOIDED")
    if data["status"] == "GRADED":
        assert data["outcome"] in ("PASS", "FAIL")


def assert_sponsorship_offer(data: dict):
    _assert_common(data)
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "FULFILLED", "FORFEITED")
    assert data["months_served"] >= 0
    assert data["clawback_cents"] >= 0


def assert_finance_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "CANCELLED")
    # Conserved relationship between snapshot, down payment, and financed amount.
    assert data["financed_cents"] == data["tuition_cents"] - data["down_payment_cents"]


def assert_completion_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "TRANSMITTED")
