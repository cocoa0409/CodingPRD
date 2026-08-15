"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD §2.4 common resource properties."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_branch_office(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["inspection_cycle_months"], int)
    assert isinstance(data["open_findings_count"], int)
    assert isinstance(data["high_severity_open_count"], int)
    assert isinstance(data["sd_rep_count"], int)
    assert data["posture"] in ("NORMAL", "REMEDIATION_REQUIRED")
    assert isinstance(data["risk_score"], int)


def assert_representative(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", ""))
    assert isinstance(data["crd_number"], str) and data["crd_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["is_statutorily_disqualified"], bool)
    assert data["supervision_tier"] in ("STANDARD", "HEIGHTENED")
    assert isinstance(data["compliance_flag_count"], int)
    assert isinstance(data["active_approved_activity_count"], int)
    assert isinstance(data["pst_fee_total_cents"], int)


def assert_branch_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", ""))
    assert isinstance(data["scheduled_date"], str)
    assert data.get("started_at") is None or is_iso8601_timestamp(data["started_at"])
    assert data.get("completed_date") is None or isinstance(data["completed_date"], str)
    assert isinstance(data["open_findings_count"], int)
    assert isinstance(data["high_severity_open_count"], int)
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "AWAITING_REMEDIATION", "CLOSED",
    )


def assert_inspection_finding(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("inspection_id", ""))
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["due_date"], str)
    assert isinstance(data["reopen_count"], int)
    assert data["status"] in (
        "OPEN", "OVERDUE", "REMEDIATION_SUBMITTED", "VERIFIED_CLOSED",
    )


def assert_correspondence_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rep_id", ""))
    assert data["channel"] in ("EMAIL", "SMS", "SOCIAL_MEDIA", "PAPER_LETTER")
    assert isinstance(data["lexicon_hits"], int) and data["lexicon_hits"] >= 0
    assert isinstance(data["provisional_risk_score"], int)
    assert data.get("final_risk_score") is None or isinstance(
        data["final_risk_score"], int
    )
    assert data["status"] in (
        "PENDING_REVIEW", "OVERDUE", "ESCALATED", "APPROVED", "FLAGGED",
    )


def assert_outside_activity(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rep_id", ""))
    assert data["activity_type"] in (
        "OUTSIDE_BUSINESS_ACTIVITY", "PRIVATE_SECURITIES_TRANSACTION",
    )
    assert isinstance(data["compensation_expected"], bool)
    assert data.get("supervisory_fee_cents") is None or isinstance(
        data["supervisory_fee_cents"], int
    )
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "APPROVED_WITH_CONDITIONS", "REJECTED",
        "WITHDRAWN", "REVOKED", "SUSPENDED_REVIEW",
    )


def assert_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rep_id", ""))
    assert data["allegation_type"] in (
        "FORGERY", "THEFT", "MISREPRESENTATION", "SUITABILITY",
        "UNAUTHORIZED_TRADING", "OTHER",
    )
    assert isinstance(data["damages_claimed_cents"], int)
    assert data["damages_claimed_cents"] >= 0
    assert isinstance(data["reportable"], bool)
    assert isinstance(data["provisional_reserve_cents"], int)
    assert data["status"] in ("RECEIVED", "RESOLVED")
    assert data["regulatory_status"] in ("NOT_REQUIRED", "REQUIRED", "FILED")


def assert_disclosure_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rep_id", ""))
    assert data["event_type"] in (
        "FELONY_CONVICTION", "SECURITIES_MISDEMEANOR", "REGULATORY_BAR",
        "CUSTOMER_AWARD", "CIVIL_JUDGMENT", "BANKRUPTCY",
    )
    assert isinstance(data["is_sd_trigger"], bool)
    assert isinstance(data["filing_deadline"], str)
    assert data["status"] in ("DRAFT", "FILED", "ACKNOWLEDGED")


def assert_supervision_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rep_id", ""))
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["conditions"], list) and len(data["conditions"]) >= 1
    assert data.get("terminated_reason") is None or data["terminated_reason"] in (
        "MANUAL", "REP_TERMINATED",
    )
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED", "COMPLETED")


def assert_meeting(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["meeting_date"], str)
    assert data.get("held_at") is None or is_iso8601_timestamp(data["held_at"])
    assert data["status"] in ("SCHEDULED", "HELD", "CLOSED")


def assert_attestation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("meeting_id", ""))
    assert is_valid_uuid(data.get("rep_id", ""))
    assert isinstance(data["attest_deadline"], str)
    assert data.get("attested_at") is None or is_iso8601_timestamp(data["attested_at"])
    assert data["status"] in ("PENDING", "ATTESTED", "OVERDUE")


def assert_wsp_document(data: dict):
    _assert_common(data)
    assert data["policy_area"] in (
        "CORRESPONDENCE", "OBA_PST", "COMPLAINTS", "DISCLOSURE",
        "HEIGHTENED_SUPERVISION", "INSPECTIONS", "BOOKS_RECORDS",
    )
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_exam_request(data: dict):
    _assert_common(data)
    assert data["regulator"] in ("SEC", "FINRA", "STATE")
    assert data["document_type"] in (
        "TRADE_BLOTTER", "CORRESPONDENCE_LOG", "COMPLAINT_FILE",
        "WSP_COPY", "OBA_REGISTER",
    )
    assert isinstance(data["due_date"], str)
    assert data.get("is_late") is None or isinstance(data["is_late"], bool)
    assert data["status"] in ("OPEN", "OVERDUE", "FULFILLED")


def assert_branch_risk_invariants(data: dict):
    """PRD §3.2 branch risk invariants that hold after any operation."""
    assert 0 <= data["risk_score"] <= 100
    assert data["open_findings_count"] >= 0
    assert data["high_severity_open_count"] >= 0
    assert data["high_severity_open_count"] <= data["open_findings_count"]
    assert data["sd_rep_count"] >= 0
    if data["posture"] == "REMEDIATION_REQUIRED":
        assert data["high_severity_open_count"] >= 2
