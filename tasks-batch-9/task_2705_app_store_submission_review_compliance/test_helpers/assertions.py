"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppealState,
    CommerceItemStatus,
    CompliancePosture,
    CredentialStatus,
    DistributionState,
    ExpediteState,
    FindingStatus,
    GuidelineStatus,
    ImpactStatus,
    ListingState,
    ProgramStatus,
    RolloutState,
    SelfReviewStatus,
    SubmissionState,
    WindowStatus,
)


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict):
    """Every resource type carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 when the row is created"


def assert_publisher_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert "@" in data["contact_email"], "contact_email must contain an @ character"
    assert data["program_status"] in _values(ProgramStatus)
    assert data["commerce_program_tier"] in ("SMALL_BUSINESS", "STANDARD")
    assert is_iso8601_timestamp(data["membership_paid_through_at"])
    assert isinstance(data["standing_score_rolling_365"], (int, float))
    assert isinstance(data["standing_score_lifetime"], (int, float))
    assert 0.0 <= data["standing_score_rolling_365"] <= 100.0
    assert 0.0 <= data["standing_score_lifetime"] <= 100.0
    assert isinstance(data["expedite_credits_remaining"], int)
    assert isinstance(data["rejection_strike_count"], int)
    assert isinstance(data["settlement_finalized_periods"], list)


def assert_signing_credential(data: dict):
    assert_common_fields(data)
    assert data["credential_type"] in ("DISTRIBUTION_CERT", "PROVISIONING_PROFILE")
    assert data["platform"] in ("IOS", "ANDROID")
    assert data["key_custody"] in ("HSM", "CLOUD_MANAGED", "LOCAL_KEYCHAIN")
    assert data["status"] in _values(CredentialStatus)
    assert isinstance(data["entitlements"], list)
    assert is_iso8601_timestamp(data["not_before"])
    assert is_iso8601_timestamp(data["not_after"])
    assert data["not_after"] > data["not_before"], "not_after must be strictly later than not_before"
    assert isinstance(data["blocked_submission_count"], int)


def assert_app_record(data: dict):
    assert_common_fields(data)
    assert data["platform"] in ("IOS", "ANDROID")
    assert data["primary_category"] in (
        "GAMES",
        "FINANCE",
        "HEALTH",
        "SOCIAL",
        "PRODUCTIVITY",
        "KIDS",
    )
    assert 1 <= len(data["display_name"]) <= 30
    assert data["listing_state"] in _values(ListingState)
    assert data["distribution_state"] in _values(DistributionState)
    assert data["compliance_posture"] in _values(CompliancePosture)
    assert isinstance(data["posture_reason_codes"], list)
    assert isinstance(data["feature_compliance_index"], (int, float))
    assert isinstance(data["rollback_count"], int)
    assert_share_conservation(data)


def assert_share_conservation(data: dict):
    """released_share_pct and held_back_share_pct always sum to exactly 100.00."""
    total = round(data["released_share_pct"] + data["held_back_share_pct"], 2)
    assert total == 100.00, (
        f"released_share_pct ({data['released_share_pct']}) + held_back_share_pct "
        f"({data['held_back_share_pct']}) must be exactly 100.00, got {total}"
    )


def assert_guideline_rule(data: dict):
    assert_common_fields(data)
    assert data["category"] in ("SAFETY", "PRIVACY", "COMMERCE", "LEGAL", "DESIGN")
    assert data["status"] in _values(GuidelineStatus)
    assert isinstance(data["severity_weight"], int)
    assert isinstance(data["remediation_grace_days"], int)
    assert isinstance(data["requires_feature_mapping"], bool)
    assert isinstance(data["impacted_app_count"], int)
    assert is_iso8601_timestamp(data["effective_from"])


def assert_feature_mapping(data: dict):
    assert_common_fields(data)
    assert data["self_review_status"] in _values(SelfReviewStatus)
    assert isinstance(data["risk_weight"], (int, float))
    assert 0.00 <= data["risk_weight"] <= 10.00


def assert_submission(data: dict):
    assert_common_fields(data)
    assert data["state"] in _values(SubmissionState)
    assert data["release_mode"] in ("IMMEDIATE", "PHASED", "MANUAL")
    assert data["submission_channel"] in ("STANDARD", "EXPEDITED")
    assert isinstance(data["build_number"], int)
    assert isinstance(data["pre_review_passed"], bool)
    assert isinstance(data["pre_review_blocking_reasons"], list)
    assert isinstance(data["declared_privacy_items"], list)
    assert isinstance(data["tracking_consent_prompt_present"], bool)
    assert isinstance(data["resubmission_count"], int)
    assert isinstance(data["metadata_locale_count"], int)
    for score_field in (
        "disclosure_accuracy_score_provisional",
        "disclosure_accuracy_score_final",
    ):
        value = data.get(score_field)
        if value is not None:
            assert 0.0000 <= value <= 1.0000, f"{score_field} lives in [0.0000, 1.0000]"
    if data.get("priority_score") is not None:
        assert 0.00 <= data["priority_score"] <= 100.00


def assert_metadata_locale(data: dict):
    assert_common_fields(data)
    assert 1 <= len(data["title"]) <= 30
    assert isinstance(data["screenshot_counts"], dict)
    for device_class, count in data["screenshot_counts"].items():
        assert isinstance(count, int) and count >= 0
    assert isinstance(data["required_device_classes"], list)
    assert isinstance(data["is_complete"], bool)
    assert isinstance(data["is_primary"], bool)


def assert_behavior_finding(data: dict):
    assert_common_fields(data)
    assert data["data_type"] in (
        "PRECISE_LOCATION",
        "CONTACTS",
        "DEVICE_ID",
        "EMAIL",
        "PURCHASE_HISTORY",
        "HEALTH",
        "USAGE_DATA",
    )
    assert data["observed_purpose"] in (
        "ANALYTICS",
        "ADVERTISING",
        "APP_FUNCTIONALITY",
        "PERSONALIZATION",
        "THIRD_PARTY_SHARING",
    )
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert data["status"] in _values(FindingStatus)
    assert 0.0000 <= data["scanner_confidence"] <= 1.0000
    assert isinstance(data["observed_linked_to_user"], bool)
    assert isinstance(data["observed_tracking"], bool)
    assert is_iso8601_timestamp(data["detected_at"])


def assert_rejection_reason(data: dict):
    assert_common_fields(data)
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert data["disposition"] in ("PENDING", "ACCEPTED", "CONTESTED")
    assert data["appeal_disposition"] in ("PENDING", "OVERTURNED", "UPHELD")
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_appeal_request(data: dict):
    assert_common_fields(data)
    assert data["state"] in _values(AppealState)
    assert data["appeal_type"] in ("GUIDELINE_INTERPRETATION", "FACTUAL_ERROR")
    assert 20 <= len(data["argument"]) <= 2000
    assert isinstance(data["cited_rejection_reason_ids"], list)
    assert len(data["cited_rejection_reason_ids"]) >= 1


def assert_expedite_request(data: dict):
    assert_common_fields(data)
    assert data["state"] in _values(ExpediteState)
    assert data["justification_category"] in (
        "CRITICAL_BUG",
        "SECURITY_FIX",
        "TIME_SENSITIVE_EVENT",
    )
    assert 20 <= len(data["justification"]) <= 1000


def assert_review_capacity_window(data: dict):
    assert_common_fields(data)
    assert data["platform"] in ("IOS", "ANDROID")
    assert data["status"] in _values(WindowStatus)
    assert data["capacity_slots"] >= 1
    assert data["ends_at"] > data["starts_at"], "ends_at must be strictly after starts_at"
    assert_slot_conservation(data)


def assert_slot_conservation(data: dict):
    """slots_reserved, slots_consumed and slots_available always sum to capacity_slots."""
    total = data["slots_reserved"] + data["slots_consumed"] + data["slots_available"]
    assert total == data["capacity_slots"], (
        f"slots_reserved ({data['slots_reserved']}) + slots_consumed "
        f"({data['slots_consumed']}) + slots_available ({data['slots_available']}) "
        f"must equal capacity_slots ({data['capacity_slots']}), got {total}"
    )


def assert_rollout_plan(data: dict):
    assert_common_fields(data)
    assert data["state"] in _values(RolloutState)
    assert data["mode"] in ("IMMEDIATE", "PHASED")
    assert isinstance(data["phase_index"], int)
    assert 0 <= data["phase_index"] <= 6
    assert isinstance(data["halt_distribution"], bool)
    assert_share_conservation(data)


def assert_commerce_item(data: dict):
    assert_common_fields(data)
    assert data["item_type"] in (
        "CONSUMABLE",
        "NON_CONSUMABLE",
        "SUBSCRIPTION",
        "EXTERNAL_PAYMENT_LINK",
    )
    assert data["entitlement_class"] in ("DIGITAL_CONTENT", "PHYSICAL_GOOD", "SERVICE")
    assert data["status"] in _values(CommerceItemStatus)
    assert isinstance(data["price_tier_cents"], int) and data["price_tier_cents"] >= 0
    assert isinstance(data["reported_gross_cents"], int)
    assert isinstance(data["commission_cents"], int), "money is handled in integer cents"
    assert isinstance(data["subscriber_retention_months"], int)


def assert_impact_assessment(data: dict):
    assert_common_fields(data)
    assert data["status"] in _values(ImpactStatus)
    assert isinstance(data["affected_feature_codes"], list)
    assert data["exposure_factor"] in (1.0, 1.5)
    assert isinstance(data["impact_severity"], (int, float))
    assert is_iso8601_timestamp(data["remediation_deadline_at"])
    assert is_iso8601_timestamp(data["opened_at"])


def assert_expedite_credit_conservation(account: dict, credits_used: int):
    """expedite_credits_remaining plus the credits used inside the rolling window
    always sum to exactly 2."""
    total = account["expedite_credits_remaining"] + credits_used
    assert total == 2, (
        f"expedite_credits_remaining ({account['expedite_credits_remaining']}) plus "
        f"credits used ({credits_used}) must sum to exactly 2, got {total}"
    )


def assert_posture(data: dict, posture: str, reason_codes=None):
    assert data["compliance_posture"] == posture, (
        f"expected compliance_posture {posture}, got {data['compliance_posture']} "
        f"with reasons {data.get('posture_reason_codes')}"
    )
    if reason_codes is not None:
        assert data["posture_reason_codes"] == list(reason_codes), (
            f"expected posture_reason_codes {list(reason_codes)}, "
            f"got {data['posture_reason_codes']}"
        )


def num(value):
    """Coerce a JSON-encoded decimal to float.

    Money and score fields may legitimately serialise as either a JSON number
    or a decimal string, so every numeric comparison funnels through here.
    """
    assert value is not None, "expected a numeric value, got null"
    return float(value)


def assert_decimal_equals(actual, expected, places=2, label="value"):
    """Compare a serialised decimal against an exact expected magnitude."""
    got = num(actual)
    assert abs(got - float(expected)) < 10 ** -(places + 3), (
        f"{label}: expected {expected} to {places} decimal places, got {actual!r}"
    )
