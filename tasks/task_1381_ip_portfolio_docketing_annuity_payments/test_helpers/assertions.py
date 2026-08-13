"""Entity assertions and domain invariant checkers (PRD §2.6, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_jurisdiction_rule(data: dict):
    _assert_common(data)
    assert data["jurisdiction"] in ["US", "EP", "JP", "CN", "KR", "PCT"]


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_client_contact(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_counsel_firm(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["accredited_jurisdictions"], list)


def assert_inventor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_patent_family(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in ["ACTIVE", "PRUNING_REVIEW", "CLOSED"]
    assert isinstance(data["committed_forecast_cents"], int)
    assert isinstance(data["budget_cap_cents"], int)


def assert_application(data: dict):
    _assert_common(data)
    assert data["jurisdiction"] in ["US", "EP", "JP", "CN", "KR", "PCT"]
    assert data["application_type"] in [
        "ORIGINAL", "PARIS_CONVENTION", "PCT_INTERNATIONAL",
        "PCT_NATIONAL_PHASE", "CONTINUATION", "DIVISIONAL",
    ]
    assert data["entity_size"] in ["LARGE", "SMALL"]
    assert data["status"] in ["DRAFT", "PENDING", "GRANTED", "ABANDONED", "LAPSED", "WITHDRAWN"]
    assert isinstance(data["open_docket_count"], int)


def assert_docket_entry(data: dict):
    _assert_common(data)
    assert data["entry_type"] in [
        "OFFICE_ACTION_RESPONSE", "STATUTORY", "PARIS_PRIORITY",
        "PCT_PHASE", "ANNUITY", "RECORDATION",
    ]
    assert data["status"] in ["PENDING", "IN_PROGRESS", "RESPONSE_FILED", "COMPLETED", "CANCELLED", "LAPSED"]
    assert isinstance(data["extension_count"], int)
    assert isinstance(data["extension_fees_total_cents"], int)


def assert_office_action(data: dict):
    _assert_common(data)
    assert data["action_type"] in [
        "NON_FINAL_REJECTION", "FINAL_REJECTION", "NOTICE_OF_ALLOWANCE", "INFORMATIONAL",
    ]
    assert data["status"] in ["RECEIVED", "UNDER_RESPONSE", "CLOSED"]


def assert_annuity_obligation(data: dict):
    _assert_common(data)
    assert isinstance(data["period_year"], int)
    assert data["status"] in [
        "SCHEDULED", "PENDING_AUTHORIZATION", "AUTHORIZED", "PAYMENT_INSTRUCTED",
        "CONFIRMATION_QUERY", "PAID_CONFIRMED", "LAPSED", "CANCELLED",
    ]


def assert_payment_authorization(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["REQUESTED", "APPROVED", "RELEASED", "REJECTED", "SUPERSEDED"]


def assert_instruction(data: dict):
    _assert_common(data)
    assert data["instruction_type"] in ["FILING", "OA_RESPONSE", "ANNUITY_PAYMENT", "RECORDATION"]
    assert data["status"] in [
        "DRAFT", "SENT", "ACKNOWLEDGED", "CONFIRMED", "COMPLETED", "DECLINED", "CANCELLED",
    ]


def assert_abandonment_review(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "UNDER_REVIEW", "APPROVED", "REJECTED", "EXECUTED"]


def assert_assignment_record(data: dict):
    _assert_common(data)
    assert isinstance(data["assignee_name"], str) and len(data["assignee_name"]) > 0
    assert isinstance(data["inventor_ids"], list)
    assert data["status"] in ["DRAFT", "EXECUTED", "RECORDATION_REJECTED", "RECORDED"]


def assert_docket_audit(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "VARIANCE_FOUND", "RESOLVED", "CLOSED_CLEAN"]
    assert isinstance(data["variances"], list)


def assert_family_committed_invariant(family: dict):
    """Family rollup never negative and never above its budget cap after a successful write."""
    assert family["committed_forecast_cents"] >= 0
    assert family["committed_forecast_cents"] <= family["budget_cap_cents"]


def assert_open_docket_count_non_negative(application: dict):
    assert application["open_docket_count"] >= 0
