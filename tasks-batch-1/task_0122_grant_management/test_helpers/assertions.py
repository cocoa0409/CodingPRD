"""Entity assertions and domain invariant checkers for the Grant Management API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_application(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["nofo_number"], str) and len(data["nofo_number"]) > 0
    assert isinstance(data["applicant_org_name"], str) and len(data["applicant_org_name"]) > 0
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] >= 1
    assert 0 < data["federal_share_pct"] <= 1
    assert data["status"] in {
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISIONS_REQUESTED",
        "AWARDED", "REJECTED", "WITHDRAWN",
    }


def assert_award(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["total_award_cents"], int)
    assert 0 < data["federal_share_pct"] <= 1
    assert isinstance(data["federal_ceiling_cents"], int)
    assert isinstance(data["federal_drawn_cents"], int)
    assert isinstance(data["federal_approved_expenditures_cents"], int)
    assert data["status"] in {"ACTIVE", "SUSPENDED", "PENDING_CLOSEOUT", "CLOSED"}


def assert_indirect_cost_rate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert data["rate_type"] in {"NEGOTIATED", "DE_MINIMIS"}
    assert data["base_type"] in {"MTDC", "TDC"}
    assert data["status"] in {"ACTIVE", "SUPERSEDED"}


def assert_subaward(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["subrecipient_name"], str) and len(data["subrecipient_name"]) > 0
    assert isinstance(data["subaward_amount_cents"], int) and data["subaward_amount_cents"] >= 1
    assert data["risk_tier"] in {"LOW", "MEDIUM", "HIGH"}
    assert data["status"] in {"PROPOSED", "APPROVED", "ACTIVE", "TERMINATED"}


def assert_restricted_fund(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert data["category"] in {
        "PERSONNEL", "EQUIPMENT", "TRAVEL", "SUPPLIES", "SUBAWARD_PASS_THROUGH", "INDIRECT",
    }
    assert isinstance(data["budgeted_cents"], int) and data["budgeted_cents"] >= 0
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0
    assert isinstance(data["priority_order"], int) and data["priority_order"] >= 1
    # PRD §3.5: allocated_cents may never exceed budgeted_cents.
    assert data["allocated_cents"] <= data["budgeted_cents"], "allocated_cents must not exceed budgeted_cents"


def assert_drawdown(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in {"REQUESTED", "DISBURSED", "RETURNED"}


def assert_fund_allocation(data: dict):
    """Append-only ledger artifact (PRD §2.4): only id + created_at; no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "FundAllocation must NOT expose a version field (PRD §2.4)"
    assert "updated_at" not in data, "FundAllocation must NOT expose updated_at (PRD §2.4)"


def assert_financial_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["period_label"], str) and len(data["period_label"]) > 0
    assert data["report_basis"] in {"INTERIM", "FINAL"}
    assert data["status"] in {"DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"}


def assert_progress_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["milestones_met"], int) and data["milestones_met"] >= 0
    assert isinstance(data["milestones_planned"], int) and data["milestones_planned"] >= 1
    assert data["status"] in {"SUBMITTED", "ACCEPTED", "RETURNED"}


def assert_single_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["fiscal_year"], int) and data["fiscal_year"] >= 2000
    assert isinstance(data["federal_expenditures_cents"], int) and data["federal_expenditures_cents"] >= 0
    assert isinstance(data["audit_required"], bool)
    assert data["status"] in {"OPEN", "SUBMITTED", "RESOLVED"}


def assert_audit_finding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("single_audit_id", ""))
    assert data["severity"] in {"DEFICIENCY", "SIGNIFICANT_DEFICIENCY", "MATERIAL_WEAKNESS"}
    assert isinstance(data["questioned_cost_cents"], int) and data["questioned_cost_cents"] >= 0
    assert data["status"] in {"OPEN", "RESOLVED"}
