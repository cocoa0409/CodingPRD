"""Entity assertions and domain invariant checkers.

Each assert_* validates the fields the PRD guarantees on a resource: the
common system-managed properties of section 2.4 (id, created_at, updated_at,
version) plus the entity's own declared fields.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_agency(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["fee_cap_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_agent(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["cert_number"], str)
    assert data["cert_status"] in ("PENDING", "CERTIFIED", "SUSPENDED", "REVOKED")
    assert isinstance(data["is_manager"], bool)


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["primary_agent_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["position"], str) and len(data["position"]) > 0
    assert data["status"] in ("ACTIVE", "TRANSITIONING", "RELEASED")


def assert_team(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["league_code"], str) and len(data["league_code"]) > 0


def assert_cap_season(data: dict):
    _assert_common(data)
    assert isinstance(data["team_id"], str)
    assert isinstance(data["season_year"], int)
    assert isinstance(data["cap_limit_cents"], int)
    assert isinstance(data["luxury_threshold_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["reserved_cents"], int)
    assert data["status"] in ("OPEN", "LOCKED", "CLOSED")


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["team_id"], str)
    assert isinstance(data["cap_season_id"], str)
    assert isinstance(data["start_season_year"], int)
    assert isinstance(data["years"], int) and 1 <= data["years"] <= 5
    assert isinstance(data["base_salary_cents"], int)
    assert isinstance(data["guaranteed_cents"], int)
    assert isinstance(data["signing_bonus_cents"], int)
    assert isinstance(data["incentive_cents"], int)
    assert isinstance(data["escalator_pct"], (int, float))
    assert isinstance(data["aav_cents"], int)
    assert isinstance(data["total_value_cents"], int)
    assert data["signing_status"] in ("NEGOTIATING", "SIGNED", "VOIDED")
    assert data["cap_posting_status"] in ("UNPOSTED", "POSTED", "REVERSED")


def assert_proposal(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["proposed_by_agent_id"], str)
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert isinstance(data["proposed_aav_cents"], int)
    assert isinstance(data["proposed_guaranteed_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "COUNTERED", "ACCEPTED",
                              "REJECTED", "WITHDRAWN")


def assert_endorsement_deal(data: dict):
    _assert_common(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["brand_name"], str) and len(data["brand_name"]) > 0
    assert isinstance(data["deal_value_cents"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("PENDING_APPROVAL", "ACTIVE", "COMPLETED",
                              "TERMINATED")


def assert_tender_option(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert data["kind"] in ("QUALIFYING_OFFER", "TEAM_OPTION", "PLAYER_OPTION")
    assert isinstance(data["window_open_at"], str)
    assert isinstance(data["window_close_at"], str)
    assert data["status"] in ("PENDING", "EXERCISED", "EXPIRED")


def assert_grievance(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["filed_by_agent_id"], str)
    assert data["category"] in ("NON_PAYMENT", "ROSTER_MOVE", "BONUS_DISPUTE",
                                "MEDICAL")
    assert isinstance(data["description"], str)
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "ARBITRATION",
                              "RESOLVED", "WITHDRAWN")


def assert_fee_ledger_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_id"], str)
    assert isinstance(data["agent_id"], str)
    assert isinstance(data["split_pct"], (int, float))
    assert isinstance(data["amount_cents"], int)
    assert data["kind"] in ("PLAYING_CONTRACT", "ENDORSEMENT",
                            "TRANSITION_ADJUSTMENT")
    assert data["status"] in ("ACCRUED", "PAID", "VOIDED")


def assert_cap_season_counters_consistent(data: dict):
    """Cap-season counter invariants that must hold after any operation."""
    assert data["committed_cents"] >= 0, "committed_cents never goes negative"
    assert data["reserved_cents"] >= 0, "reserved_cents never goes negative"
