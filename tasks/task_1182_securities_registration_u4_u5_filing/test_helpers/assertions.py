"""Entity assertions and domain invariant checkers (PRD Sections 2.4, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_firm(data: dict):
    _assert_common(data)
    assert isinstance(data["crd_number"], str) and data["crd_number"].isdigit()
    assert 1 <= len(data["crd_number"]) <= 7
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_inquiry_count"], int) and data["open_inquiry_count"] >= 0


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["crd_number"], str) and data["crd_number"].isdigit()
    assert 1 <= len(data["crd_number"]) <= 7
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["fingerprint_required"], bool)


def assert_registration_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["firm_id"])
    assert data["registration_category"] in ("RR", "IA", "PRINCIPAL")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "DEFICIENT", "APPROVED", "ACTIVE",
        "WITHDRAWN", "DENIED", "TERMINATED",
    )
    assert isinstance(data["deficiency_count"], int) and data["deficiency_count"] >= 0


def assert_jurisdiction_selection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["registration_request_id"])
    assert isinstance(data["jurisdiction_code"], str)
    assert data["jurisdiction_type"] in ("STATE", "SRO")
    assert data["status"] in ("SELECTED", "APPROVED", "REJECTED", "RELINQUISHED")
    assert isinstance(data["annual_fee_cents"], int) and data["annual_fee_cents"] >= 0


def assert_fingerprint_submission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["registration_request_id"])
    assert data["submission_channel"] in ("ELECTRONIC", "HARD_CARD")
    assert data["status"] in ("SUBMITTED", "CLEARED", "REJECTED")


def assert_background_disclosure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["registration_request_id"])
    assert data["question_code"] in (
        "CRIMINAL", "REGULATORY", "FINANCIAL", "CIVIL", "EMPLOYMENT",
    )
    assert isinstance(data["answer"], bool)
    assert data["review_status"] in ("PENDING_REVIEW", "CLEARED", "FLAGGED")


def assert_exam_requirement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["registration_request_id"])
    assert data["exam_code"] in ("SIE", "S7", "S63", "S66", "S24")
    assert data["status"] in ("REQUIRED", "SCHEDULED", "PASSED", "WAIVED", "EXPIRED")


def assert_exam_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["exam_requirement_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("SCHEDULED", "OPEN", "USED", "CANCELLED")


def assert_disclosure_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["applicant_id"])
    assert data["event_type"] in (
        "CRIMINAL_CHARGE", "REGULATORY_ACTION", "BANKRUPTCY",
        "CIVIL_JUDGMENT", "CUSTOMER_COMPLAINT",
    )
    assert isinstance(data["event_date"], str)
    assert data["status"] in ("OPEN", "AMENDED", "LATE_AMENDED")


def assert_amendment_filing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["disclosure_event_id"])
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["narrative_text"], str) and len(data["narrative_text"]) >= 20
    assert data["status"] in ("FILED", "ACCEPTED", "RETURNED")


def assert_termination_filing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["registration_request_id"])
    assert data["termination_reason"] in (
        "VOLUNTARY", "PERMITTED_TO_RESIGN", "DISCHARGED", "DECEASED",
    )
    assert isinstance(data["termination_date"], str)
    assert isinstance(data["is_late"], bool)
    assert data["status"] in ("FILED", "AMENDMENT_OPEN", "CLOSED")


def assert_u5_comment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["termination_filing_id"])
    assert data["author_role"] in ("COMPLIANCE_OFFICER", "REGISTRATION_PRINCIPAL")
    assert isinstance(data["comment_text"], str) and len(data["comment_text"]) >= 10
    assert data["disposition"] in ("PENDING", "CONSISTENT", "INCONSISTENT")


def assert_affiliation_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["second_firm_id"])
    assert is_valid_uuid(data["first_registration_request_id"])
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "REVOKED")


def assert_renewal_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["registration_request_id"])
    assert isinstance(data["cycle_year"], int) and 2026 <= data["cycle_year"] <= 2100
    for field in (
        "jurisdiction_fee_cents", "base_fee_cents",
        "late_surcharge_cents", "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0, f"{field} must never be negative"
    assert data["total_cents"] == (
        data["jurisdiction_fee_cents"]
        + data["base_fee_cents"]
        + data["late_surcharge_cents"]
    ), "total_cents must equal the sum of the three pinned components"
    assert data["status"] in ("ISSUED", "PAID", "VOID")


def assert_regulatory_inquiry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["firm_id"])
    assert data["subject_filing_type"] in (
        "REGISTRATION_REQUEST", "AMENDMENT_FILING", "TERMINATION_FILING",
    )
    assert isinstance(data["subject_filing_id"], str)
    assert isinstance(data["inquiry_text"], str) and len(data["inquiry_text"]) >= 20
    assert data["status"] in ("OPEN", "PENDING_RESPONSE", "RESPONDED", "CLOSED")
