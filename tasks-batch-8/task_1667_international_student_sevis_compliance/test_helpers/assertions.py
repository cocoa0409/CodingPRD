"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_SEVIS_ID_RE = re.compile(r"^N[0-9]{10}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_iso_date(value, field: str):
    assert isinstance(value, str) and _ISO_DATE_RE.match(value), (
        f"{field} must be an ISO 8601 date (YYYY-MM-DD), got {value!r}"
    )


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sevis_id"], str) and _SEVIS_ID_RE.match(data["sevis_id"]), (
        "sevis_id must be the letter N followed by ten digits"
    )
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    _assert_iso_date(data["date_of_birth"], "date_of_birth")
    assert isinstance(data["country_of_citizenship"], str)
    assert data["degree_level"] in ("UNDERGRADUATE", "GRADUATE")
    assert data["compliance_posture"] in ("CLEAR", "AT_RISK", "VIOLATION_OPEN")


def assert_financial_document(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert data["document_type"] in (
        "BANK_STATEMENT", "SCHOLARSHIP_LETTER", "SPONSOR_AFFIDAVIT",
    )
    assert isinstance(data["amount_usd_cents"], int) and data["amount_usd_cents"] >= 0
    _assert_iso_date(data["issue_date"], "issue_date")
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED")


def assert_sevis_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    _assert_iso_date(data["program_start_date"], "program_start_date")
    _assert_iso_date(data["program_end_date"], "program_end_date")
    assert data["status"] in (
        "DRAFT", "INITIAL", "ACTIVE", "COMPLETED", "TERMINATED",
        "REINSTATEMENT_PENDING", "TRANSFERRED_OUT",
    )


def assert_i20_form(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert isinstance(data["sevis_record_id"], str) and data["sevis_record_id"]
    assert isinstance(data["program_name"], str) and data["program_name"]
    for field in ("tuition_cents", "living_cents", "insurance_cents", "other_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer of cents"
        )
    assert isinstance(data["estimated_total_cents"], int)
    assert data["estimated_total_cents"] == (
        data["tuition_cents"] + data["living_cents"]
        + data["insurance_cents"] + data["other_cents"]
    ), "estimated_total_cents must be the integer sum of the four cost lines"
    assert data["status"] in ("DRAFT", "ISSUED", "SUPERSEDED", "CANCELLED")


def assert_term_enrollment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert isinstance(data["term_code"], str) and data["term_code"]
    _assert_iso_date(data["term_start_date"], "term_start_date")
    _assert_iso_date(data["term_end_date"], "term_end_date")
    assert isinstance(data["enrolled_credits"], int) and data["enrolled_credits"] >= 0
    assert isinstance(data["effective_min_credits"], int)
    assert data["status"] in ("PENDING", "REGISTERED", "NOT_ENROLLED", "COMPLETED")


def assert_reduced_course_load(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["enrollment_id"], str) and data["enrollment_id"]
    assert data["reason_category"] in ("ACADEMIC", "MEDICAL", "FINAL_TERM")
    assert isinstance(data["requested_credits"], int) and data["requested_credits"] >= 0
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_employment_authorization(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert data["auth_type"] in ("CPT", "OPT_PRE", "OPT_POST")
    assert isinstance(data["hours_per_week"], int) and data["hours_per_week"] > 0
    _assert_iso_date(data["start_date"], "start_date")
    _assert_iso_date(data["end_date"], "end_date")
    assert isinstance(data["unemployment_days_settled"], int)
    assert isinstance(data["unemployment_days_as_of"], int)
    assert data["status"] in (
        "DRAFT", "RECOMMENDED", "FILED", "APPROVED", "DENIED",
        "CANCELLED", "COMPLETED", "REVOKED",
    )


def assert_employment_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["authorization_id"], str) and data["authorization_id"]
    assert isinstance(data["employer_name"], str) and data["employer_name"]
    _assert_iso_date(data["start_date"], "start_date")
    if data.get("end_date") is not None:
        _assert_iso_date(data["end_date"], "end_date")
    assert isinstance(data["hours_per_week"], int) and data["hours_per_week"] > 0


def assert_travel_endorsement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["i20_form_id"], str) and data["i20_form_id"]
    _assert_iso_date(data["travel_departure_date"], "travel_departure_date")
    _assert_iso_date(data["travel_return_date"], "travel_return_date")
    _assert_iso_date(data["valid_until"], "valid_until")
    assert data["status"] in ("ACTIVE", "EXPIRED", "VOIDED")


def assert_transfer_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert data["direction"] in ("OUT", "IN")
    assert isinstance(data["target_school_code"], str) and data["target_school_code"]
    _assert_iso_date(data["release_date"], "release_date")
    assert data["status"] in ("REQUESTED", "RELEASED", "CANCELLED")


def assert_program_extension(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    _assert_iso_date(data["new_program_end_date"], "new_program_end_date")
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_status_violation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert data["violation_type"] in (
        "FAILURE_TO_ENROLL", "UNAUTHORIZED_EMPLOYMENT",
        "UNEMPLOYMENT_LIMIT_EXCEEDED", "ADDRESS_REPORT_OVERDUE", "OTHER",
    )
    assert isinstance(data["description"], str)
    assert data["status"] in (
        "OPEN", "REINSTATEMENT_PENDING", "RESOLVED_REINSTATED",
        "RESOLVED_DENIED", "DISMISSED",
    )


def assert_address_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    _assert_iso_date(data["move_date"], "move_date")
    assert isinstance(data["address_line1"], str) and data["address_line1"]
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["postal_code"], str) and data["postal_code"]
    assert data["status"] in ("REPORTED", "FLAGGED_LATE")


def assert_unemployment_invariant(auth: dict):
    """PRD §3.5: for either counter variant, elapsed always equals covered
    plus unemployment; in particular the two counters are non-negative and
    the as-of figure never trails the settled figure by more than the one
    uncovered current day."""
    settled = auth["unemployment_days_settled"]
    as_of = auth["unemployment_days_as_of"]
    assert settled >= 0 and as_of >= 0
    assert as_of - settled in (0, 1), (
        f"as_of runs at most one day ahead of settled, got {as_of} vs {settled}"
    )
