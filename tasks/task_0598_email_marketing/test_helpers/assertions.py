"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountStatus,
    BillingCycleStatus,
    CampaignStatus,
    ConsentSource,
    ConsentState,
    DeliveryStatus,
    EngagementState,
    EngagementStatus,
    EnrollmentStatus,
    ImportJobStatus,
    JourneyStatus,
    PlanTier,
    SuppressionReason,
    TemplateStatus,
)

_COMMON_MUTABLE = ("id", "created_at", "updated_at", "version")


def _assert_common_mutable(data: dict, label: str):
    """PRD §2.4: every mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_account(data: dict):
    _assert_common_mutable(data, "Account")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["plan_tier"] in [t.value for t in PlanTier]
    assert data["status"] in [s.value for s in AccountStatus]
    assert isinstance(data["hourly_send_capacity"], int) and data["hourly_send_capacity"] >= 1
    assert isinstance(data["granted_send_credits"], int) and data["granted_send_credits"] >= 0
    assert isinstance(data["send_credit_balance"], int) and data["send_credit_balance"] >= 0
    assert isinstance(data["reserved_send_credits"], int)
    assert isinstance(data["consumed_send_credits"], int)
    assert isinstance(data["billable_contact_count"], int)
    assert 0 <= data["sender_reputation_score"] <= 100
    assert_account_invariants(data)


def assert_account_invariants(data: dict):
    """PRD §2.7 send-credit ledger + §2.10 suspension bookkeeping."""
    assert (
        data["granted_send_credits"]
        == data["send_credit_balance"] + data["reserved_send_credits"] + data["consumed_send_credits"]
    ), (
        "granted_send_credits must equal balance + reservations + consumption, got "
        f"{data['granted_send_credits']} != {data['send_credit_balance']} + "
        f"{data['reserved_send_credits']} + {data['consumed_send_credits']}"
    )
    if data["status"] == AccountStatus.ACTIVE.value:
        assert data["suspension_reason"] is None, "an ACTIVE account has a null suspension_reason"
    else:
        assert data["suspension_reason"] is not None, "a SUSPENDED account has a non-null suspension_reason"


def assert_account_user(data: dict):
    _assert_common_mutable(data, "AccountUser")
    assert is_valid_uuid(data["account_id"])
    assert "@" in data["email"]
    assert data["user_role"] in ("CAMPAIGN_AUTHOR", "COMPLIANCE_APPROVER", "DUAL")


def assert_audience(data: dict):
    _assert_common_mutable(data, "Audience")
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["double_optin_required"], bool)
    assert "@" in data["default_from_email"]
    assert isinstance(data["subscriber_count"], int) and data["subscriber_count"] >= 0


def assert_subscriber(data: dict):
    _assert_common_mutable(data, "Subscriber")
    assert is_valid_uuid(data["audience_id"])
    assert "@" in data["email"]
    assert data["consent_source"] in [s.value for s in ConsentSource]
    assert data["consent_state"] in [s.value for s in ConsentState]
    assert data["engagement_state"] in [s.value for s in EngagementState]
    assert isinstance(data["unsubscribe_token"], str) and len(data["unsubscribe_token"]) > 0
    assert 0 <= data["engagement_score"] <= 100
    assert 0 <= data["engagement_score_90d"] <= 100
    assert data["delivered_send_count"] >= 0
    assert data["opened_send_count"] >= 0
    assert data["clicked_send_count"] >= 0


def assert_import_job(data: dict):
    _assert_common_mutable(data, "ImportJob")
    assert is_valid_uuid(data["audience_id"])
    assert data["status"] in [s.value for s in ImportJobStatus]
    assert_import_row_conservation(data)


def assert_import_row_conservation(data: dict):
    """PRD §3.3: accepted + rejected + duplicate + suppressed == row_count, on every job."""
    total = (
        data["accepted_count"]
        + data["rejected_count"]
        + data["duplicate_count"]
        + data["suppressed_count"]
    )
    assert total == data["row_count"], (
        "import dispositions must reconcile against row_count: "
        f"{data['accepted_count']} + {data['rejected_count']} + {data['duplicate_count']} + "
        f"{data['suppressed_count']} != {data['row_count']}"
    )


def assert_segment(data: dict):
    _assert_common_mutable(data, "Segment")
    assert is_valid_uuid(data["audience_id"])
    assert isinstance(data["consent_states"], list) and len(data["consent_states"]) >= 1
    for state in data["consent_states"]:
        assert state in ("PENDING", "CONFIRMED", "UNSUBSCRIBED")
    assert 0 <= data["min_engagement_score"] <= 100
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0


def assert_template(data: dict):
    _assert_common_mutable(data, "Template")
    assert is_valid_uuid(data["account_id"])
    assert 1 <= len(data["subject"]) <= 200
    assert 1 <= len(data["html_body"]) <= 5000
    assert isinstance(data["has_unsubscribe_link"], bool)
    assert data["status"] in [s.value for s in TemplateStatus]
    assert data["has_unsubscribe_link"] == ("{{unsubscribe_url}}" in data["html_body"]), (
        "has_unsubscribe_link must be true exactly when the literal merge tag occurs in html_body"
    )


def assert_campaign(data: dict):
    _assert_common_mutable(data, "Campaign")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["audience_id"])
    assert is_valid_uuid(data["template_id"])
    assert is_valid_uuid(data["created_by_user_id"])
    assert data["status"] in [s.value for s in CampaignStatus]
    assert isinstance(data["ab_test_enabled"], bool)
    assert 1 <= data["variant_split_pct"] <= 99
    assert isinstance(data["recipient_snapshot_ids"], list)
    assert data["recipient_count"] == len(data["recipient_snapshot_ids"])
    assert data["reserved_credit_count"] >= 0
    assert data["send_charge_cents"] >= 0
    assert isinstance(data["send_charge_cents"], int), "money is expressed in whole cents as integers"
    assert data["winning_variant"] in (None, "A", "B")


def assert_send(data: dict):
    _assert_common_mutable(data, "Send")
    assert is_valid_uuid(data["subscriber_id"])
    assert data["delivery_status"] in [s.value for s in DeliveryStatus]
    assert data["engagement_status"] in [s.value for s in EngagementStatus]
    assert data["variant_label"] in (None, "A", "B")
    assert data["soft_bounce_count"] >= 0
    assert data["open_count"] >= 0
    assert data["click_count"] >= 0
    assert (data["campaign_id"] is None) != (data["journey_id"] is None), (
        "a Send carries either a campaign_id or a journey_id, never both and never neither"
    )


def assert_suppression_entry(data: dict):
    """PRD §2.4: suppression rows carry only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "SuppressionEntry.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "SuppressionEntry.created_at must be ISO 8601"
    assert "@" in data["email"]
    assert data["reason"] in [r.value for r in SuppressionReason]
    assert "version" not in data, "SuppressionEntry must expose no version"
    assert "updated_at" not in data, "SuppressionEntry must expose no updated_at"


def assert_journey(data: dict):
    _assert_common_mutable(data, "Journey")
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["audience_id"])
    assert data["status"] in [s.value for s in JourneyStatus]
    assert data["trigger_event"] in ("SUBSCRIBE_CONFIRMED", "CAMPAIGN_CLICK")
    assert isinstance(data["steps"], list) and 1 <= len(data["steps"]) <= 10
    assert data["active_enrollment_count"] >= 0
    assert data["entered_count"] >= data["active_enrollment_count"]


def assert_journey_enrollment(data: dict):
    _assert_common_mutable(data, "JourneyEnrollment")
    assert is_valid_uuid(data["journey_id"])
    assert is_valid_uuid(data["subscriber_id"])
    assert data["status"] in [s.value for s in EnrollmentStatus]
    assert data["current_step_index"] >= 0


def assert_billing_cycle(data: dict):
    _assert_common_mutable(data, "BillingCycle")
    assert is_valid_uuid(data["account_id"])
    assert data["status"] in [s.value for s in BillingCycleStatus]
    assert data["peak_contact_count"] >= 0
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["overage_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["base_fee_cents"] + data["overage_cents"], (
        "total_cents is base_fee_cents plus overage_cents"
    )
    if data["status"] == BillingCycleStatus.OPEN.value:
        assert data["tier_applied"] is None
        assert data["closed_at"] is None
        assert data["base_fee_cents"] == 0 and data["overage_cents"] == 0 and data["total_cents"] == 0
    else:
        assert data["tier_applied"] in [t.value for t in PlanTier]
        assert data["closed_at"] is not None


def assert_credit_conservation(account: dict, expected_granted: int):
    """PRD §2.7: granted == balance + reservations + consumption, at every observable instant."""
    assert account["granted_send_credits"] == expected_granted
    assert_account_invariants(account)
