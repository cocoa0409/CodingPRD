"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict):
    """Common resource properties of PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_auditable_entity(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("business_owner"), str) and len(data["business_owner"]) > 0
    assert isinstance(data.get("regulatory_scrutiny"), bool)
    assert data.get("status") in ("ACTIVE", "RETIRED")
    if data.get("status") == "ACTIVE":
        assert data.get("retired_at") is None
    else:
        assert is_iso8601_timestamp(data.get("retired_at", ""))
    if data.get("current_inherent_risk_score") is not None:
        assert isinstance(data["current_inherent_risk_score"], int)
        assert 20 <= data["current_inherent_risk_score"] <= 100
        assert data.get("current_risk_tier") in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    else:
        assert data.get("current_risk_tier") is None


def assert_risk_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("auditable_entity_id", ""))
    assert isinstance(data.get("fiscal_year"), int)
    assert isinstance(data.get("likelihood"), int) and 1 <= data["likelihood"] <= 5
    assert isinstance(data.get("impact"), int) and 1 <= data["impact"] <= 5
    assert data.get("scoring_variant") in ("WEIGHTED", "CONSERVATIVE")
    assert isinstance(data.get("inherent_risk_score"), int)
    assert 20 <= data["inherent_risk_score"] <= 100
    assert data.get("status") in ("DRAFT", "FINALIZED")
    if data.get("status") == "FINALIZED":
        assert is_iso8601_timestamp(data.get("finalized_at", ""))


def assert_rating_criteria_config(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("critical_min"), int)
    assert isinstance(data.get("high_min"), int)
    assert isinstance(data.get("moderate_min"), int)
    assert 1 <= data["moderate_min"] < data["high_min"] < data["critical_min"] <= 25
    assert data.get("status") in ("DRAFT", "ACTIVE", "SUPERSEDED")
    if data.get("status") == "ACTIVE":
        assert is_iso8601_timestamp(data.get("activated_at", ""))


def assert_audit_plan(data: dict):
    _assert_common(data)
    assert isinstance(data.get("fiscal_year"), int)
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("status") in ("DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "CLOSED")
    assert isinstance(data.get("engagement_count"), int) and data["engagement_count"] >= 0
    assert isinstance(data.get("high_risk_coverage_pct"), (int, float))
    assert_cost_precision(float(data["high_risk_coverage_pct"]))


def assert_engagement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("audit_plan_id", ""))
    assert is_valid_uuid(data.get("auditable_entity_id", ""))
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("status") in (
        "PLANNED", "SCOPED", "FIELDWORK", "REPORTING", "CLOSED", "CANCELLED"
    )
    assert data.get("budget_hours", 0) > 0
    assert isinstance(data.get("reserved_hours"), (int, float)) and data["reserved_hours"] >= 0
    assert isinstance(data.get("actual_hours"), (int, float)) and data["actual_hours"] >= 0
    assert isinstance(data.get("provisional_hours"), (int, float)) and data["provisional_hours"] >= 0
    assert isinstance(data.get("signed_off_workpaper_count"), int)
    assert isinstance(data.get("open_finding_count"), int)
    assert isinstance(data.get("qa_regression_count"), int)


def assert_auditor(data: dict):
    _assert_common(data)
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert data.get("grade") in ("STAFF", "SENIOR", "MANAGER", "DIRECTOR")
    assert data.get("status") in ("ACTIVE", "INACTIVE")


def assert_engagement_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert is_valid_uuid(data.get("auditor_id", ""))
    assert data.get("role_in_engagement") in ("LEAD", "STAFF", "REVIEWER")
    assert data.get("allocated_hours", 0) > 0
    assert data.get("status") in ("ACTIVE", "CANCELLED")


def assert_workpaper(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert isinstance(data.get("reference"), str) and len(data["reference"]) > 0
    assert is_valid_uuid(data.get("preparer_auditor_id", ""))
    assert data.get("hours_worked", 0) > 0
    assert data.get("status") in ("DRAFT", "SUBMITTED", "SIGNED_OFF", "RETURNED")
    assert isinstance(data.get("locked"), bool)
    if data.get("status") == "SIGNED_OFF":
        assert is_iso8601_timestamp(data.get("signed_off_at", ""))
        assert data.get("reviewer_auditor_id") is not None


def assert_finding(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert is_valid_uuid(data.get("rating_criteria_config_id", ""))
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert isinstance(data.get("likelihood"), int) and 1 <= data["likelihood"] <= 5
    assert isinstance(data.get("impact"), int) and 1 <= data["impact"] <= 5
    assert isinstance(data.get("composite_score"), int)
    assert data["composite_score"] == data["likelihood"] * data["impact"]
    assert data.get("severity") in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert data.get("status") in (
        "DRAFT", "PENDING_RESPONSE", "UNDER_REVIEW", "AGREED",
        "REBUTTED", "ESCALATED", "FINAL",
    )
    assert isinstance(data.get("negotiation_rounds"), int) and data["negotiation_rounds"] >= 0
    assert isinstance(data.get("open_overdue_action_count"), int)
    assert data["open_overdue_action_count"] >= 0


def assert_management_response(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("finding_id", ""))
    assert isinstance(data.get("response_text"), str) and len(data["response_text"]) > 0
    assert isinstance(data.get("responder_user_id"), str)
    assert data.get("status") in ("SUBMITTED", "ACCEPTED", "REBUTTED")


def assert_action_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("finding_id", ""))
    assert isinstance(data.get("description"), str) and len(data["description"]) > 0
    assert isinstance(data.get("owner_name"), str) and len(data["owner_name"]) > 0
    assert is_iso8601_timestamp(data.get("original_due_date", ""))
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert isinstance(data.get("extension_count"), int) and data["extension_count"] >= 0
    assert isinstance(data.get("cumulative_extended_days"), int)
    assert data["cumulative_extended_days"] >= 0
    assert data.get("status") in (
        "OPEN", "IN_PROGRESS", "SUBMITTED_FOR_VALIDATION", "VALIDATED"
    )
    if data.get("status") == "VALIDATED":
        assert data.get("validated_by_user_id") is not None
        assert is_iso8601_timestamp(data.get("validated_at", ""))


def assert_extension_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("action_plan_id", ""))
    assert is_iso8601_timestamp(data.get("requested_due_date", ""))
    assert isinstance(data.get("reason"), str) and len(data["reason"]) > 0
    assert data.get("status") in ("PENDING", "APPROVED", "DENIED")
    if data.get("status") == "APPROVED":
        assert isinstance(data.get("approved_days"), int) and data["approved_days"] >= 1
        assert data.get("decided_by_user_id") is not None


def assert_audit_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("status") in (
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "ISSUED", "DISTRIBUTED"
    )
    if data.get("status") in ("ISSUED", "DISTRIBUTED"):
        assert is_iso8601_timestamp(data.get("issued_at", ""))
    if data.get("status") == "DISTRIBUTED":
        assert is_iso8601_timestamp(data.get("distributed_at", ""))
        assert isinstance(data.get("distribution_list"), list) and len(data["distribution_list"]) > 0


def assert_qa_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert data.get("scope") in ("INTERNAL", "EXTERNAL")
    assert data.get("status") in ("SCHEDULED", "IN_PROGRESS", "COMPLETED")
    if data.get("status") == "COMPLETED":
        for dim in (
            "doc_quality_score", "fieldwork_quality_score",
            "reporting_quality_score", "independence_score",
        ):
            assert isinstance(data.get(dim), int) and 1 <= data[dim] <= 5
        assert isinstance(data.get("overall_score"), (int, float))
        assert_cost_precision(float(data["overall_score"]))
        assert data.get("rating") in ("PASS", "PASS_WITH_DEFICIENCIES", "FAIL")
        assert is_iso8601_timestamp(data.get("completed_at", ""))


def assert_committee_pack(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("audit_plan_id", ""))
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("status") in ("DRAFT", "FINALIZED", "PRESENTED")
    assert isinstance(data.get("is_stale_snapshot"), bool)
    if data.get("status") in ("FINALIZED", "PRESENTED"):
        assert isinstance(data.get("snapshot_plan_completion_pct"), (int, float))
        assert_cost_precision(float(data["snapshot_plan_completion_pct"]))
        assert isinstance(data.get("snapshot_overdue_action_count"), int)
        assert isinstance(data.get("snapshot_critical_findings"), int)
        assert isinstance(data.get("snapshot_high_findings"), int)
        assert is_iso8601_timestamp(data.get("finalized_at", ""))
    if data.get("status") == "PRESENTED":
        assert is_iso8601_timestamp(data.get("presented_at", ""))
