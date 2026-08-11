"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_employer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["industry_code"], str)
    assert isinstance(data["contact_email"], str)
    assert data["status"] in ("PROSPECT", "ACTIVE", "DORMANT")
    assert isinstance(data["lifetime_billed_cents"], int)
    assert isinstance(data["follow_on_pipeline_cents"], int)


def assert_needs_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["skill_gaps"], list)
    assert isinstance(data["target_roles"], list)
    assert isinstance(data["curriculum_modules"], list)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REVISION_REQUESTED")
    assert isinstance(data["revision_round"], int)


def assert_training_agreement(data: dict):
    _assert_common(data)
    assert data["contract_status"] in (
        "DRAFT", "QUOTED", "NEGOTIATING", "SIGNED", "IN_DELIVERY", "COMPLETED", "CANCELLED",
    )
    assert data["billing_status"] in ("UNBILLED", "PARTIALLY_BILLED", "SETTLED")
    assert data["pricing_model"] in ("PER_PARTICIPANT", "FLAT_COHORT")
    assert data["delivery_mode"] in ("ON_SITE", "ON_CAMPUS")
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["negotiation_round"], int)
    assert isinstance(data["assessment_version_pinned"], int)


def assert_grant_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "SUSPENDED", "CLOSED")
    for f in ("appropriation_cents", "available_cents", "reserved_cents",
              "committed_cents", "reimbursed_cents", "cap_per_trainee_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"


def assert_grant_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED", "APPROVED",
        "DENIED", "CLAIMED", "PAID", "EXPIRED", "WITHDRAWN",
    )
    assert isinstance(data["requested_cents"], int)


def assert_instructor(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["credentials"], list)
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["committed_hours"], (int, float))


def assert_venue(data: dict):
    _assert_common(data)
    assert data["kind"] in ("CAMPUS_LAB", "EMPLOYER_SITE")
    assert isinstance(data["capacity"], int)
    assert isinstance(data["hourly_cost_cents"], int)
    assert isinstance(data["turnover_buffer_minutes"], int)


def assert_cohort(data: dict):
    _assert_common(data)
    assert data["delivery_status"] in (
        "SCHEDULED", "LAUNCHED", "IN_PROGRESS", "DELIVERED", "CREDENTIALED", "CANCELLED",
    )
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID")
    assert data["delivery_mode"] in ("ON_SITE", "ON_CAMPUS")
    assert isinstance(data["enrolled_count"], int)
    assert isinstance(data["completer_count"], int)
    assert isinstance(data["min_enrollment"], int)


def assert_session(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "HELD", "CANCELLED")
    assert isinstance(data["attendance_closed"], bool)
    assert isinstance(data["hours"], (int, float))


def assert_instructor_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "CONFIRMED", "RELEASED", "COMPLETED")
    assert isinstance(data["instructor_id"], str)
    assert isinstance(data["session_id"], str)


def assert_participant(data: dict):
    _assert_common(data)
    assert data["completion_status"] in ("ENROLLED", "COMPLETED", "DROPPED", "NO_SHOW")
    assert isinstance(data["external_employee_ref"], str)
    assert isinstance(data["attended_hours"], (int, float))
    assert isinstance(data["attendance_pct"], (int, float))


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["grant_offset_cents"], int)
    assert isinstance(data["net_due_cents"], int)
    assert isinstance(data["lines"], list)


def assert_outcome_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED")
    assert isinstance(data["completers_employed_90d"], int)
    assert isinstance(data["follow_on_opportunity_cents"], int)


def assert_program_fund_invariant(program: dict):
    """Grant-program ledger invariant: available + reserved + committed +
    reimbursed == appropriation (PRD §2.10)."""
    total = (
        program["available_cents"]
        + program["reserved_cents"]
        + program["committed_cents"]
        + program["reimbursed_cents"]
    )
    assert total == program["appropriation_cents"], (
        f"fund conservation violated: {total} != {program['appropriation_cents']}"
    )
