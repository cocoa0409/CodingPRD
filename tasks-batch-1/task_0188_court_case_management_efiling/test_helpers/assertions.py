"""Entity assertions and domain invariant checkers.

These validate the shape of entity payloads against the PRD's field contracts.
All entities are mutable and carry id, created_at, updated_at, and version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and only increases"


def assert_court(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["jurisdiction_code"], str)
    assert isinstance(data["filing_fee_cents"], int) and data["filing_fee_cents"] >= 0
    assert isinstance(data["business_days_only"], bool)
    assert isinstance(data["holidays"], list)
    assert isinstance(data["appeal_window_days"], int)


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["court_id"], str)
    assert isinstance(data["case_number"], str) and len(data["case_number"]) > 0
    assert isinstance(data["caption"], str)
    assert data["case_type"] in ["CONTRACT", "TORT", "PROPERTY", "FAMILY"]
    assert data["status"] in [
        "DRAFT", "OPEN", "STAYED", "JUDGMENT_ENTERED", "ON_APPEAL", "CLOSED"
    ]
    assert data["posture"] in ["ACTIVE", "RESTRICTED", "FROZEN"]
    assert isinstance(data["open_deadline_count"], int) and data["open_deadline_count"] >= 0
    assert isinstance(data["total_fees_assessed_cents"], int)
    assert isinstance(data["total_fees_paid_cents"], int)


def assert_party(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["display_name"], str)
    assert data["role"] in ["PLAINTIFF", "DEFENDANT"]
    assert data["service_status"] in ["UNSERVED", "SERVED", "SERVICE_FAILED"]


def assert_filing(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["filed_by_party_id"], str)
    assert data["document_type"] in [
        "COMPLAINT", "ANSWER", "MOTION", "EXHIBIT", "PROOF_OF_SERVICE"
    ]
    assert isinstance(data["title"], str)
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "REJECTED"]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["fee_status"] in ["NONE", "ASSESSED", "PAID", "WAIVED"]


def assert_service_of_process(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["filing_id"], str)
    assert isinstance(data["served_party_id"], str)
    assert data["method"] in ["PERSONAL", "MAIL", "PUBLICATION"]
    assert data["status"] in ["ATTEMPTED", "COMPLETED", "FAILED"]


def assert_deadline(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["deadline_type"] in [
        "RESPONSE", "DISCOVERY", "MOTION_HEARING", "STATUTE_OF_LIMITATIONS", "APPEAL"
    ]
    assert data["anchor_event"] in [
        "SERVICE_COMPLETED", "FILING_ACCEPTED", "JUDGMENT_ENTERED", "CASE_OPENED", "MANUAL"
    ]
    assert data["counting_mode"] in ["CALENDAR", "COURT_DAYS"]
    assert isinstance(data["interval_days"], int) and data["interval_days"] >= 0
    assert is_iso8601_timestamp(data["due_date"]), "due_date must be ISO 8601"
    assert data["status"] in ["PENDING", "SATISFIED", "MISSED", "VACATED"]


def assert_motion(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["filing_id"], str)
    assert isinstance(data["moving_party_id"], str)
    assert data["motion_type"] in [
        "DISMISS", "SUMMARY_JUDGMENT", "CONTINUANCE", "COMPEL_DISCOVERY"
    ]
    assert data["status"] in [
        "FILED", "UNDER_SUBMISSION", "GRANTED", "DENIED", "GRANTED_IN_PART", "WITHDRAWN"
    ]
    assert isinstance(data["opposed"], bool)


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["motion_id"], str)
    assert data["disposition"] in ["GRANT", "DENY", "GRANT_IN_PART"]
    assert isinstance(data["stays_case"], bool)


def assert_fee_waiver(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["filing_id"], str)
    assert isinstance(data["requesting_party_id"], str)
    assert isinstance(data["monthly_income_cents"], int) and data["monthly_income_cents"] >= 0
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["status"] in ["PENDING", "NEEDS_INFO", "APPROVED", "DENIED"]
    assert isinstance(data["eligibility_ratio"], (int, float))


def assert_hearing(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["courtroom"], str)
    assert isinstance(data["judge_user_id"], str)
    assert is_iso8601_timestamp(data["start_at"]), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data["end_at"]), "end_at must be ISO 8601"
    assert data["status"] in ["SCHEDULED", "HELD", "CONTINUED", "CANCELLED"]


def assert_judgment(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["judgment_type"] in ["DEFAULT", "SUMMARY", "TRIAL", "DISMISSAL"]
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] >= 0
    assert isinstance(data["interest_rate_bps"], int) and data["interest_rate_bps"] >= 0
    assert isinstance(data["total_with_interest_cents"], int)
    assert data["status"] in ["ENTERED", "APPEALED", "SATISFIED", "VACATED"]


def assert_appeal(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["judgment_id"], str)
    assert isinstance(data["appellant_party_id"], str)
    assert data["status"] in ["NOTICE_FILED", "RECORD_PREPARED", "TRANSMITTED", "DISMISSED"]
    assert isinstance(data["record_page_count"], int) and data["record_page_count"] >= 0
