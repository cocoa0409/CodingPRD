"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def assert_contract(data: dict):
    _common(data)
    assert isinstance(data["employer_name"], str) and len(data["employer_name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["sessions_per_issue"], int)
    assert isinstance(data["annual_session_cap"], int)
    assert isinstance(data["session_rate_cents"], int)
    assert isinstance(data["annual_reimbursement_budget_cents"], int)
    assert isinstance(data["sessions_committed"], int) and data["sessions_committed"] >= 0
    assert isinstance(data["utilization_rate"], (int, float)) and data["utilization_rate"] >= 0


def assert_plan(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")
    assert isinstance(data["name"], str)


def assert_employee(data: dict):
    _common(data)
    assert data["eligibility_status"] in ("ELIGIBLE", "GRACE", "INELIGIBLE")
    assert isinstance(data["full_name"], str)


def assert_dependent(data: dict):
    _common(data)
    assert data["relationship"] in ("SPOUSE", "CHILD", "OTHER")
    assert data["eligibility_status"] in ("ELIGIBLE", "INELIGIBLE")


def assert_case(data: dict):
    _common(data)
    assert data["clinical_status"] in ("INTAKE", "OPEN", "CLOSED")
    assert data["funding_status"] in ("PENDING", "AUTHORIZED", "EXHAUSTED", "REVOKED")


def assert_session(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_provider(data: dict):
    _common(data)
    assert data["network_status"] in ("IN_NETWORK", "OUT_OF_NETWORK")
    assert isinstance(data["active_referral_count"], int) and data["active_referral_count"] >= 0


def assert_referral(data: dict):
    _common(data)
    assert data["referral_type"] in ("CLINICAL", "WORKLIFE", "LEGAL", "FINANCIAL")
    assert data["status"] in ("REQUESTED", "ACCEPTED", "DECLINED",
                              "COMPLETED", "CANCELLED", "DENIED")


def assert_crisis_contact(data: dict):
    _common(data)
    assert data["severity"] in ("LOW", "MODERATE", "HIGH", "IMMINENT")
    assert data["status"] in ("OPEN", "TRIAGED", "ESCALATED", "RESOLVED")
    assert isinstance(data["sla_breached"], bool)


def assert_claim(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED",
                              "REJECTED", "RESUBMITTED", "PAID")
    assert isinstance(data["provisional_cents"], int) and data["provisional_cents"] >= 0


def assert_report(data: dict):
    """UtilizationReport is common_fields:false — id + created_at only, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["suppressed"], bool)


def assert_wellness_activity(data: dict):
    _common(data)
    assert data["activity_type"] in ("SCREENING", "WEBINAR", "CHALLENGE", "COACHING")
