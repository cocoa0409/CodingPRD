"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_client(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in [
        "SUBMITTED", "DOCS_REQUESTED", "SCREENED", "ELIGIBLE",
        "INELIGIBLE", "WAITLISTED", "OPENED", "WITHDRAWN",
    ]
    assert data["case_type"] in [
        "EVICTION_DEFENSE", "FAMILY_DV", "BENEFITS_APPEAL",
        "CONSUMER_DEBT", "IMMIGRATION_RELIEF", "EXPUNGEMENT",
    ]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_conflict_check(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["result"] in [
        "CLEAR", "POTENTIAL_CONFLICT", "CONFIRMED_CONFLICT", "WAIVED", "EXPIRED",
    ]
    assert is_iso8601_timestamp(data.get("checked_at", "")), "checked_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("valid_until", "")), "valid_until must be ISO 8601"


def assert_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PENDING_ASSIGNMENT", "OPEN", "ON_HOLD", "CLOSED"]
    assert data["funding_status"] in [
        "UNFUNDED", "GRANT_RESERVED", "GRANT_FROZEN", "GRANT_SPENT", "GRANT_RELEASED",
    ]
    assert data["placement"] in ["INTERNAL", "PRO_BONO"]
    assert data["service_level"] in ["ADVICE_ONLY", "EXTENDED"]
    assert data["case_weight"] in [2, 5]
    assert isinstance(data["reserved_cents"], int) and data["reserved_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_staff_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["staff_type"] in ["ATTORNEY", "PARALEGAL", "INTAKE_SPECIALIST"]
    assert data["status"] in ["ACTIVE", "ON_LEAVE", "SEPARATED"]
    assert isinstance(data["max_units"], int) and data["max_units"] >= 1
    assert isinstance(data["weighted_open_units"], int) and data["weighted_open_units"] >= 0
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0


def assert_panel_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "SUSPENDED", "INACTIVE"]
    assert isinstance(data["max_active_referrals"], int) and data["max_active_referrals"] >= 1
    assert isinstance(data["active_referral_count"], int) and data["active_referral_count"] >= 0


def assert_referral(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in [
        "OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN", "COMPLETED",
    ]
    assert is_iso8601_timestamp(data.get("offered_at", "")), "offered_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("response_deadline", "")), "response_deadline must be ISO 8601"


def assert_grant_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] >= 0
    assert isinstance(data["reserved_cents"], int) and data["reserved_cents"] >= 0
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0
    assert isinstance(data["available_cents"], int)


def assert_grant_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED"]
    assert isinstance(data["cases_opened_count"], int)
    assert isinstance(data["cases_closed_count"], int)


def assert_venue_rule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["venue"] in [
        "SUPERIOR_COURT", "HOUSING_COURT", "FAMILY_COURT",
        "MUNICIPAL_COURT", "ADMIN_TRIBUNAL", "FEDERAL_TRIBUNAL",
    ]
    assert isinstance(data["priority_base_weight"], int)
    assert 1 <= data["priority_base_weight"] <= 100


def assert_time_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["activity_code"] in [
        "RESEARCH", "CLIENT_MEETING", "COURT_APPEARANCE", "DRAFTING", "ADMIN",
    ]


def assert_survey(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5
    assert isinstance(data["would_recommend"], bool)


def assert_unmet_need_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["reason_code"] in [
        "OVER_INCOME", "NO_EXTENDED_CAPACITY", "CONFLICT_CONFIRMED", "CLIENT_WITHDRAWN",
    ]


def assert_waitlist_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["required_weight"] in [2, 5]


def assert_grant_ledger_invariants(program: dict):
    """PRD §2.11 conservation invariant: reserved + spent + available == total."""
    assert (
        program["reserved_cents"] + program["spent_cents"] + program["available_cents"]
        == program["total_budget_cents"]
    ), (
        f"grant ledger violated conservation: {program['reserved_cents']} + "
        f"{program['spent_cents']} + {program['available_cents']} != "
        f"{program['total_budget_cents']}"
    )
