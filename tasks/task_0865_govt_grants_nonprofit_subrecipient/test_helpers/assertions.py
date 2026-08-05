"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def _append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must NOT carry updated_at"
    assert "version" not in data, "append-only record must NOT carry version"


def assert_nonprofit(data: dict):
    _common(data)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["uei"], str)
    assert isinstance(data["cumulative_federal_expenditures_cents"], int)
    assert data["cumulative_federal_expenditures_cents"] >= 0
    assert data.get("latest_risk_tier") in (None, "LOW", "MODERATE", "HIGH")


def assert_nofo(data: dict):
    _common(data)
    assert isinstance(data["total_pool_cents"], int)
    assert isinstance(data["remaining_pool_cents"], int)
    assert isinstance(data["max_award_cents"], int)
    assert data["intake_status"] in ("OPEN", "CLOSED")


def assert_application(data: dict):
    _common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
        "SCORED", "AWARDED", "REJECTED",
    )
    assert data["indirect_method"] in ("DE_MINIMIS", "NEGOTIATED")
    assert isinstance(data["review_count"], int)


def assert_subaward(data: dict):
    _common(data)
    assert data["status"] in (
        "DRAFT", "ACTIVE", "SUSPENDED", "CLOSEOUT_PENDING", "CLOSED", "TERMINATED",
    )
    for f in ("total_budget_cents", "indirect_cost_cents", "federal_share_cents",
              "obligated_cents", "disbursed_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert_subaward_ledger_invariants(data)


def assert_subaward_ledger_invariants(data: dict):
    """Ledger figures never go negative and disbursed never exceeds obligated."""
    assert data["obligated_cents"] >= 0, "obligated_cents must be non-negative"
    assert data["disbursed_cents"] >= 0, "disbursed_cents must be non-negative"
    assert data["disbursed_cents"] <= data["obligated_cents"], (
        "disbursed_cents must not exceed obligated_cents"
    )


def assert_drawdown(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "RETURNED", "DENIED", "PAID")
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["reimbursable_cents"], int)


def assert_risk_assessment(data: dict):
    _common(data)
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 100
    assert data["risk_tier"] in ("LOW", "MODERATE", "HIGH")


def assert_monitoring_visit(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "CONDUCTED")


def assert_single_audit(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED")
    assert isinstance(data["audit_required"], bool)


def assert_finding(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "CAP_SUBMITTED", "CAP_ACCEPTED", "RESOLVED")
    assert data["source_kind"] in ("MONITORING", "SINGLE_AUDIT")
    assert data["severity"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")


def assert_performance_report(data: dict):
    _common(data)
    assert isinstance(data["on_track"], bool)


def assert_panel_review(data: dict):
    _append_only(data)
    assert isinstance(data["score"], int)


def assert_budget_line(data: dict):
    _append_only(data)
    assert isinstance(data["amount_cents"], int)
