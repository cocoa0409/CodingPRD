"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_seq):04d}"


CLEAN_AGE_RATING_ANSWERS = {
    "violence": 0,
    "sexual_content": 0,
    "profanity": 0,
    "gambling_simulated": 0,
    "drugs_alcohol": 0,
    "horror": 0,
    "unrestricted_web_access": False,
    "user_generated_content": False,
    "ugc_moderation_enabled": False,
    "real_money_gambling": False,
    "contests": False,
}


def age_rating_answers(**overrides) -> dict:
    """The questionnaire: six intensity keys 0..3 plus the five declared booleans."""
    answers = dict(CLEAN_AGE_RATING_ANSWERS)
    answers.update(overrides)
    return answers


def create_publisher_account_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Northwind Mobile Ltd {unique_suffix()}",
        "contact_email": "ops@northwind.example",
        "membership_paid_through_at": "2027-08-01T00:00:00Z",
        "commerce_program_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_signing_credential_payload(
    account_id, expected_publisher_account_version, **overrides
) -> dict:
    defaults = {
        "expected_publisher_account_version": expected_publisher_account_version,
        "publisher_account_id": account_id,
        "credential_type": "DISTRIBUTION_CERT",
        "platform": "IOS",
        "key_custody": "HSM",
        "not_before": "2026-07-01T00:00:00Z",
        "not_after": "2027-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_app_record_payload(account_id, **overrides) -> dict:
    defaults = {
        "publisher_account_id": account_id,
        "bundle_id": f"com.northwind.wallet{unique_suffix()}",
        "platform": "IOS",
        "display_name": "Northwind Wallet",
        "primary_category": "FINANCE",
    }
    defaults.update(overrides)
    return defaults


def create_guideline_rule_payload(**overrides) -> dict:
    suffix = unique_suffix()
    defaults = {
        "rule_code": f"5.1.{suffix}",
        "title": "Data collection and storage",
        "category": "PRIVACY",
        "version_label": "2026.08",
        "effective_from": "2026-07-01T00:00:00Z",
        "requires_feature_mapping": True,
    }
    defaults.update(overrides)
    return defaults


def create_feature_mapping_payload(app_record_id, guideline_rule_id, **overrides) -> dict:
    defaults = {
        "app_record_id": app_record_id,
        "guideline_rule_id": guideline_rule_id,
        "feature_code": "ACCOUNT_DELETION",
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(
    app_record_id, signing_credential_id, expected_app_record_version, **overrides
) -> dict:
    defaults = {
        "expected_app_record_version": expected_app_record_version,
        "app_record_id": app_record_id,
        "signing_credential_id": signing_credential_id,
        "build_number": 10,
        "version_string": "1.0.0",
        "release_mode": "PHASED",
    }
    defaults.update(overrides)
    return defaults


def create_metadata_locale_payload(submission_id, **overrides) -> dict:
    defaults = {
        "submission_id": submission_id,
        "locale": "en-US",
        "title": "Northwind Wallet",
        "screenshot_counts": {"PHONE_65": 3, "TABLET_129": 2},
        "is_primary": True,
    }
    defaults.update(overrides)
    return defaults


def create_behavior_finding_payload(submission_id, **overrides) -> dict:
    defaults = {
        "submission_id": submission_id,
        "data_type": "DEVICE_ID",
        "observed_purpose": "ADVERTISING",
        "observed_linked_to_user": True,
        "observed_tracking": True,
        "endpoint_domain": "ads.thirdparty.example",
        "severity": "MAJOR",
        "scanner_confidence": 0.95,
        "detected_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def privacy_item(data_type="DEVICE_ID", purpose="ANALYTICS", linked=False, tracking=False) -> dict:
    return {
        "data_type": data_type,
        "purpose": purpose,
        "linked_to_user": linked,
        "used_for_tracking": tracking,
    }


def create_appeal_request_payload(submission_id, cited_reason_ids, **overrides) -> dict:
    defaults = {
        "submission_id": submission_id,
        "appeal_type": "GUIDELINE_INTERPRETATION",
        "argument": (
            "The cited guideline does not apply to this build because the feature "
            "was removed before the binary was produced."
        ),
        "cited_rejection_reason_ids": list(cited_reason_ids),
    }
    defaults.update(overrides)
    return defaults


def create_expedite_request_payload(submission_id, **overrides) -> dict:
    defaults = {
        "submission_id": submission_id,
        "justification_category": "SECURITY_FIX",
        "justification": (
            "A remote code execution defect is live in production and this build "
            "carries the only available fix."
        ),
    }
    defaults.update(overrides)
    return defaults


def create_review_capacity_window_payload(**overrides) -> dict:
    defaults = {
        "platform": "IOS",
        "reviewer_pool_code": "POOL_A",
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": "2026-12-31T00:00:00Z",
        "capacity_slots": 5,
    }
    defaults.update(overrides)
    return defaults


def create_rollout_plan_payload(
    app_record_id, submission_id, expected_app_record_version, **overrides
) -> dict:
    defaults = {
        "expected_app_record_version": expected_app_record_version,
        "app_record_id": app_record_id,
        "submission_id": submission_id,
        "mode": "PHASED",
        "scheduled_start_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_commerce_item_payload(app_record_id, **overrides) -> dict:
    defaults = {
        "app_record_id": app_record_id,
        "item_type": "CONSUMABLE",
        "reference_name": f"coin_pack_{unique_suffix()}",
        "price_tier_cents": 499,
        "entitlement_class": "DIGITAL_CONTENT",
    }
    defaults.update(overrides)
    return defaults


def rejection_reason_entry(guideline_rule_id, severity="CRITICAL", **overrides) -> dict:
    defaults = {
        "guideline_rule_id": guideline_rule_id,
        "reason_code": "PRIVACY_LABEL_INACCURATE",
        "severity": severity,
        "detail": "Undisclosed device-id sharing to an advertising domain",
    }
    defaults.update(overrides)
    return defaults
