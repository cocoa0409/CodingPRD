"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. RevenueEvent is append-only and must NOT
expose updated_at/version (PRD resource-identity section).
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Two renderings of the same logical-clock instant compare equal."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_channel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["handle"], str) and data["handle"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["home_platform"] in ("TWITCH", "YOUTUBE")
    assert data["payout_schedule"] in ("WEEKLY", "BIWEEKLY", "MONTHLY")
    assert isinstance(data["payout_threshold_cents"], int)
    assert data["monetization_posture"] in ("STANDARD", "RESTRICTED", "SUSPENDED")
    for field in ("balance_pending_cents", "balance_payable_cents",
                  "lifetime_paid_cents", "trust_score_bp",
                  "consistency_score_bps", "active_strike_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert 0 <= data["trust_score_bp"] <= 10000
    assert 0 <= data["consistency_score_bps"] <= 10000
    assert isinstance(data["projected_strike_weight"], (int, float))


def assert_tax_form(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert data["form_type"] in ("W9", "W8BEN", "W8BENE")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id_last4"], str) and len(data["tax_id_last4"]) == 4
    assert data["tax_status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")
    assert is_iso8601_timestamp(data["submitted_at"]), "submitted_at must be ISO 8601"


def assert_revenue_event(data: dict):
    """Append-only ledger entry: id + created_at, and no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entries expose no updated_at"
    assert "version" not in data, "append-only ledger entries expose no version"
    assert isinstance(data["channel_id"], str)
    assert data["kind"] in ("SUBSCRIPTION", "TIP", "AD_SHARE", "SPONSORSHIP", "CHARGEBACK")
    assert isinstance(data["gross_cents"], int)
    assert 0 <= data["platform_fee_bps"] <= 10000
    assert is_iso8601_timestamp(data["occurred_at"]), "occurred_at must be ISO 8601"
    assert data["recognition_status"] in ("PENDING", "CLEARED", "REVERSED")
    assert isinstance(data["settlement_month"], str) and len(data["settlement_month"]) == 7
    assert isinstance(data["net_cents"], int)
    assert isinstance(data["withholding_cents"], int)


def assert_payout(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert data["payout_status"] in ("SCHEDULED", "PROCESSING", "PAID", "FAILED",
                                     "HELD", "CANCELLED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["withholding_cents"], int)
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["net_transfer_cents"], int)
    assert isinstance(data["settled_event_count"], int)
    assert isinstance(data["retry_count"], int) and data["retry_count"] >= 0
    assert data["hold_reason"] in ("NONE", "TAX_FORM", "POSTURE")
    assert is_iso8601_timestamp(data["scheduled_for"]), "scheduled_for must be ISO 8601"


def assert_tier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert data["tier_code"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["monthly_price_cents"], int) and data["monthly_price_cents"] > 0
    assert 0 <= data["revenue_share_bps"] <= 10000
    assert isinstance(data["perk_inventory_total"], int)
    assert isinstance(data["perk_inventory_remaining"], int)
    assert data["tier_status"] in ("ACTIVE", "RETIRED")


def assert_viewer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert isinstance(data["handle"], str) and data["handle"]
    assert data["standing"] in ("GOOD_STANDING", "TIMED_OUT", "BANNED")
    assert isinstance(data["lifetime_spend_cents"], int)


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert isinstance(data["viewer_id"], str)
    assert isinstance(data["tier_id"], str)
    assert data["sub_status"] in ("ACTIVE", "PAST_DUE", "CANCELLED", "EXPIRED")
    assert is_iso8601_timestamp(data["started_at"]), "started_at must be ISO 8601"
    assert is_iso8601_timestamp(data["current_period_end"]), \
        "current_period_end must be ISO 8601"
    assert isinstance(data["cycles_paid"], int) and data["cycles_paid"] >= 1


def assert_perk_grant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["subscription_id"], str)
    assert data["perk_kind"] == "MERCH"
    assert data["perk_status"] in ("PENDING", "FULFILLED", "FAILED", "EXPIRED", "VOIDED")
    assert is_iso8601_timestamp(data["due_at"]), "due_at must be ISO 8601"
    assert isinstance(data["failure_count"], int) and data["failure_count"] >= 0


def assert_moderator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert isinstance(data["moderator_handle"], str) and data["moderator_handle"]
    assert isinstance(data["scopes"], list)
    for scope in data["scopes"]:
        assert scope in ("TIMEOUT", "BAN")
    assert data["moderator_status"] in ("INVITED", "ACTIVE", "SUSPENDED", "REMOVED")
    assert isinstance(data["actions_issued_count"], int) and data["actions_issued_count"] >= 0


def assert_moderation_action(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert isinstance(data["viewer_id"], str)
    assert data["action_kind"] in ("TIMEOUT", "BAN")
    assert isinstance(data["reason"], str)
    assert data["action_status"] in ("ACTIVE", "REVERSED", "EXPIRED")
    assert is_iso8601_timestamp(data["issued_at"]), "issued_at must be ISO 8601"


def assert_strike(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert data["policy_code"] in ("COPYRIGHT", "HATE_SPEECH", "NUDITY",
                                   "HARASSMENT", "SPAM")
    assert data["severity"] in ("MINOR", "MAJOR", "SEVERE")
    assert isinstance(data["evidence_ref"], str)
    assert data["strike_status"] in ("ISSUED", "UNDER_APPEAL", "UPHELD",
                                     "REVERSED", "EXPIRED")
    assert is_iso8601_timestamp(data["issued_at"]), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data["expires_at"]), "expires_at must be ISO 8601"
    assert is_iso8601_timestamp(data["appeal_deadline"]), "appeal_deadline must be ISO 8601"
    assert isinstance(data["appeal_round"], int) and 0 <= data["appeal_round"] <= 2
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]


def assert_deal(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert isinstance(data["sponsor_ref"], str) and data["sponsor_ref"]
    assert isinstance(data["title"], str)
    assert data["category"] in ("GAMING_HARDWARE", "ENERGY_DRINK", "VPN",
                                "GAME_PUBLISHER", "OTHER")
    assert isinstance(data["total_value_cents"], int)
    assert is_iso8601_timestamp(data["flight_start"]), "flight_start must be ISO 8601"
    assert is_iso8601_timestamp(data["flight_end"]), "flight_end must be ISO 8601"
    assert isinstance(data["required_deliverable_count"], int)
    assert data["deal_status"] in ("DRAFT", "PROPOSED", "ACCEPTED", "ACTIVE",
                                   "COMPLETED", "BREACHED", "CANCELLED")
    assert isinstance(data["miss_count"], int) and data["miss_count"] >= 0
    assert isinstance(data["verified_deliverable_count"], int)
    assert isinstance(data["disclosure_compliant"], bool)


def assert_deliverable(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["deal_id"], str)
    assert data["kind"] in ("AD_READ", "SPONSORED_SEGMENT", "LOGO_PLACEMENT",
                            "PRODUCT_PLACEMENT")
    assert is_iso8601_timestamp(data["due_at"]), "due_at must be ISO 8601"
    assert data["performance_status"] in ("SCHEDULED", "PERFORMED", "VERIFIED",
                                          "MISSED", "DISPUTED")
    assert data["disclosure_status"] in ("PENDING", "DISCLOSED_ON_TIME",
                                         "DISCLOSED_LATE", "MISSING")


def assert_stream(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert isinstance(data["title"], str)
    assert is_iso8601_timestamp(data["scheduled_start"]), "scheduled_start must be ISO 8601"
    assert is_iso8601_timestamp(data["scheduled_end"]), "scheduled_end must be ISO 8601"
    assert isinstance(data["simulcast"], bool)
    assert data["stream_status"] in ("SCHEDULED", "LIVE", "ENDED", "CANCELLED", "NO_SHOW")


def assert_simulcast_grant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["channel_id"], str)
    assert data["platform"] in ("TWITCH", "YOUTUBE", "KICK")
    assert is_iso8601_timestamp(data["window_start"]), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data["window_end"]), "window_end must be ISO 8601"
    assert isinstance(data["exclusive"], bool)
    assert data["grant_status"] in ("REQUESTED", "APPROVED", "DENIED", "REVOKED", "EXPIRED")


def assert_tier_perk_invariant(tier: dict, fulfilled_count: int):
    """The perk-inventory invariant from the PRD perks section:
    remaining + count(FULFILLED) == perk_inventory_total at all times."""
    assert tier["perk_inventory_remaining"] + fulfilled_count == tier["perk_inventory_total"], (
        f"Perk inventory invariant broken: {tier['perk_inventory_remaining']} + "
        f"{fulfilled_count} != {tier['perk_inventory_total']}"
    )


def assert_money_conservation(channel: dict, in_flight_amount_cents: int,
                              cleared_net_total_cents: int):
    """The pinned ledger identity from the PRD money section (no PAID payouts):
    payable + in-flight reserved amounts == cumulative cleared net."""
    assert channel["balance_payable_cents"] + in_flight_amount_cents == cleared_net_total_cents, (
        f"Ledger conservation broken: {channel['balance_payable_cents']} + "
        f"{in_flight_amount_cents} != {cleared_net_total_cents}"
    )
