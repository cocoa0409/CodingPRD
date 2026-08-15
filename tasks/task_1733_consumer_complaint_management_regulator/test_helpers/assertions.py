"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ProductPosture, ComplaintStatus, ReferralStatus, ReferralTimeliness,
    RcaStatus, RcaVerdict, RemediationDecisionType, RemediationDecisionStatus,
    TemplateStatus, QualityReviewStatus, QualityReviewOutcome, EscalationTier,
    EscalationStatus, IntakeEventType,
)


def parse_instant(value) -> datetime:
    """Parse an ISO-8601 timestamp (with or without fractional digits) to a datetime."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assert_instant_equals(actual, expected_iso, context="timestamp"):
    """Compare two timestamps by instant, tolerating surface format variants."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{context}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1"
    )


def _assert_append_only_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{label} is append-only and must not carry updated_at"
    assert "version" not in data, f"{label} is append-only and must not carry version"


def assert_product(data: dict):
    _assert_common_fields(data, "Product")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["posture"] in [p.value for p in ProductPosture]
    assert isinstance(data["open_complaint_count"], int)
    assert isinstance(data["substantiated_count_90d"], int)
    assert isinstance(data["early_warning_active"], bool)


def assert_channel(data: dict):
    _assert_common_fields(data, "Channel")
    assert isinstance(data["channel_code"], str) and data["channel_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["is_regulator_portal"], bool)


def assert_taxonomy_category(data: dict):
    _assert_common_fields(data, "TaxonomyCategory")
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert data.get("parent_category_code") is None or isinstance(
        data["parent_category_code"], str
    )
    assert isinstance(data["retired"], bool)


def assert_response_template(data: dict):
    _assert_common_fields(data, "ResponseTemplate")
    assert isinstance(data["template_key"], str) and data["template_key"]
    assert isinstance(data["channel_code"], str) and data["channel_code"]
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert isinstance(data["body"], str)
    assert data["status"] in [s.value for s in TemplateStatus]


def assert_complaint(data: dict):
    _assert_common_fields(data, "Complaint")
    assert isinstance(data["complainant_ref"], str) and data["complainant_ref"]
    assert isinstance(data["channel_code"], str) and data["channel_code"]
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["category_code"], str) and data["category_code"]
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert isinstance(data["narrative"], str)
    assert isinstance(data["claimed_loss_cents"], int)
    assert data["claimed_loss_cents"] >= 0
    assert data["status"] in [s.value for s in ComplaintStatus]
    assert data.get("response_text") is None or isinstance(data["response_text"], str)
    assert data.get("response_template_key") is None or isinstance(
        data["response_template_key"], str
    )
    assert data.get("resolved_at") is None or is_iso8601_timestamp(data["resolved_at"])
    assert isinstance(data["approved_restitution_cents"], int)
    assert isinstance(data["paid_restitution_cents"], int)
    assert isinstance(data["days_open_business"], int)
    assert isinstance(data["days_open_calendar"], int)
    assert data.get("timeliness_score") is None or isinstance(
        data["timeliness_score"], (int, float)
    )
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    assert data.get("retention_purge_at") is None or is_iso8601_timestamp(
        data["retention_purge_at"]
    )


def assert_intake_event(data: dict):
    _assert_append_only_fields(data, "IntakeEvent")
    assert is_valid_uuid(data.get("complaint_id", ""))
    assert data["event_type"] in [e.value for e in IntakeEventType]
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert is_iso8601_timestamp(data.get("event_at", ""))


def assert_regulatory_referral(data: dict):
    _assert_common_fields(data, "RegulatoryReferral")
    assert is_valid_uuid(data.get("complaint_id", ""))
    assert isinstance(data["portal_ref"], str) and data["portal_ref"]
    assert is_iso8601_timestamp(data.get("received_via_portal_at", ""))
    assert is_iso8601_timestamp(data.get("response_due_at", ""))
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])
    assert data["timeliness"] in [t.value for t in ReferralTimeliness]
    assert data["status"] in [s.value for s in ReferralStatus]
    assert data.get("response_text") is None or isinstance(data["response_text"], str)


def assert_rca(data: dict):
    _assert_common_fields(data, "RootCauseAnalysis")
    assert is_valid_uuid(data.get("complaint_id", ""))
    assert data["verdict"] in [v.value for v in RcaVerdict]
    assert isinstance(data["linked_product_code"], str) and data["linked_product_code"]
    assert isinstance(data["process_step"], str) and data["process_step"]
    assert data.get("completed_at") is None or is_iso8601_timestamp(data["completed_at"])
    assert data["status"] in [s.value for s in RcaStatus]


def assert_remediation_decision(data: dict):
    _assert_common_fields(data, "RemediationDecision")
    assert is_valid_uuid(data.get("complaint_id", ""))
    assert data["decision_type"] in [t.value for t in RemediationDecisionType]
    assert isinstance(data["line_items"], list)
    for item in data["line_items"]:
        assert isinstance(item.get("label"), str)
        assert isinstance(item.get("amount_cents"), int) and item["amount_cents"] >= 0
    assert isinstance(data["restitution_amount_cents"], int)
    assert data["restitution_amount_cents"] >= 0
    assert isinstance(data["drafted_by_user_id"], str) and data["drafted_by_user_id"]
    assert data.get("approved_by_user_id") is None or isinstance(
        data["approved_by_user_id"], str
    )
    assert data["status"] in [s.value for s in RemediationDecisionStatus]


def assert_quality_review(data: dict):
    _assert_common_fields(data, "QualityReview")
    assert is_valid_uuid(data.get("complaint_id", ""))
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]
    assert is_iso8601_timestamp(data.get("window_start_at", ""))
    assert is_iso8601_timestamp(data.get("window_end_at", ""))
    assert parse_instant(data["window_end_at"]) > parse_instant(data["window_start_at"])
    assert data.get("outcome") is None or data["outcome"] in [
        o.value for o in QualityReviewOutcome
    ]
    assert data["status"] in [s.value for s in QualityReviewStatus]


def assert_escalation(data: dict):
    _assert_common_fields(data, "EscalationCase")
    assert is_valid_uuid(data.get("complaint_id", ""))
    assert data["escalation_tier"] in [t.value for t in EscalationTier]
    assert isinstance(data["reason"], str)
    assert isinstance(data["raised_by_user_id"], str) and data["raised_by_user_id"]
    assert data["status"] in [s.value for s in EscalationStatus]


def assert_trend_snapshot(data: dict):
    _assert_append_only_fields(data, "TrendSnapshot")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert is_iso8601_timestamp(data.get("period_start_at", ""))
    assert is_iso8601_timestamp(data.get("period_end_at", ""))
    assert parse_instant(data["period_end_at"]) >= parse_instant(data["period_start_at"])
    assert isinstance(data["complaint_count"], int) and data["complaint_count"] >= 0
    assert isinstance(data["substantiated_count"], int)
    assert 0 <= data["substantiated_count"] <= data["complaint_count"]
    assert isinstance(data["substantiation_rate_bps"], int)
    assert 0 <= data["substantiation_rate_bps"] <= 10000
    assert isinstance(data["early_warning"], bool)
    assert is_iso8601_timestamp(data.get("evaluated_at", ""))


def assert_restitution_ledger_invariants(complaint: dict):
    """Restitution ledger invariants on a complaint read (PRD §3.6)."""
    assert complaint["approved_restitution_cents"] >= 0
    assert complaint["paid_restitution_cents"] >= 0
    assert complaint["paid_restitution_cents"] <= complaint["approved_restitution_cents"]


def assert_event_order(events: list, expected_types: list):
    """Assert the audit stream contains the given event types as an ordered subsequence."""
    actual = [e["event_type"] for e in events]
    pos = 0
    for wanted in expected_types:
        while pos < len(actual) and actual[pos] != wanted:
            pos += 1
        assert pos < len(actual), (
            f"Expected event {wanted} after position {pos} in stream {actual}"
        )
        pos += 1
