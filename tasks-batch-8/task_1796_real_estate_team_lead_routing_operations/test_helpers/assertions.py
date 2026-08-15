"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

AGENT_STATUSES = ["ONBOARDING", "ACTIVE", "PAUSED", "OFFBOARDING", "OFFBOARDED"]
PERFORMANCE_TIERS = ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
POLICY_STATUSES = ["DRAFT", "ACTIVE", "SUPERSEDED"]
POLICY_MODES = ["ROUND_ROBIN", "PERFORMANCE_WEIGHTED"]
SOURCE_TYPES = ["PORTAL", "IDX_WEBSITE", "PAID_AD", "REFERRAL_PARTNER", "SPHERE", "SIGN_CALL"]
SOURCE_STATUSES = ["ACTIVE", "PAUSED"]
LEAD_STATUSES = ["NEW", "OFFERED", "CLAIMED", "WORKING", "UNDER_CONTRACT", "CLOSED_WON", "CLOSED_LOST"]
LEAD_TEMPERATURES = ["COLD", "WARM", "HOT"]
ASSIGNMENT_STATUSES = ["OFFERED", "CLAIMED", "EXPIRED", "RELEASED", "REASSIGNED"]
ASSIGNMENT_OUTCOME_REASONS = ["DEADLINE", "AUTO_PAUSE", "OFFBOARD", "MANUAL", "RELEASED"]
EVENT_TYPES = ["EMAIL_OPEN", "LINK_CLICK", "CALL_ANSWERED", "FORM_SUBMIT", "REPLIED", "SHOWING_ATTENDED"]
CAMPAIGN_STATUSES = ["DRAFT", "ACTIVE", "PAUSED"]
ENROLLMENT_STATUSES = ["ENROLLED", "PAUSED", "COMPLETED", "EXITED"]
ENROLLMENT_EXIT_REASONS = ["MANUAL", "TEMPERATURE_SHIFT", "CONVERTED"]
AGREEMENT_STATUSES = ["ACTIVE", "TERMINATED", "EXPIRED"]
DEAL_STATUSES = ["PENDING", "APPROVED", "DISPUTED", "PAID_OUT"]
SPLIT_BASIS_TYPES = ["ESTIMATED", "ACTUAL"]


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str):
    """Assert two ISO-8601 timestamps denote the same instant (PRD §2.5 format)."""
    assert is_iso8601_timestamp(actual), f"Not an ISO-8601 UTC timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def iso_plus_seconds(base_iso: str, seconds: int) -> str:
    """Return the canonical ISO-8601 instant `seconds` after base_iso."""
    from datetime import timedelta

    dt = _parse_instant(base_iso) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_team(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["market"], str)
    assert isinstance(data["timezone"], str)
    assert isinstance(data["speed_to_lead_window_seconds"], int)
    assert isinstance(data["claim_window_seconds"], int)


def assert_agent(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in AGENT_STATUSES
    assert data["performance_tier"] in PERFORMANCE_TIERS
    assert data["role_on_team"] in ["MEMBER", "LEADER"]
    assert isinstance(data["max_active_leads"], int) and data["max_active_leads"] >= 1
    assert isinstance(data["active_lead_count"], int) and data["active_lead_count"] >= 0
    assert isinstance(data["trailing_90d_conversions"], int)
    assert isinstance(data["trailing_90d_claimed"], int)
    assert isinstance(data["trailing_90d_offered"], int)
    assert isinstance(data["consecutive_missed_claims"], int)
    assert data.get("avg_first_response_seconds") is None or isinstance(
        data["avg_first_response_seconds"], int
    )


def assert_routing_policy(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in POLICY_STATUSES
    assert data["mode"] in POLICY_MODES
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1


def assert_lead_source(data: dict):
    _assert_common_mutable(data)
    assert data["type"] in SOURCE_TYPES
    assert data["status"] in SOURCE_STATUSES
    assert isinstance(data["cost_per_lead_cents"], int) and data["cost_per_lead_cents"] >= 0
    assert isinstance(data["monthly_budget_cents"], int) and data["monthly_budget_cents"] >= 0
    assert isinstance(data["leads_this_month_count"], int)
    assert isinstance(data["spent_this_month_cents"], int)


def assert_lead(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in LEAD_STATUSES
    assert data["temperature"] in LEAD_TEMPERATURES
    assert isinstance(data["engagement_score"], int)
    assert isinstance(data["expected_close_price_cents"], int)
    assert data["expected_close_price_cents"] > 0
    assert data.get("within_speed_sla") is None or isinstance(data["within_speed_sla"], bool)


def assert_assignment(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ASSIGNMENT_STATUSES
    assert data["policy_mode_snapshot"] in POLICY_MODES
    assert isinstance(data["rotation_seq"], int)
    assert data.get("outcome_reason") is None or data["outcome_reason"] in ASSIGNMENT_OUTCOME_REASONS


def assert_engagement_event(data: dict):
    """Append-only log row: id + created_at only — NO updated_at, NO version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only event must not carry updated_at"
    assert "version" not in data, "append-only event must not carry version"
    assert data["type"] in EVENT_TYPES
    assert isinstance(data["points"], int)
    assert isinstance(data["effective_points"], int)


def assert_nurture_campaign(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in CAMPAIGN_STATUSES
    assert data["temperature_target"] in LEAD_TEMPERATURES
    assert isinstance(data["steps"], list) and len(data["steps"]) >= 1


def assert_nurture_enrollment(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ENROLLMENT_STATUSES
    assert data["entered_temperature"] in LEAD_TEMPERATURES
    assert isinstance(data["current_step_index"], int)
    assert data.get("exit_reason") is None or data["exit_reason"] in ENROLLMENT_EXIT_REASONS


def assert_referral_partner(data: dict):
    _assert_common_mutable(data)
    assert data["status"] == "ACTIVE"
    assert isinstance(data["fee_bps"], int) and 0 <= data["fee_bps"] <= 5000


def assert_split_agreement(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in AGREEMENT_STATUSES
    assert data["a_share_bps"] + data["b_share_bps"] == 10000


def assert_deal(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in DEAL_STATUSES
    assert data["split_basis_type"] in SPLIT_BASIS_TYPES
    assert isinstance(data["split_basis_cents"], int)
    assert isinstance(data["referral_fee_cents"], int)
    assert isinstance(data["house_share_cents"], int)
    assert isinstance(data["agent_pool_cents"], int)
    assert isinstance(data["agent_shares"], list) and len(data["agent_shares"]) >= 1
    for share in data["agent_shares"]:
        assert is_valid_uuid(share["agent_id"])
        assert isinstance(share["amount_cents"], int)


def assert_waterfall_conservation(deal: dict):
    """Money conservation: fee + house + sum(shares) == basis exactly (PRD §3.6)."""
    total = (
        deal["referral_fee_cents"]
        + deal["house_share_cents"]
        + sum(s["amount_cents"] for s in deal["agent_shares"])
    )
    assert total == deal["split_basis_cents"], (
        f"Waterfall does not conserve cents: {deal['referral_fee_cents']} + "
        f"{deal['house_share_cents']} + shares != {deal['split_basis_cents']}"
    )
