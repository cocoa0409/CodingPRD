"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AlertSeverity,
    AlertType,
    CampaignStatus,
    Channel,
    EscalationState,
    ModerationState,
    NpsCategory,
    Posture,
    RequestStatus,
    ResponseState,
    ReviewResponseState,
    Sentiment,
    Site,
    SurveyStatus,
    SyncState,
    WidgetStatus,
)

MONEY_TOLERANCE = 0.001


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp produced by the server."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert a server timestamp names exactly the expected UTC instant."""
    assert is_iso8601_timestamp(actual), f"{label} must be an ISO 8601 timestamp, got {actual!r}"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def assert_score(actual, expected: float, label: str = "score"):
    """Assert a 2-decimal-place score/money value (PRD §2.7)."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r}"
    )
    assert abs(float(actual) - expected) < MONEY_TOLERANCE, (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_common_fields(data: dict, entity: str):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_append_only_fields(data: dict, entity: str):
    """Append-only snapshot: id + created_at ONLY, no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "version" not in data, f"{entity} is append-only and must expose no version field"
    assert "updated_at" not in data, f"{entity} is append-only and must expose no updated_at field"


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------
def assert_business(data: dict):
    assert_common_fields(data, "Business")
    assert isinstance(data["name"], str) and data["name"]
    assert data["plan_tier"] in ("BASIC", "PRO", "ENTERPRISE")
    assert isinstance(data["default_frequency_cap_days"], int)
    assert data["default_frequency_cap_days"] >= 1
    assert isinstance(data["location_count"], int) and data["location_count"] >= 0


def assert_location(data: dict):
    assert_common_fields(data, "Location")
    assert is_valid_uuid(data["business_id"])
    for field in ("name", "nap_name", "nap_address", "nap_phone"):
        assert isinstance(data[field], str) and data[field], f"Location.{field} must be a string"
    assert data["posture"] in [p.value for p in Posture]
    for field in (
        "review_count",
        "responded_review_count",
        "sentiment_positive_count",
        "sentiment_neutral_count",
        "sentiment_negative_count",
        "open_escalation_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"Location.{field} must be a non-negative integer"
        )
    for field in (
        "avg_rating",
        "reputation_score_provisional",
        "reputation_score_certified",
        "listing_health_score",
        "nps_score",
    ):
        assert isinstance(data[field], (int, float)) and not isinstance(data[field], bool), (
            f"Location.{field} must be a JSON number"
        )
    assert 0.0 <= float(data["listing_health_score"]) <= 100.0
    assert 0.0 <= float(data["reputation_score_provisional"]) <= 100.0


def assert_listing(data: dict):
    assert_common_fields(data, "Listing")
    assert is_valid_uuid(data["location_id"])
    assert data["site"] in [s.value for s in Site]
    assert isinstance(data["external_listing_id"], str)
    for field in ("listed_nap_name", "listed_nap_address", "listed_nap_phone"):
        assert isinstance(data[field], str), f"Listing.{field} must be a string"
    assert data["sync_state"] in [s.value for s in SyncState]
    assert isinstance(data["sync_failure_count"], int) and data["sync_failure_count"] >= 0
    assert isinstance(data["nap_match_count"], int)
    assert 0 <= data["nap_match_count"] <= 3, "Listing.nap_match_count ranges from 0 to 3"


def assert_contact(data: dict):
    assert_common_fields(data, "Contact")
    assert is_valid_uuid(data["business_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["sms_consent"], bool)
    assert isinstance(data["email_consent"], bool)
    assert isinstance(data["opted_out"], bool)
    assert isinstance(data["request_count"], int) and data["request_count"] >= 0


def assert_template(data: dict):
    assert_common_fields(data, "ResponseTemplate")
    assert is_valid_uuid(data["business_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["body"], str)
    assert 1 <= data["min_rating"] <= 5
    assert data["min_rating"] <= data["max_rating"] <= 5
    assert isinstance(data["requires_approval"], bool)


def assert_campaign(data: dict):
    assert_common_fields(data, "Campaign")
    assert is_valid_uuid(data["location_id"])
    assert data["channel"] in [c.value for c in Channel]
    assert data["status"] in [s.value for s in CampaignStatus]
    assert isinstance(data["daily_send_cap"], int) and data["daily_send_cap"] >= 1
    for field in ("credits_allocated", "credits_reserved", "credits_consumed", "credits_released"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"Campaign.{field} must be a non-negative integer"
        )
    assert isinstance(data["sent_count"], int) and data["sent_count"] >= 0
    assert isinstance(data["billing_cost"], (int, float))


def assert_review_request(data: dict):
    assert_common_fields(data, "ReviewRequest")
    assert is_valid_uuid(data["campaign_id"])
    assert is_valid_uuid(data["contact_id"])
    assert data["channel"] in [c.value for c in Channel]
    assert data["status"] in [s.value for s in RequestStatus]


def assert_review(data: dict):
    assert_common_fields(data, "Review")
    assert is_valid_uuid(data["location_id"])
    assert data["site"] in [s.value for s in Site]
    assert isinstance(data["external_review_id"], str)
    assert isinstance(data["author_name"], str)
    assert isinstance(data["text"], str)
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert data["sentiment"] in [s.value for s in Sentiment]
    assert data["moderation_state"] in [m.value for m in ModerationState]
    assert data["response_state"] in [r.value for r in ResponseState]


def assert_review_response(data: dict):
    assert_common_fields(data, "ReviewResponse")
    assert is_valid_uuid(data["review_id"])
    assert isinstance(data["body"], str) and data["body"]
    assert data["state"] in [s.value for s in ReviewResponseState]
    assert isinstance(data["drafted_by_user_id"], str) and data["drafted_by_user_id"]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_escalation(data: dict):
    assert_common_fields(data, "Escalation")
    assert is_valid_uuid(data["review_id"])
    assert data["reason"] == "NEGATIVE_SENTIMENT"
    assert data["state"] in [s.value for s in EscalationState]


def assert_survey(data: dict):
    assert_common_fields(data, "SurveyResponse")
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["contact_id"])
    assert data["status"] in [s.value for s in SurveyStatus]
    assert is_iso8601_timestamp(data["expires_at"]), "SurveyResponse.expires_at must be ISO 8601"
    if data["nps_category"] is not None:
        assert data["nps_category"] in [c.value for c in NpsCategory]


def assert_widget(data: dict):
    assert_common_fields(data, "Widget")
    assert is_valid_uuid(data["location_id"])
    assert data["status"] in [s.value for s in WidgetStatus]
    assert isinstance(data["embed_token"], str) and data["embed_token"]
    assert 1 <= data["min_rating"] <= 5
    assert 1 <= data["max_reviews"] <= 50


def assert_competitor(data: dict):
    assert_append_only_fields(data, "Competitor")
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["site"] in [s.value for s in Site]
    assert 1.00 <= float(data["avg_rating"]) <= 5.00
    assert isinstance(data["review_count"], int) and data["review_count"] >= 0


def assert_alert(data: dict):
    assert_append_only_fields(data, "Alert")
    assert is_valid_uuid(data["location_id"])
    assert data["alert_type"] in [a.value for a in AlertType]
    assert data["severity"] in [s.value for s in AlertSeverity]
    assert isinstance(data["message"], str)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
FIXED_ALERT_SEVERITY = {
    AlertType.NEGATIVE_REVIEW.value: AlertSeverity.WARNING.value,
    AlertType.LISTING_SYNC_FAILED.value: AlertSeverity.WARNING.value,
    AlertType.NPS_DETRACTOR.value: AlertSeverity.WARNING.value,
    AlertType.POSTURE_CHANGED.value: AlertSeverity.CRITICAL.value,
    AlertType.SEND_CAP_REACHED.value: AlertSeverity.INFO.value,
}


def assert_alert_severity(alert: dict):
    """Each alert_type has a fixed severity that never varies (PRD §2.10)."""
    expected = FIXED_ALERT_SEVERITY[alert["alert_type"]]
    assert alert["severity"] == expected, (
        f"Alert {alert['alert_type']} must carry severity {expected}, got {alert['severity']}"
    )


def assert_spendable_credits(campaign: dict, expected: int):
    """allocated - reserved - consumed is the conserved quantity (PRD §3.6)."""
    actual = (
        campaign["credits_allocated"]
        - campaign["credits_reserved"]
        - campaign["credits_consumed"]
    )
    assert actual == expected, (
        f"spendable credits: expected {expected}, got {actual} "
        f"(allocated={campaign['credits_allocated']}, reserved={campaign['credits_reserved']}, "
        f"consumed={campaign['credits_consumed']})"
    )


def assert_credit_ledger(campaign: dict, reserved: int, consumed: int, released: int):
    assert campaign["credits_reserved"] == reserved, (
        f"credits_reserved: expected {reserved}, got {campaign['credits_reserved']}"
    )
    assert campaign["credits_consumed"] == consumed, (
        f"credits_consumed: expected {consumed}, got {campaign['credits_consumed']}"
    )
    assert campaign["credits_released"] == released, (
        f"credits_released: expected {released}, got {campaign['credits_released']}"
    )
