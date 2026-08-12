"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_name: str):
    assert isinstance(data, dict), f"{entity_name} payload must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 timestamp"


def assert_funder(data: dict):
    _assert_common_fields(data, "Funder")
    assert isinstance(data["name"], str) and data["name"]
    assert data["funder_type"] in ["FEDERAL", "STATE", "FOUNDATION", "CORPORATE"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data.get("requires_match", False), bool)


def assert_grant(data: dict):
    _assert_common_fields(data, "Grant")
    assert is_valid_uuid(data.get("funder_id", "")), "Grant.funder_id must be a UUID"
    assert isinstance(data["award_number"], str) and data["award_number"]
    assert isinstance(data["title"], str)
    assert isinstance(data["award_amount_cents"], int)
    assert data["reporting_frequency"] in [
        "MONTHLY", "QUARTERLY", "SEMIANNUAL", "ANNUAL",
    ]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSEOUT", "CLOSED"]
    assert isinstance(data["total_expended_cents"], int)
    assert data["total_expended_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["interim_report_due_days"], int)
    assert isinstance(data["final_report_due_days"], int)
    assert isinstance(data["renewal_window_days"], int)
    assert isinstance(data["required_match_cents"], int)
    # original_end_date snapshot must be present once the grant exists
    assert "original_end_date" in data


def assert_budget_line(data: dict):
    _assert_common_fields(data, "BudgetLine")
    assert data["category"] in [
        "PERSONNEL", "FRINGE", "TRAVEL", "EQUIPMENT",
        "SUPPLIES", "CONTRACTUAL", "INDIRECT", "OTHER",
    ]
    assert isinstance(data["budgeted_cents"], int)
    assert isinstance(data["adjusted_cents"], int)
    assert isinstance(data["expended_cents"], int)
    assert data["expended_cents"] >= 0
    assert isinstance(data["period_budgets_cents"], list)
    for entry in data["period_budgets_cents"]:
        assert isinstance(entry, int), "period budgets are integer cents"


def assert_fund(data: dict):
    _assert_common_fields(data, "Fund")
    assert data["fund_type"] in ["RESTRICTED", "UNRESTRICTED"]
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["expended_cents"], int)
    assert data["expended_cents"] >= 0
    assert isinstance(data["remaining_cents"], int)
    assert (
        data["remaining_cents"] == data["allocated_cents"] - data["expended_cents"]
    ), "remaining_cents must equal allocated_cents - expended_cents"
    assert isinstance(data["allowed_categories"], list)


def assert_expense(data: dict):
    _assert_common_fields(data, "Expense")
    assert data["status"] in ["DRAFT", "POSTED", "VOIDED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["unallocated_cents"], int)
    assert 0 <= data["unallocated_cents"] <= data["amount_cents"]
    assert isinstance(data["vendor"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["created_by_user_id"], str)


def assert_allocation(data: dict):
    _assert_common_fields(data, "ExpenseAllocation")
    assert data["status"] in ["ACTIVE", "VOIDED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_valid_uuid(data.get("budget_line_id", ""))
    assert is_valid_uuid(data.get("fund_id", ""))
    assert is_valid_uuid(data.get("expense_id", ""))


def assert_report(data: dict):
    _assert_common_fields(data, "Report")
    assert data["status"] in [
        "SCHEDULED", "DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED", "ACCEPTED",
    ]
    assert data["period_type"] in ["INTERIM", "FINAL"]
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["narrative_draft"], str)
    assert isinstance(data["outcome_entries"], list)
    assert isinstance(data["frozen"], bool)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["submitted_late"], bool)
    assert "due_date" in data
    assert "period_start" in data
    assert "period_end" in data


def assert_variance_explanation(data: dict):
    _assert_common_fields(data, "VarianceExplanation")
    assert data["status"] in ["DRAFTED", "LOCKED", "SUBMITTED"]
    assert isinstance(data["explanation_text"], str) and data["explanation_text"]
    assert is_valid_uuid(data.get("budget_line_id", ""))
    assert is_valid_uuid(data.get("report_id", ""))


def assert_match_contribution(data: dict):
    _assert_common_fields(data, "MatchContribution")
    assert data["status"] in ["PLEDGED", "DOCUMENTED", "VERIFIED"]
    assert data["contribution_type"] in [
        "CASH", "IN_KIND_GOODS", "IN_KIND_SERVICES", "VOLUNTEER_TIME",
    ]
    assert data["valuation_basis"] in ["FAIR_MARKET", "ACTUAL_COST", "STANDARD_RATE"]
    assert isinstance(data["recognized_value_cents"], int)
    assert data["recognized_value_cents"] >= 0


def assert_modification_request(data: dict):
    _assert_common_fields(data, "ModificationRequest")
    assert data["request_type"] in ["NO_COST_EXTENSION", "BUDGET_REALLOCATION"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "DENIED", "WITHDRAWN",
    ]
    assert isinstance(data["justification"], str)


def assert_audit_engagement(data: dict):
    _assert_common_fields(data, "AuditEngagement")
    assert data["engagement_type"] in ["FINANCIAL_AUDIT", "SITE_VISIT", "DESK_REVIEW"]
    assert data["status"] in [
        "SCHEDULED", "PREPARATION", "READY", "CONDUCTED", "FINDINGS_ISSUED", "CLOSED",
    ]
    assert isinstance(data["auditor_org"], str) and data["auditor_org"]
    assert "scheduled_start" in data
    assert "scheduled_end" in data


def assert_audit_finding(data: dict):
    _assert_common_fields(data, "AuditFinding")
    assert data["severity"] in ["OBSERVATION", "DEFICIENCY", "MATERIAL_WEAKNESS"]
    assert data["status"] in ["OPEN", "RESPONSE_SUBMITTED", "RESOLVED"]
    assert isinstance(data["description"], str)


def assert_renewal_application(data: dict):
    _assert_common_fields(data, "RenewalApplication")
    assert data["status"] in [
        "NOT_OPEN", "ELIGIBLE", "SUBMITTED", "RENEWED", "DECLINED", "LAPSED",
    ]
    assert "window_open" in data
    assert "window_close" in data


def assert_error_envelope(response_json: dict):
    """PRD §2.2 error envelope shape."""
    assert response_json.get("response_type") == "error"
    data = response_json.get("data", {})
    assert isinstance(data.get("error_id"), str) and data["error_id"]
    assert isinstance(data.get("message"), str) and data["message"]
    meta = response_json.get("meta", {})
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
