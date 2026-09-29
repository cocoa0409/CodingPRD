"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ALLOWED_DISPOSAL_METHODS,
    INTEGRATION_TYPE_POINTS,
    METHOD_TIER,
    REQUIRED_CONTENT_KEYS,
)

DETERMINATION_STATUSES = [
    "NOT_ASSESSED",
    "GENERAL_AUDIENCE",
    "MIXED_AUDIENCE",
    "CHILD_DIRECTED_PRIMARY",
]
COMPLIANCE_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
SAFE_HARBOR_STATUSES = ["NOT_ENROLLED", "CERTIFIED", "ASSESSMENT_DUE", "LAPSED"]

SERVICE_COUNTER_FIELDS = [
    "active_consent_count",
    "granted_disclosure_consent_count",
    "live_child_data_element_count",
    "lifetime_collected_element_count",
    "third_party_exposure_points",
    "open_audit_count",
    "audit_decision_count",
    "evidence_sequence_counter",
    "compliance_run_sequence",
]


def normalize_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to a single comparable form.

    Timestamps are returned with three fractional digits, so a test that expects
    a whole-second instant must compare instants rather than strings.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def assert_instant(actual, expected: str, field: str = "timestamp") -> None:
    """The value must be the given instant, whatever fractional form it is rendered in."""
    assert actual is not None, f"{field} should be {expected}, got null"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{field} should be {expected}, got {actual}"
    )


def assert_common_fields(data: dict) -> None:
    """Every resource carries a UUID `id` and an ISO 8601 `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_versioned_fields(data: dict) -> None:
    """Most resources also carry `updated_at` and an integer `version` beginning at 1."""
    assert_common_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must begin at 1, got {data['version']}"


def assert_online_service(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["name"], str) and data["name"], "name must be a non-empty string"
    assert isinstance(data["operator_organization"], str) and data["operator_organization"]
    assert data["service_category"] in [
        "GAME",
        "VIDEO_PLATFORM",
        "EDUCATION_APP",
        "SOCIAL_NETWORK",
        "GENERAL_INTEREST_PORTAL",
    ]
    assert data["subject_matter_code"] in [
        "CHILD_ENTERTAINMENT",
        "CHILD_EDUCATION",
        "FAMILY_MIXED",
        "TEEN_LIFESTYLE",
        "ADULT_GENERAL",
    ]
    assert data["determination_status"] in DETERMINATION_STATUSES
    assert data["compliance_posture"] in COMPLIANCE_POSTURES
    assert data["posture_override"] in COMPLIANCE_POSTURES + [None]
    assert data["determination_variant_applied"] in ["AUDIENCE_FIRST", "DESIGN_FIRST", None]
    assert data["safe_harbor_status"] in SAFE_HARBOR_STATUSES
    for field in SERVICE_COUNTER_FIELDS:
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never be negative, got {data[field]}"


def assert_service_posture_ladder(data: dict) -> None:
    """The posture must agree with the ordered clauses that derive it."""
    override = data["posture_override"]
    if override is not None:
        expected = override
    elif data["third_party_exposure_points"] >= 80:
        expected = "FROZEN"
    elif data["open_audit_count"] >= 1:
        expected = "RESTRICTED"
    elif data["third_party_exposure_points"] >= 40:
        expected = "RESTRICTED"
    elif data["safe_harbor_status"] == "LAPSED":
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert data["compliance_posture"] == expected, (
        f"compliance_posture should be {expected} for override={override}, "
        f"exposure={data['third_party_exposure_points']}, "
        f"open_audits={data['open_audit_count']}, "
        f"safe_harbor_status={data['safe_harbor_status']}; "
        f"got {data['compliance_posture']}"
    )


def assert_service_count_invariants(data: dict) -> None:
    """Counter relationships that must hold on every read of a service."""
    assert data["live_child_data_element_count"] <= data["lifetime_collected_element_count"], (
        "live_child_data_element_count may never exceed lifetime_collected_element_count"
    )
    assert data["granted_disclosure_consent_count"] <= data["active_consent_count"], (
        "granted_disclosure_consent_count may never exceed active_consent_count"
    )


def assert_determination_evidence(data: dict) -> None:
    """Evidence is append-only: it carries `id` and `created_at` and nothing else common."""
    assert_common_fields(data)
    assert "updated_at" not in data, "determination evidence must carry no updated_at field"
    assert "version" not in data, "determination evidence must carry no version field"
    assert data["evidence_kind"] in ["AUDIENCE_SAMPLE", "DESIGN_FACTOR"]
    assert isinstance(data["evidence_sequence"], int) and data["evidence_sequence"] >= 1
    if data["evidence_kind"] == "AUDIENCE_SAMPLE":
        assert data["measurement_method"] in ["PANEL", "AGE_SCREEN_LOG", "SELF_REPORTED"]
        assert isinstance(data["total_users"], int) and data["total_users"] >= 1
        assert isinstance(data["users_under_13"], int)
        assert 0 <= data["users_under_13"] <= data["total_users"]
    else:
        assert data["factor_code"] in [
            "SUBJECT_MATTER",
            "VISUAL_CONTENT",
            "CHILD_CELEBRITIES",
            "LANGUAGE",
            "MUSIC_AUDIO",
            "ADVERTISING_PLACEMENT",
            "INTERACTIVE_DESIGN",
        ]
        assert data["rating"] in ["ABSENT", "INCIDENTAL", "MODERATE", "STRONG"]


def assert_age_screen(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["mechanism"] in ["NEUTRAL_DOB_ENTRY", "AGE_RANGE_SELECT", "ACCOUNT_AGE_INHERIT"]
    assert data["status"] in ["DRAFT", "IN_REVIEW", "ACTIVE", "REJECTED", "RETIRED"]
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 2
    assert isinstance(data["neutrality_violation_codes"], list)
    for code in data["neutrality_violation_codes"]:
        assert code in [
            "PREFILLED_AGE",
            "RETRY_ALLOWED",
            "OUTCOME_NOT_PERSISTED",
            "UNVERIFIED_INHERIT",
        ]


def assert_neutrality_codes_in_declared_order(codes: list) -> None:
    """Codes must appear in the fixed order the PRD declares, whichever are present."""
    order = ["PREFILLED_AGE", "RETRY_ALLOWED", "OUTCOME_NOT_PERSISTED", "UNVERIFIED_INHERIT"]
    positions = [order.index(code) for code in codes]
    assert positions == sorted(positions), (
        f"neutrality_violation_codes must follow the declared order {order}, got {codes}"
    )


def assert_parental_notice(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]
    assert data["delivery_channel"] in ["EMAIL", "IN_APP_MODAL", "POSTAL", "SCHOOL_INTERMEDIARY"]
    assert isinstance(data["content_keys"], list)
    assert isinstance(data["missing_content_keys"], list)
    assert isinstance(data["disclosed_integration_vendors"], list)


def assert_missing_content_keys_in_canonical_order(missing: list) -> None:
    """`missing_content_keys` is listed in the canonical section order, not the client's order."""
    positions = [REQUIRED_CONTENT_KEYS.index(key) for key in missing]
    assert positions == sorted(positions), (
        f"missing_content_keys must follow the canonical order {REQUIRED_CONTENT_KEYS}, got {missing}"
    )


def assert_activity(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["activity_code"], str) and data["activity_code"]
    assert isinstance(data["participation_required_elements"], list)


def assert_consent_request(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in [
        "INITIATED",
        "NOTICE_DELIVERED",
        "PENDING_VERIFICATION",
        "GRANTED",
        "DENIED",
        "EXPIRED",
        "REVOKED",
        "SUPERSEDED",
    ]
    assert data["consent_method"] in METHOD_TIER
    assert isinstance(data["intended_uses"], list) and data["intended_uses"]
    assert data["method_assurance_tier"] == METHOD_TIER[data["consent_method"]], (
        "method_assurance_tier must be the tier of the chosen consent_method"
    )
    assert 1 <= data["required_tier_at_creation"] <= 3
    assert isinstance(data["secondary_confirmation_received"], bool)


def assert_child_data_record(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ["COLLECTED", "SCHEDULED_FOR_DISPOSAL", "DISPOSED"]
    assert data["age_screen_outcome"] in ["UNDER_13", "THIRTEEN_PLUS"]
    assert is_iso8601_timestamp(data["collected_at"])
    assert isinstance(data["retention_days_applied"], int) and data["retention_days_applied"] >= 1
    assert data["disposal_method_applied"] in (
        ALLOWED_DISPOSAL_METHODS[data["data_element_code"]]
    ), (
        f"disposal_method_applied {data['disposal_method_applied']} is not admissible "
        f"for {data['data_element_code']}"
    )
    assert is_iso8601_timestamp(data["disposal_due_at"])


def assert_parental_rights_request(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in [
        "SUBMITTED",
        "VERIFYING",
        "VERIFIED",
        "VERIFICATION_FAILED",
        "REJECTED",
        "FULFILLED",
    ]
    assert data["right_type"] in ["REVIEW", "DELETE", "REFUSE_FURTHER_COLLECTION"]
    assert isinstance(data["verification_attempt_count"], int)
    assert 0 <= data["verification_attempt_count"] <= 3
    assert data["scope_mode"] in ["PARENT_CONSENT_SCOPE", "CHILD_IDENTITY_SCOPE", None]


def assert_third_party_integration(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ["DECLARED", "AUDIT_PENDING", "APPROVED", "BLOCKED"]
    assert data["integration_type"] in INTEGRATION_TYPE_POINTS
    assert data["placement_area"] in ["CHILD_DIRECTED_AREA", "GENERAL_AREA"]
    assert isinstance(data["collects_persistent_identifier"], bool)
    assert isinstance(data["disclosed_in_notice"], bool)
    expected_points = INTEGRATION_TYPE_POINTS[data["integration_type"]] * (
        2 if data["collects_persistent_identifier"] else 1
    )
    assert data["exposure_points"] == expected_points, (
        f"exposure_points for {data['integration_type']} with persistent identifier "
        f"{data['collects_persistent_identifier']} should be {expected_points}, "
        f"got {data['exposure_points']}"
    )


def assert_retention_schedule(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["retention_days"], int) and data["retention_days"] >= 1
    assert data["disposal_method"] in ALLOWED_DISPOSAL_METHODS[data["data_element_code"]]
    assert isinstance(data["defined_purpose_statement"], str) and data["defined_purpose_statement"]


def assert_safe_harbor_program(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["regulator_approved"], bool)
    assert isinstance(data["annual_assessment_required"], bool)
    assert isinstance(data["assessment_validity_days"], int)
    assert isinstance(data["assessment_grace_days"], int)


def assert_safe_harbor_assessment(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "REMEDIATION_REQUIRED", "CERTIFIED", "FAILED"]
    assert isinstance(data["assessment_year"], int)
    assert isinstance(data["preparer_user_id"], str) and data["preparer_user_id"]
    assert isinstance(data["remediation_round"], int) and 0 <= data["remediation_round"] <= 2
    assert isinstance(data["findings_open_count"], int) and data["findings_open_count"] >= 0
    if data["status"] == "CERTIFIED":
        assert data["certifier_user_id"] != data["preparer_user_id"], (
            "a certified assessment must have been certified by someone other than its preparer"
        )


def assert_compliance_run_summary(data: dict) -> None:
    """The run reports an inline counter object rather than a stored entity."""
    for field in (
        "service_id",
        "run_sequence",
        "expired_consent_count",
        "scheduled_count",
        "disposed_count",
        "live_child_data_element_count_after",
        "compliance_posture_after",
    ):
        assert field in data, f"compliance run summary must report {field}"
    assert isinstance(data["run_sequence"], int) and data["run_sequence"] >= 1
    assert data["compliance_posture_after"] in COMPLIANCE_POSTURES


def assert_design_score(data: dict, expected: float) -> None:
    """`design_score` is carried to 2 decimal places."""
    actual = float(data["design_score"])
    assert abs(actual - expected) < 0.005, (
        f"design_score should be {expected:.2f}, got {actual}"
    )


def assert_audience_child_share(data: dict, expected: Optional[float]) -> None:
    """`audience_child_share` is carried to 4 decimal places, or is null."""
    actual = data["audience_child_share"]
    if expected is None:
        assert actual is None, f"audience_child_share should be null, got {actual}"
        return
    assert actual is not None, f"audience_child_share should be {expected}, got null"
    assert abs(float(actual) - expected) < 0.00005, (
        f"audience_child_share should be {expected:.4f}, got {actual}"
    )
