"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer >= 1"
    )


def assert_partner_agreement(data: dict):
    _assert_common_fields(data, "PartnerAgreement")
    assert isinstance(data["host_institution"], str) and data["host_institution"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert data["status"] in ("DRAFT", "ACTIVE")


def assert_program(data: dict):
    _assert_common_fields(data, "Program")
    assert isinstance(data["partner_agreement_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert data["term"] in ("SPRING", "SUMMER", "FALL", "ACADEMIC_YEAR")
    assert data["billing_model"] in ("HOME_TUITION", "PROGRAM_FEE")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["seats_taken"], int) and data["seats_taken"] >= 0
    assert data["status"] in ("DRAFT", "OPEN", "SUSPENDED")


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert 0.0 <= data["gpa"] <= 4.0
    assert data["conduct_standing"] in ("GOOD_STANDING", "CONDUCT_REVIEW", "CONDUCT_HOLD")
    assert isinstance(data["aid_award_cents"], int) and data["aid_award_cents"] >= 0


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert isinstance(data["student_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["aid_award_cents_snapshot"], int)
    assert data["status"] in (
        "SUBMITTED", "RETURNED_FOR_REVISION", "CLEARED", "APPROVED", "COMMITTED",
        "ABROAD", "RETURNED_HOME", "CREDIT_POSTED", "REJECTED", "WITHDRAWN",
    )
    assert "clearance_recorded_by" in data
    assert "approved_by" in data
    assert "withdraw_reason" in data


def assert_course_preapproval(data: dict):
    _assert_common_fields(data, "CoursePreApproval")
    assert isinstance(data["application_id"], str)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert data["host_credits"] > 0
    assert isinstance(data["home_credits_est"], (int, float))
    assert data["status"] in ("PENDING", "APPROVED", "NEEDS_REVISION", "REJECTED", "SUPERSEDED")
    assert "reviewed_by" in data
    assert "review_notes" in data


def assert_travel_advisory(data: dict):
    _assert_common_fields(data, "TravelAdvisory")
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert data["level"] in ("CAUTION", "WARNING", "DO_NOT_TRAVEL")
    assert data["status"] in ("ACTIVE", "LIFTED")


def assert_insurance_enrollment(data: dict):
    _assert_common_fields(data, "InsuranceEnrollment")
    assert isinstance(data["application_id"], str)
    assert isinstance(data["provider"], str) and data["provider"]
    assert isinstance(data["coverage_start_date"], str)
    assert isinstance(data["coverage_end_date"], str)
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_billing_statement(data: dict):
    _assert_common_fields(data, "BillingStatement")
    assert isinstance(data["application_id"], str)
    assert data["billing_model_snapshot"] in ("HOME_TUITION", "PROGRAM_FEE")
    for money_field in (
        "base_cents", "insurance_premium_cents", "application_fee_cents",
        "aid_portable_cents", "charge_cents", "amount_paid_cents",
        "credit_memo_cents", "outstanding_cents",
    ):
        assert isinstance(data[money_field], int), (
            f"BillingStatement.{money_field} must be integer cents"
        )
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "VOID")


def assert_incident(data: dict):
    _assert_common_fields(data, "Incident")
    assert isinstance(data["application_id"], str)
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data["description"], str)
    assert data["status"] in ("REPORTED", "TRIAGED", "ESCALATED", "RESOLVED")
    assert "reported_by" in data
    assert "resolution_notes" in data


def assert_credit_posting(data: dict):
    _assert_common_fields(data, "CreditPosting")
    assert isinstance(data["application_id"], str)
    assert isinstance(data["lines"], list)
    assert isinstance(data["provisional_credits"], (int, float))
    assert isinstance(data["final_credits"], (int, float))
    assert data["status"] in ("PENDING", "POSTED")
    assert "posted_by" in data


def assert_billing_money_invariants(data: dict):
    """Money relationships that hold on any BillingStatement (PRD §3.4)."""
    assert isinstance(data["charge_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    if data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID"):
        assert data["outstanding_cents"] == data["charge_cents"] - data["amount_paid_cents"], (
            "outstanding_cents must equal charge_cents - amount_paid_cents while not VOID"
        )
    if data["status"] == "VOID":
        assert data["outstanding_cents"] == 0, "VOID statement forces outstanding_cents to 0"
