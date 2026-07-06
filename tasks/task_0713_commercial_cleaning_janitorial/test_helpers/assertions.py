"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response structure against the PRD contract.
common_fields entities carry id/created_at/updated_at/version; Crew and CrewShift
carry only id/created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_id_created_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["industry"] in ["OFFICE", "MEDICAL", "INDUSTRIAL", "RETAIL", "EDUCATION"]
    assert data["lifecycle_stage"] in ["PROSPECT", "ACTIVE_CUSTOMER", "CHURNED"]
    assert isinstance(data["health_score"], int)
    assert 0 <= data["health_score"] <= 100, "health_score bounded 0..100"


def assert_rfp(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["title"], str)
    assert data["estimated_total_sqft"] > 0
    assert data["status"] in [
        "OPEN", "WALKTHROUGH_SCHEDULED", "BIDDING", "PROPOSED", "WON", "LOST"
    ]


def assert_site_contact(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["full_name"], str)
    assert is_iso8601_timestamp(data["avail_start_at"])
    assert is_iso8601_timestamp(data["avail_end_at"])


def assert_walkthrough(data: dict):
    _assert_common(data)
    assert isinstance(data["rfp_id"], str)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"]


def assert_service_area(data: dict):
    _assert_common(data)
    assert isinstance(data["rfp_id"], str)
    assert data["sqft"] > 0
    assert data["soil_level"] in ["LIGHT", "MEDIUM", "HEAVY"]
    assert 1 <= data["frequency_per_week"] <= 7
    assert isinstance(data["weekly_hours"], (int, float))


def assert_bid_estimate(data: dict):
    _assert_common(data)
    assert isinstance(data["rfp_id"], str)
    assert data["base_wage_cents"] > 0
    assert data["loading_method"] in ["ESTIMATE", "LOADED"]
    assert data["status"] in ["DRAFT", "PRICED"]


def assert_proposal(data: dict):
    _assert_common(data)
    assert isinstance(data["rfp_id"], str)
    assert isinstance(data["bid_estimate_id"], str)
    assert isinstance(data["revision_round"], int)
    assert data["status"] in ["DRAFT", "SENT", "ACCEPTED", "DECLINED"]


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["proposal_id"], str)
    assert data["lifecycle_status"] in ["DRAFT", "SIGNED", "STARTUP", "SERVICING", "ENDED"]
    assert data["billing_status"] in ["PENDING", "ACTIVE", "SUSPENDED", "CLOSED"]


def assert_startup_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["allocated_hours"], (int, float))
    assert data["status"] in ["PLANNING", "CREWED", "READY", "LIVE", "ABORTED"]


def assert_crew(data: dict):
    _assert_id_created_only(data)
    assert isinstance(data["name"], str)
    assert data["weekly_capacity_hours"] > 0
    assert data["status"] in ["AVAILABLE", "RETIRED"]


def assert_crew_shift(data: dict):
    _assert_id_created_only(data)
    assert isinstance(data["startup_plan_id"], str)
    assert isinstance(data["crew_id"], str)
    assert isinstance(data["shift_hours"], (int, float))
    assert data["status"] in ["ASSIGNED", "CANCELLED"]


def assert_supply_budget(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert data["total_cents"] > 0


def assert_supply_requisition(data: dict):
    _assert_common(data)
    assert isinstance(data["supply_budget_id"], str)
    assert data["amount_cents"] > 0
    assert data["status"] in ["REQUESTED", "APPROVED", "CANCELLED"]


def assert_renewal_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert data["escalation_method"] in ["CPI", "FLAT"]
    assert data["status"] in ["DRAFT", "OFFERED", "RENEWED", "LAPSED"]


def assert_budget_conservation(budget: dict):
    """PRD §3.9 invariant: committed_cents + remaining_cents == total_cents."""
    assert budget["committed_cents"] + budget["remaining_cents"] == budget["total_cents"], (
        f"budget conservation violated: committed={budget['committed_cents']} + "
        f"remaining={budget['remaining_cents']} != total={budget['total_cents']}"
    )
