"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """PRD §2.5: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and len(data["fein"]) == 9
    assert data["compliance_posture"] in ("GOOD_STANDING", "WATCH", "DELINQUENT")
    assert isinstance(data["open_notice_count"], int)
    assert isinstance(data["outstanding_penalty_cents"], int)
    assert isinstance(data["registered_state_count"], int)


def assert_tax_agency(data: dict):
    _assert_common_fields(data)
    assert data["agency_kind"] in ("STATE_WITHHOLDING", "STATE_UI", "LOCAL")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["agency_name"], str) and data["agency_name"]


def assert_reciprocity_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_a"], str) and len(data["state_a"]) == 2
    assert isinstance(data["state_b"], str) and len(data["state_b"]) == 2
    assert data["scope"] in ("FULL", "WAGES_ONLY")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED")


def assert_work_location(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert data["location_type"] in ("COMPANY_OFFICE", "REMOTE_HOME", "CLIENT_SITE")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["annual_wage_cents"], int) and data["annual_wage_cents"] > 0
    assert is_valid_uuid(data.get("current_work_location_id", ""))


def assert_nexus_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("WATCH", "THRESHOLD_MET", "CONFIRMED", "EXEMPT", "LAPSED")
    assert data["threshold_basis"] in ("NONE", "DAYS", "WAGES", "BOTH")
    assert isinstance(data["employee_days_ytd"], int)
    assert isinstance(data["wages_ytd_cents"], int)


def assert_registration(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "REJECTED", "ACTIVE", "CLOSED")
    assert data["registration_kind"] in ("STATE_WITHHOLDING", "STATE_UI", "LOCAL")


def assert_withholding_election(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "VALIDATED", "ACTIVE", "SUPERSEDED", "REVOKED", "REJECTED", "EXPIRED",
    )
    assert data["election_type"] in (
        "RECIPROCITY_EXEMPTION", "COURTESY_RESIDENT", "COURTESY_WORK",
    )
    assert is_valid_uuid(data.get("employee_id", ""))


def assert_local_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("CURRENT", "SUPERSEDED")
    assert data["resolution_source"] in ("AUTO_GEOCODE", "MANUAL_OVERRIDE")


def assert_ui_rate(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("RECEIVED", "UNDER_REVIEW", "CONTESTED", "EFFECTIVE", "SUPERSEDED")
    assert isinstance(data["final_rate_bp"], int)
    assert 50 <= data["final_rate_bp"] <= 900, "final_rate_bp clamped to [50, 900] (PRD §3.7)"


def assert_voluntary_contribution(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "DECLINED", "REMITTED", "APPLIED", "EXPIRED")
    assert isinstance(data["proposed_amount_cents"], int) and data["proposed_amount_cents"] > 0


def assert_location_change(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PENDING_REVIEW", "APPROVED", "REJECTED", "CANCELLED", "EFFECTIVE", "REVERSED",
    )
    assert is_valid_uuid(data.get("employee_id", ""))
    assert isinstance(data.get("from_location_snapshot"), dict)


def assert_filing_obligation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "DUE", "LATE", "FILED", "CONFIRMED", "WAIVED")
    assert data["obligation_kind"] in (
        "WITHHOLDING_RETURN", "WITHHOLDING_DEPOSIT", "UI_RETURN",
        "UI_CONTRIBUTION", "LOCAL_RETURN",
    )
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["late_days"], int)


def assert_agency_notice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "RECEIVED", "TRIAGED", "RESPONSE_IN_PROGRESS", "ESCALATED", "RESOLVED", "CLOSED",
    )
    assert data["severity"] in ("HIGH", "MEDIUM", "LOW")
    assert data["notice_type"] in (
        "PENALTY_ASSESSMENT", "RATE_NOTICE", "MISSING_RETURN", "ACCOUNT_INQUIRY", "AUDIT",
    )


def assert_abatement_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "GRANTED",
        "PARTIALLY_GRANTED", "DENIED", "WITHDRAWN",
    )
    assert data["abatement_type"] in ("FIRST_TIME", "REASONABLE_CAUSE", "STATUTORY")


def assert_employer_counter_invariants(data: dict):
    """PRD §2.7 aggregate counters are always non-negative."""
    assert data["open_notice_count"] >= 0
    assert data["outstanding_penalty_cents"] >= 0
    assert data["registered_state_count"] >= 0
