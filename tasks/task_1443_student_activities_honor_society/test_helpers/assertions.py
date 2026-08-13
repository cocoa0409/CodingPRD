"""Entity assertions and domain invariant checkers.

Each assert_* verifies the standard system-managed properties of PRD section
2.5 (id UUID, ISO 8601 created_at/updated_at, integer version >= 1) plus the
entity's own status vocabulary.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert isinstance(data, dict), f"{label}: response data must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}: version must be an integer starting at 1"


def assert_chapter(data: dict):
    _assert_common(data, "Chapter")
    assert isinstance(data["school_name"], str) and data["school_name"]
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "DISSOLVED")
    assert data["standing"] in ("GOOD_STANDING", "PROBATIONARY", "REVOKED")
    assert isinstance(data["fund_balance_cents"], int)
    assert isinstance(data["dues_arrears_cents"], int)
    assert isinstance(data["active_member_count"], int)


def assert_member(data: dict):
    _assert_common(data, "Member")
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert data["grade_level"] in (9, 10, 11, 12)
    assert data["status"] in ("PROSPECTIVE", "CANDIDATE", "ACTIVE",
                              "ON_PROBATION", "DISMISSED", "ALUMNUS")


def assert_cycle(data: dict):
    _assert_common(data, "MembershipCycle")
    assert data["status"] in ("PLANNED", "NOMINATION", "REVIEW", "INDUCTED",
                              "CLOSED", "CANCELLED")
    assert data["semester"] in ("FALL", "SPRING")


def assert_application(data: dict):
    _assert_common(data, "CycleApplication")
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED",
                              "REJECTED", "INDUCTED", "WITHDRAWN")


def assert_service_entry(data: dict):
    _assert_common(data, "ServiceHourEntry")
    assert data["status"] in ("PENDING_VERIFICATION", "VERIFIED", "REJECTED",
                              "VOID")


def assert_election(data: dict):
    _assert_common(data, "OfficerElection")
    assert data["office"] in ("PRESIDENT", "VICE_PRESIDENT", "SECRETARY",
                              "TREASURER", "HISTORIAN")
    assert data["status"] in ("DRAFT", "OPEN", "TALLIED", "CERTIFIED",
                              "VOIDED")


def assert_vote(data: dict):
    _assert_common(data, "ElectionVote")
    assert data["status"] in ("CAST", "VOIDED")


def assert_officer_role(data: dict):
    _assert_common(data, "OfficerRole")
    assert data["office"] in ("PRESIDENT", "VICE_PRESIDENT", "SECRETARY",
                              "TREASURER", "HISTORIAN")
    assert data["status"] in ("ACTIVE", "RESIGNED", "REMOVED")


def assert_minutes(data: dict):
    _assert_common(data, "MeetingMinutes")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "AMENDED")


def assert_fundraiser(data: dict):
    _assert_common(data, "FundraiserRequest")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ADVISOR_APPROVED",
                              "DIRECTOR_APPROVED", "REJECTED", "EXECUTED",
                              "CLOSED")
    assert isinstance(data["goal_amount_cents"], int)
    assert isinstance(data["upfront_cost_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_common(data, "FundLedgerEntry")
    assert data["entry_type"] in ("FUNDRAISER_DEPOSIT",
                                  "UPFRONT_COST_DISBURSEMENT",
                                  "DUES_REMITTANCE", "NATIONAL_DUES_PAYMENT",
                                  "ADJUSTMENT")
    assert isinstance(data["amount_cents"], int), \
        "ledger amounts are whole cents (PRD section 2.8)"
    assert data["status"] in ("PENDING", "CLEARED", "VOIDED")


def assert_dues_payment(data: dict):
    _assert_common(data, "DuesPayment")
    assert data["status"] in ("PENDING_REMITTANCE", "REMITTED", "REFUNDED",
                              "VOID")


def assert_probation_case(data: dict):
    _assert_common(data, "ProbationCase")
    assert data["status"] in ("OPEN", "APPEALED", "RESOLVED", "DISMISSED")
    assert data["reason_code"] in ("GPA_BELOW_THRESHOLD",
                                   "SERVICE_HOURS_SHORTFALL",
                                   "CONDUCT_VIOLATION", "MISSED_MEETINGS")


def assert_athletics_block(data: dict):
    _assert_common(data, "AthleticsCalendarBlock")
    assert data["priority"] in ("PRACTICE", "GAME", "TOURNAMENT")
    assert data["status"] in ("ACTIVE", "CANCELLED")
