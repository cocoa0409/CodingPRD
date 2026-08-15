"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1"
    )


def assert_school_year(data: dict):
    _assert_common(data, "SchoolYear")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["member_tuition_cents"], int) and data["member_tuition_cents"] > 0
    assert isinstance(data["non_member_tuition_cents"], int) and data["non_member_tuition_cents"] > 0
    assert data["status"] in ["SETUP", "OPEN", "CLOSED"]


def assert_security_plan(data: dict):
    _assert_common(data, "SecurityPlan")
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACTIVE", "SUPERSEDED"]
    if data["status"] == "ACTIVE":
        assert is_iso8601_timestamp(data.get("approved_at", "")), (
            "approved_at must be set when ACTIVE"
        )
    else:
        assert data.get("approved_at") is None, "approved_at must be null when not ACTIVE"


def assert_family(data: dict):
    _assert_common(data, "Family")
    assert data["membership_status"] in ["MEMBER", "NON_MEMBER"]
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)


def assert_student(data: dict):
    _assert_common(data, "Student")
    assert data["grade"] in ["K", "G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert data["hebrew_level"] in ["BEGINNER", "INTERMEDIATE", "ADVANCED"]


def assert_teacher(data: dict):
    _assert_common(data, "Teacher")
    assert data["status"] in ["APPLIED", "VETTED", "HIRED", "SEPARATED"]


def assert_section(data: dict):
    _assert_common(data, "Section")
    assert data["status"] in ["OPEN", "FULL", "CLOSED"]
    assert data["staffing_status"] in ["STAFFED", "UNSTAFFED"]
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_enrollment(data: dict):
    _assert_common(data, "Enrollment")
    assert data["status"] in ["REGISTERED", "ACTIVE", "WITHDRAWN", "COMPLETED"]
    assert isinstance(data["estimated_tuition_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data, "TuitionInvoice")
    assert data["status"] in ["ISSUED", "PARTIALLY_PAID", "PAID", "VOID"]
    assert data["kind"] in ["TUITION", "VOLUNTEER_FEE"]
    assert isinstance(data["line_items"], list)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["balance_cents"], int)


def assert_payment(data: dict):
    _assert_common(data, "Payment")
    assert data["status"] in ["POSTED", "VOIDED"]
    assert isinstance(data["applications"], list)
    assert isinstance(data["remainder_cents"], int)


def assert_application(data: dict):
    _assert_common(data, "AssistanceApplication")
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED"]


def assert_session(data: dict):
    _assert_common(data, "Session")
    assert data["status"] in ["SCHEDULED", "HELD", "CANCELLED"]
    assert isinstance(data.get("attendance"), list)


def assert_milestone(data: dict):
    _assert_common(data, "Milestone")
    assert data["status"] in ["TRACKING", "ELIGIBLE", "SCHEDULED", "COMPLETED"]


def assert_commitment(data: dict):
    _assert_common(data, "VolunteerCommitment")
    assert data["status"] in ["OPEN", "FULFILLED", "DEFAULTED", "WAIVED"]
    assert isinstance(data["entries"], list)


def assert_invoice_money_invariants(inv: dict):
    """balance_cents = total_due_cents - credit_applied_cents - paid_cents + late_fees_cents."""
    expected = (
        inv["total_due_cents"]
        - inv["credit_applied_cents"]
        - inv["paid_cents"]
        + inv["late_fees_cents"]
    )
    assert inv["balance_cents"] == expected, (
        f"invoice balance invariant violated: balance {inv['balance_cents']} != {expected}"
    )
