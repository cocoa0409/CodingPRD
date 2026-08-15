"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_role_profile(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in ("DRAFT", "PUBLISHED")
    assert isinstance(data.get("published_version"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_employee(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("employment_status") in ("ACTIVE", "INACTIVE")
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_new_hire(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("status") in ("REGISTERED", "EMPLOYED", "RESCINDED", "SEPARATED")
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_onboarding_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("phase") in (
        "PRE_BOARDING", "CLEARANCE_IN_PROGRESS", "PROVISIONING", "DAY_ONE_READY",
        "IN_PROGRESS", "PROBATION", "COMPLETED", "WITHDRAWN", "REVOKED", "SEPARATED",
    )
    assert data.get("health") in ("ON_TRACK", "AT_RISK")
    assert isinstance(data.get("health_score"), int)
    assert isinstance(data.get("pinned_profile_version"), int)
    assert isinstance(data.get("version"), int)


def assert_onboarding_task(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("task_kind") in ("DOCUMENT_UPLOAD", "FORM_ACK", "POLICY_READ")
    assert data.get("status") in ("PENDING", "SUBMITTED", "APPROVED", "REJECTED", "WAIVED", "CANCELLED")
    assert isinstance(data.get("is_required"), bool)
    assert isinstance(data.get("reject_count"), int)
    assert isinstance(data.get("sort_index"), int)


def assert_clearance_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ("IN_PROGRESS", "ESCALATED", "CLEARED", "REJECTED", "CANCELLED")
    assert data.get("background_status") in ("PENDING", "PASSED", "FAILED")
    assert data.get("reference_status") in ("PENDING", "PASSED", "FAILED")


def assert_provisioning_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "IN_PROGRESS", "ATTENTION_REQUIRED", "FULFILLED", "CANCELLED",
    )
    assert isinstance(data.get("sla_hours"), int)


def assert_provisioning_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("item_kind") in ("EQUIPMENT", "ACCESS")
    assert data.get("status") in ("PENDING", "IN_FULFILLMENT", "DONE", "BLOCKED", "CANCELLED")
    assert isinstance(data.get("quantity"), int)


def assert_orientation_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("room"), str) and data["room"]
    assert data.get("status") in ("SCHEDULED", "FULL", "CONDUCTED", "CANCELLED")
    assert isinstance(data.get("capacity"), int)
    assert isinstance(data.get("booked_count"), int)


def assert_check_in(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("kind") in ("MANAGER", "BUDDY")
    assert data.get("status") in ("SCHEDULED", "COMPLETED", "MISSED", "CANCELLED")
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))


def assert_training_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ("ASSIGNED", "COMPLETED", "OVERDUE", "CANCELLED")
    assert isinstance(data.get("module_code"), str)


def assert_probation_cycle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("cycle_index"), int)
    assert data.get("status") in (
        "ACTIVE", "EVALUATION_DUE", "EVALUATED_PASS", "EVALUATED_EXTEND", "EVALUATED_FAIL", "CANCELLED",
    )


def assert_payroll_handoff(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in (
        "DRAFT", "TRANSMITTED", "ACKNOWLEDGED", "REJECTED_BY_PAYROLL", "SUPERSEDED", "WITHDRAWN",
    )
    assert isinstance(data.get("base_salary_cents"), int)
    assert isinstance(data.get("first_period_gross_cents"), int)


def assert_survey(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("status") in ("SENT", "SUBMITTED", "EXPIRED", "CANCELLED")


def assert_case_health_invariants(case_data: dict):
    """Domain invariants that must hold for the health dimension."""
    score = case_data["health_score"]
    assert 0 <= score <= 100, f"health_score {score} out of bounds"
    expected_label = "ON_TRACK" if score >= 70 else "AT_RISK"
    assert case_data["health"] == expected_label, (
        f"health label {case_data['health']} inconsistent with score {score}"
    )
