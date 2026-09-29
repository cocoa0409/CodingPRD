"""Per-entity shape assertions and the domain invariants worth naming once.

Timestamps are compared through :func:`assert_instant`, which normalises the optional
fractional-second digits before comparing, because timestamp comparisons in this
contract are evaluated at second granularity.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_valid_uuid,
)

from .constants import DECIMAL_TOLERANCE, QUARTER_HOUR
from .types import (
    AbstractionStatus,
    AgreementStatus,
    CompletionStatus,
    ComplianceStatus,
    CycleStatus,
    DeficiencyClass,
    DeficiencyStatus,
    EdDisposition,
    InclusionReason,
    InclusionStatus,
    PiOrigin,
    PiStatus,
    ReadinessPosture,
    TriageReviewStatus,
    ValidationStatus,
    VerifiedStatus,
)

# ─── Primitive comparisons ────────────────────────────────


def canonical_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to second granularity.

    ``2026-08-01T00:00:00Z`` and ``2026-08-01T00:00:00.000Z`` denote the same instant,
    so both collapse onto the same canonical string before comparison.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    if "." in text:
        text = text.split(".", 1)[0]
    return text + "Z"


def assert_instant(actual: Any, expected: str, field: str = "timestamp") -> None:
    """Assert a server-stamped instant equals the expected instant."""
    assert actual is not None, f"{field} must not be null"
    assert_timestamp_format(actual)
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_decimal(actual: Any, expected: float, field: str = "value") -> None:
    """Assert a stored decimal equals the expected two-decimal value."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=DECIMAL_TOLERANCE), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_quarter_hour_multiple(value: Any, field: str = "weighted_credit_hours") -> None:
    """Assert a weighted credit-hour figure is an exact multiple of a quarter hour."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    quarters = value / QUARTER_HOUR
    assert round(quarters) == pytest.approx(quarters, abs=1e-6), (
        f"{field} must be an exact multiple of {QUARTER_HOUR}, got {value}"
    )


def _assert_audited(record: Dict[str, Any], entity: str) -> None:
    """Assert the three system-managed audit properties every audited resource carries."""
    assert is_valid_uuid(record["id"]), f"{entity}.id must be a UUID: {record['id']!r}"
    assert_timestamp_format(record["created_at"])
    assert_timestamp_format(record["updated_at"])
    assert isinstance(record["version"], int), f"{entity}.version must be an integer"
    assert record["version"] >= 1, f"{entity}.version starts at 1"


# ─── Trauma center ────────────────────────────────────────


def assert_trauma_center(center: Dict[str, Any]) -> None:
    """Assert the shape of a trauma center, including every derived field."""
    _assert_audited(center, "TraumaCenter")
    assert isinstance(center["name"], str) and center["name"]
    assert isinstance(center["state_code"], str) and len(center["state_code"]) == 2
    assert center["state_code"].isupper()
    assert center["designation_level"] in ("LEVEL_I", "LEVEL_II", "LEVEL_III")
    assert_timestamp_format(center["verification_cycle_start_date"])
    assert center["readiness_posture"] in (
        ReadinessPosture.READY,
        ReadinessPosture.CONDITIONAL,
        ReadinessPosture.AT_RISK,
        ReadinessPosture.SUSPENDED,
    )
    assert center["national_verification_status"] in (
        "NOT_VERIFIED",
        "VERIFIED",
        "CONTINGENCY",
        "SUSPENDED",
    )
    assert center["state_designation_status"] in (
        "NOT_DESIGNATED",
        "DESIGNATED",
        "PROVISIONAL",
        "WITHDRAWN",
    )
    for decimal_field in (
        "registry_compliance_score",
        "outreach_credit_hours_ytd",
        "under_triage_rate_pct",
        "over_triage_rate_pct",
    ):
        value = center[decimal_field]
        assert isinstance(value, (int, float)) and not isinstance(value, bool), (
            f"TraumaCenter.{decimal_field} must be a JSON number, got {value!r}"
        )
        assert value >= 0.00, f"TraumaCenter.{decimal_field} floors at 0.00"
    for counter in (
        "open_critical_deficiency_count",
        "escalated_critical_deficiency_count",
        "open_pi_event_count",
        "closed_pi_event_count",
        "registry_included_case_count",
        "registry_excluded_case_count",
    ):
        assert isinstance(center[counter], int), (
            f"TraumaCenter.{counter} must be an exact integer"
        )
        assert center[counter] >= 0


def assert_center_defaults(center: Dict[str, Any]) -> None:
    """Assert a freshly registered center carries every declared clean default."""
    assert_trauma_center(center)
    assert center["readiness_posture"] == ReadinessPosture.READY
    assert center["national_verification_status"] == "NOT_VERIFIED"
    assert center["state_designation_status"] == "NOT_DESIGNATED"
    assert_decimal(center["registry_compliance_score"], 100.00, "registry_compliance_score")
    assert_decimal(center["outreach_credit_hours_ytd"], 0.00, "outreach_credit_hours_ytd")
    assert_decimal(center["under_triage_rate_pct"], 0.00, "under_triage_rate_pct")
    assert_decimal(center["over_triage_rate_pct"], 0.00, "over_triage_rate_pct")
    assert center["open_critical_deficiency_count"] == 0
    assert center["escalated_critical_deficiency_count"] == 0
    assert center["open_pi_event_count"] == 0
    assert center["closed_pi_event_count"] == 0
    assert center["registry_included_case_count"] == 0
    assert center["registry_excluded_case_count"] == 0
    assert center["version"] == 1


def assert_cohort_partition(
    center: Dict[str, Any], included: int, excluded: int
) -> None:
    """Assert the center's cohort partition, which is rewritten rather than adjusted."""
    assert center["registry_included_case_count"] == included, (
        f"registry_included_case_count: expected {included}, "
        f"got {center['registry_included_case_count']}"
    )
    assert center["registry_excluded_case_count"] == excluded, (
        f"registry_excluded_case_count: expected {excluded}, "
        f"got {center['registry_excluded_case_count']}"
    )


def assert_pi_partition(center: Dict[str, Any], open_count: int, closed_count: int) -> None:
    """Assert the conserved open/closed PI event partition."""
    assert center["open_pi_event_count"] == open_count, (
        f"open_pi_event_count: expected {open_count}, "
        f"got {center['open_pi_event_count']}"
    )
    assert center["closed_pi_event_count"] == closed_count, (
        f"closed_pi_event_count: expected {closed_count}, "
        f"got {center['closed_pi_event_count']}"
    )


# ─── Activation tier and dictionary rule ──────────────────


def assert_activation_tier(tier: Dict[str, Any], center_id: Optional[str] = None) -> None:
    """Assert the shape of one activation criteria tier."""
    _assert_audited(tier, "ActivationCriteriaTier")
    if center_id is not None:
        assert tier["center_id"] == center_id
    assert tier["tier_code"] in ("TIER_1_FULL", "TIER_2_MODIFIED", "TIER_3_CONSULT")
    for bounded in ("surgeon_response_limit_minutes", "specialty_response_limit_minutes"):
        assert isinstance(tier[bounded], int)
        assert 1 <= tier[bounded] <= 240
    assert isinstance(tier["iss_threshold"], int)
    assert 0 <= tier["iss_threshold"] <= 75


def assert_data_dictionary_rule(rule: Dict[str, Any]) -> None:
    """Assert the shape of one dictionary rule, which is immutable configuration.

    The rule carries only ``id`` and ``created_at`` of the audit properties: it has no
    ``updated_at`` and no ``version``.
    """
    assert is_valid_uuid(rule["id"]), f"DataDictionaryRule.id must be a UUID: {rule['id']!r}"
    assert_timestamp_format(rule["created_at"])
    assert "updated_at" not in rule, (
        "DataDictionaryRule has no updated_at: it is immutable configuration"
    )
    assert "version" not in rule, (
        "DataDictionaryRule has no version: it is immutable configuration"
    )
    assert rule["field_name"] in (
        "iss_abstracted",
        "gcs_arrival",
        "mechanism_code",
        "ed_departure_at",
    )
    assert rule["rule_kind"] in ("REQUIRED", "RANGE", "CONFORMANCE")
    assert rule["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    expected_weight = {"CRITICAL": 4, "MAJOR": 2, "MINOR": 1}[rule["severity"]]
    assert rule["error_weight"] == expected_weight, (
        f"error_weight is derived from severity: {rule['severity']} "
        f"must weigh {expected_weight}, got {rule['error_weight']}"
    )


# ─── Registry case and abstraction ────────────────────────


def assert_registry_case(case: Dict[str, Any], center_id: Optional[str] = None) -> None:
    """Assert the shape of a registry case, including both state dimensions."""
    _assert_audited(case, "RegistryCase")
    if center_id is not None:
        assert case["center_id"] == center_id
    assert is_valid_uuid(case["activation_tier_id"])
    assert isinstance(case["mrn"], str) and case["mrn"]
    assert_timestamp_format(case["arrival_at"])
    assert isinstance(case["injury_severity_score"], int)
    assert 0 <= case["injury_severity_score"] <= 75
    assert isinstance(case["los_hours"], (int, float)) and case["los_hours"] >= 0
    assert case["ed_disposition"] in (
        EdDisposition.ADMIT,
        EdDisposition.TRANSFER_OUT,
        EdDisposition.DISCHARGE,
        EdDisposition.MORGUE,
    )
    assert case["abstraction_status"] in (
        AbstractionStatus.PENDING,
        AbstractionStatus.ABSTRACTED,
        AbstractionStatus.VALIDATED,
        AbstractionStatus.REJECTED,
        AbstractionStatus.LOCKED,
    )
    assert case["triage_review_status"] in (
        TriageReviewStatus.UNREVIEWED,
        TriageReviewStatus.UNDER_TRIAGE_CONFIRMED,
        TriageReviewStatus.OVER_TRIAGE_CONFIRMED,
        TriageReviewStatus.APPROPRIATE,
    )
    assert isinstance(case["effective_iss"], int)
    assert case["inclusion_status"] in (InclusionStatus.INCLUDED, InclusionStatus.EXCLUDED)
    assert case["inclusion_reason"] in (
        InclusionReason.MEETS_INCLUSION_CRITERIA,
        InclusionReason.TRANSFER_OUT_MINOR_UNDER_24H,
        InclusionReason.BELOW_INJURY_THRESHOLD,
    )
    if case["abstraction_status"] != AbstractionStatus.LOCKED:
        assert case["locked_at"] is None, (
            "locked_at is null until the case is locked"
        )


def assert_abstraction_record(
    record: Dict[str, Any], case_id: Optional[str] = None
) -> None:
    """Assert the shape of an abstraction record, including its persisted scan results."""
    _assert_audited(record, "AbstractionRecord")
    if case_id is not None:
        assert record["case_id"] == case_id
    assert isinstance(record["submitted_by_user_id"], str) and record["submitted_by_user_id"]
    assert record["validation_status"] in (
        ValidationStatus.SUBMITTED,
        ValidationStatus.VALIDATED,
        ValidationStatus.REJECTED,
    )
    if record["validation_status"] == ValidationStatus.SUBMITTED:
        assert record["validated_by_user_id"] is None
        assert record["rejection_reason"] is None
    assert isinstance(record["dictionary_error_count"], int)
    assert record["dictionary_error_count"] >= 0
    assert record["band_multiplier_used"] in (1.0, 1.5, 2.0), (
        f"band_multiplier_used must be 1.0, 1.5 or 2.0, got {record['band_multiplier_used']}"
    )
    assert isinstance(record["applied_penalty_points"], (int, float))
    assert record["applied_penalty_points"] >= 0


# ─── Response log ─────────────────────────────────────────


def assert_response_log(log: Dict[str, Any], case_id: Optional[str] = None) -> None:
    """Assert the shape of a response log and the derivation of its compliance."""
    _assert_audited(log, "ResponseLog")
    if case_id is not None:
        assert log["case_id"] == case_id
    assert log["responder_role"] in (
        "SURGEON",
        "ANESTHESIA",
        "NEUROSURGERY",
        "ORTHOPEDICS",
        "RADIOLOGY",
    )
    assert isinstance(log["responder_user_id"], str) and log["responder_user_id"]
    assert_timestamp_format(log["notified_at"])
    assert isinstance(log["applicable_limit_minutes"], int)
    assert log["compliance_status"] in (
        ComplianceStatus.COMPLIANT,
        ComplianceStatus.LATE,
        ComplianceStatus.UNDOCUMENTED,
    )
    if log["arrived_at"] is None:
        assert log["response_minutes"] is None, (
            "a null arrived_at leaves response_minutes null"
        )
        assert log["compliance_status"] == ComplianceStatus.UNDOCUMENTED
    else:
        assert_timestamp_format(log["arrived_at"])
        assert isinstance(log["response_minutes"], (int, float))
        if log["response_minutes"] <= log["applicable_limit_minutes"]:
            assert log["compliance_status"] == ComplianceStatus.COMPLIANT, (
                "the limit comparison is inclusive"
            )
        else:
            assert log["compliance_status"] == ComplianceStatus.LATE


# ─── PI event and corrective action ───────────────────────


def assert_pi_event(event: Dict[str, Any], center_id: Optional[str] = None) -> None:
    """Assert the shape of a PI event."""
    _assert_audited(event, "PIEvent")
    if center_id is not None:
        assert event["center_id"] == center_id
    assert event["event_type"] in (
        "UNDER_TRIAGE",
        "DELAYED_SURGEON",
        "DEFICIENCY_ESCALATION",
        "MORTALITY_REVIEW",
        "TRANSFER_DELAY",
    )
    assert event["severity"] in ("HIGH", "MEDIUM", "LOW")
    assert event["origin"] in (PiOrigin.MANUAL, PiOrigin.SYSTEM_AUTO)
    assert event["status"] in (
        PiStatus.IDENTIFIED,
        PiStatus.UNDER_REVIEW,
        PiStatus.ACTION_PLANNED,
        PiStatus.LOOP_CLOSED,
        PiStatus.REOPENED,
    )
    assert_timestamp_format(event["opened_at"])
    assert_timestamp_format(event["loop_closure_due_at"])
    assert isinstance(event["review_round"], int) and event["review_round"] >= 1
    assert isinstance(event["corrective_action_count"], int)
    assert isinstance(event["verified_action_count"], int)
    assert event["verified_action_count"] <= event["corrective_action_count"]
    if event["status"] != PiStatus.LOOP_CLOSED:
        assert event["closed_at"] is None, (
            "closed_at is null on an event that is not closed"
        )


def assert_corrective_action(
    action: Dict[str, Any], pi_event_id: Optional[str] = None
) -> None:
    """Assert the shape of a corrective action."""
    _assert_audited(action, "CorrectiveAction")
    if pi_event_id is not None:
        assert action["pi_event_id"] == pi_event_id
    assert action["action_type"] in (
        "EDUCATION",
        "PROTOCOL_CHANGE",
        "CREDENTIAL_ACTION",
        "EQUIPMENT",
    )
    assert isinstance(action["owner_user_id"], str) and action["owner_user_id"]
    assert_timestamp_format(action["due_at"])
    assert action["completion_status"] in (
        CompletionStatus.OPEN,
        CompletionStatus.COMPLETED,
        CompletionStatus.VERIFIED,
    )
    if action["completion_status"] == CompletionStatus.OPEN:
        assert action["completed_at"] is None
        assert action["verified_at"] is None
        assert action["verified_by_user_id"] is None
    if action["completion_status"] == CompletionStatus.VERIFIED:
        assert_timestamp_format(action["verified_at"])
        assert isinstance(action["verified_by_user_id"], str)


# ─── Verification cycle, deficiency and booking ───────────


def assert_verification_cycle(
    cycle: Dict[str, Any], center_id: Optional[str] = None
) -> None:
    """Assert the shape of a verification cycle."""
    _assert_audited(cycle, "VerificationCycle")
    if center_id is not None:
        assert cycle["center_id"] == center_id
    assert cycle["cycle_type"] in ("NATIONAL_VERIFICATION", "STATE_DESIGNATION")
    assert_timestamp_format(cycle["site_visit_date"])
    assert cycle["status"] in (
        CycleStatus.PREP,
        CycleStatus.PREP_BLOCKED,
        CycleStatus.SUBMITTED,
        CycleStatus.SITE_VISIT_SCHEDULED,
        CycleStatus.UNDER_REVIEW,
        CycleStatus.VERIFIED,
        CycleStatus.CONTINGENCY,
        CycleStatus.DENIED,
    )
    assert isinstance(cycle["readiness_score"], (int, float))
    assert cycle["readiness_score"] >= 0.00, "readiness_score floors at 0.00"
    for counter in ("open_type_i_count", "open_type_ii_count", "open_type_iii_count"):
        assert isinstance(cycle[counter], int) and cycle[counter] >= 0


def assert_criteria_deficiency(
    deficiency: Dict[str, Any], cycle_id: Optional[str] = None
) -> None:
    """Assert the shape of a criteria deficiency."""
    _assert_audited(deficiency, "CriteriaDeficiency")
    if cycle_id is not None:
        assert deficiency["verification_cycle_id"] == cycle_id
    assert isinstance(deficiency["criterion_code"], str) and deficiency["criterion_code"]
    assert deficiency["deficiency_class"] in (
        DeficiencyClass.TYPE_I_CRITICAL,
        DeficiencyClass.TYPE_II_MAJOR,
        DeficiencyClass.TYPE_III_MINOR,
    )
    assert deficiency["status"] in (
        DeficiencyStatus.OPEN,
        DeficiencyStatus.REMEDIATION_SUBMITTED,
        DeficiencyStatus.ESCALATED,
        DeficiencyStatus.CLOSED,
    )
    assert_timestamp_format(deficiency["remediation_due_at"])
    if deficiency["status"] != DeficiencyStatus.CLOSED:
        assert deficiency["closed_at"] is None


def assert_surveyor_booking(
    booking: Dict[str, Any], cycle_id: Optional[str] = None
) -> None:
    """Assert the shape of a surveyor booking."""
    _assert_audited(booking, "SurveyorBooking")
    if cycle_id is not None:
        assert booking["verification_cycle_id"] == cycle_id
    assert isinstance(booking["surveyor_user_id"], str) and booking["surveyor_user_id"]
    assert_timestamp_format(booking["window_start"])
    assert_timestamp_format(booking["window_end"])
    assert canonical_instant(booking["window_end"]) > canonical_instant(
        booking["window_start"]
    ), "window_end must be strictly later than window_start"
    assert isinstance(booking["travel_buffer_hours"], int)


# ─── Outreach activity and referral agreement ─────────────


def assert_outreach_activity(
    activity: Dict[str, Any], center_id: Optional[str] = None
) -> None:
    """Assert the shape of an outreach activity."""
    _assert_audited(activity, "OutreachActivity")
    if center_id is not None:
        assert activity["center_id"] == center_id
    assert activity["activity_kind"] in (
        "INJURY_PREVENTION",
        "PROFESSIONAL_EDUCATION",
        "COMMUNITY_OUTREACH",
    )
    assert_timestamp_format(activity["event_date"])
    assert isinstance(activity["credit_hours"], (int, float))
    assert activity["credit_hours"] > 0, "credit_hours must be greater than zero"
    assert isinstance(activity["audience_count"], int) and activity["audience_count"] >= 0
    assert_quarter_hour_multiple(activity["weighted_credit_hours"])
    assert activity["verified_status"] in (
        VerifiedStatus.LOGGED,
        VerifiedStatus.VERIFIED,
        VerifiedStatus.REJECTED,
    )
    if activity["verified_status"] == VerifiedStatus.LOGGED:
        assert activity["reviewed_by_user_id"] is None


def assert_referral_agreement(agreement: Dict[str, Any]) -> None:
    """Assert the shape of a referral agreement."""
    _assert_audited(agreement, "ReferralAgreement")
    assert is_valid_uuid(agreement["referring_center_id"])
    assert is_valid_uuid(agreement["receiving_center_id"])
    assert_timestamp_format(agreement["effective_from"])
    assert_timestamp_format(agreement["effective_to"])
    assert canonical_instant(agreement["effective_to"]) > canonical_instant(
        agreement["effective_from"]
    ), "effective_to must be strictly later than effective_from"
    assert isinstance(agreement["guaranteed_acceptance_minutes"], int)
    assert 1 <= agreement["guaranteed_acceptance_minutes"] <= 720
    assert agreement["agreement_status"] in (
        AgreementStatus.DRAFT,
        AgreementStatus.ACTIVE,
        AgreementStatus.TERMINATED,
    )
    if agreement["agreement_status"] == AgreementStatus.DRAFT:
        assert agreement["activated_at"] is None
        assert agreement["terminated_at"] is None


# ─── Computed reads ───────────────────────────────────────


def assert_triage_rates_read(
    read: Dict[str, Any],
    variant: Optional[str],
    denominator: int,
    under_numerator: int,
    over_numerator: int,
    under_rate: float,
    over_rate: float,
) -> None:
    """Assert every field of the center's computed triage-rate read.

    Passing ``variant=None`` skips the echo comparison, which is what a read that
    supplied no explicit variant selector wants.
    """
    if variant is not None:
        assert read["variant"] == variant, (
            f"variant: expected {variant}, got {read['variant']}"
        )
    assert read["denominator_case_count"] == denominator, (
        f"denominator_case_count: expected {denominator}, "
        f"got {read['denominator_case_count']}"
    )
    assert read["under_triage_numerator"] == under_numerator, (
        f"under_triage_numerator: expected {under_numerator}, "
        f"got {read['under_triage_numerator']}"
    )
    assert read["over_triage_numerator"] == over_numerator, (
        f"over_triage_numerator: expected {over_numerator}, "
        f"got {read['over_triage_numerator']}"
    )
    assert_decimal(read["under_triage_rate_pct"], under_rate, "under_triage_rate_pct")
    assert_decimal(read["over_triage_rate_pct"], over_rate, "over_triage_rate_pct")


def assert_readiness_read(
    read: Dict[str, Any],
    variant: Optional[str],
    deficiency_penalty: float,
    outreach_penalty: float,
    pi_penalty: float,
    readiness_score: float,
    submit_eligible: bool,
    base_score: float = 100.00,
) -> None:
    """Assert every field of the cycle's computed readiness read.

    Passing ``variant=None`` skips the echo comparison, which is what a read that
    supplied no explicit variant selector wants.
    """
    if variant is not None:
        assert read["variant"] == variant, (
            f"variant: expected {variant}, got {read['variant']}"
        )
    assert_decimal(read["base_score"], base_score, "base_score")
    assert_decimal(read["deficiency_penalty"], deficiency_penalty, "deficiency_penalty")
    assert_decimal(read["outreach_penalty"], outreach_penalty, "outreach_penalty")
    assert_decimal(read["pi_penalty"], pi_penalty, "pi_penalty")
    assert_decimal(read["readiness_score"], readiness_score, "readiness_score")
    assert read["submit_eligible"] is submit_eligible, (
        f"submit_eligible: expected {submit_eligible}, got {read['submit_eligible']}"
    )
