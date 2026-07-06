"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_budget_cycle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["phase"] in [
        "DRAFT", "SUBMISSION", "DEVELOPMENT", "VOTING",
        "SELECTION", "IMPLEMENTATION", "CLOSED",
    ]
    assert data["voting_method"] in ["RANKED", "ALLOCATION"]
    assert isinstance(data["total_budget_cents"], int)
    assert isinstance(data["total_committed_cents"], int)
    assert isinstance(data["uncommitted_cents"], int)
    assert isinstance(data["completed_project_count"], int)
    assert "version" in data


def assert_category(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["category_budget_cap_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["remaining_cap_cents"], int)


def assert_resident(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["eligibility_status"] in [
        "UNVERIFIED", "PENDING_VERIFICATION", "VERIFIED", "REJECTED",
    ]
    assert isinstance(data["age"], int)


def assert_proposal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "DEVELOPING", "REJECTED", "COSTED", "ON_BALLOT",
        "SELECTED", "NOT_SELECTED", "IN_IMPLEMENTATION", "COMPLETED", "CANCELLED",
    ]
    assert isinstance(data["provisional_estimate_cents"], int)
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["vote_score"], int)
    assert isinstance(data["awarded_cents"], int)


def assert_cost_line_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["line_provisional_cents"], int)


def assert_ballot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["DRAFT", "CAST", "WITHDRAWN"]
    assert data["method"] in ["RANKED", "ALLOCATION"]
    assert isinstance(data["total_allocated_cents"], int)


def assert_selection_run(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["selected_count"], int)
    assert isinstance(data["total_awarded_cents"], int)
    assert isinstance(data["is_current"], bool)


def assert_milestone(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PLANNED", "IN_PROGRESS", "BLOCKED", "COMPLETED"]


def assert_report_back(data: dict):
    """ReportBack is append-only: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_ledger_conserved(cycle: dict):
    """Budget conservation invariant (PRD §2.6)."""
    assert cycle["uncommitted_cents"] == cycle["total_budget_cents"] - cycle["total_committed_cents"], (
        "uncommitted_cents must equal total_budget_cents - total_committed_cents"
    )
