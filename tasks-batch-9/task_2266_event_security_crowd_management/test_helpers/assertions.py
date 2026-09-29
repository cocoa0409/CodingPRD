"""Domain assertions for the Event Security & Crowd Management API.

Two families live here:

  * ``assert_<entity>(payload)`` — structural checks that a response body
    carries every declared field with a plausible type, including the common
    envelope fields (and their deliberate absence on the immutable
    DensityReading).
  * invariant checkers — the conserved quantities the contract promises hold
    after every request (money ledger, labour-hours ledger, coverage ratio).
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import MONEY_TOLERANCE
from .types import (
    COVERAGE_SUMMARY_KEYS,
    AssessmentStatus,
    AssignmentStatus,
    DensityLevel,
    DutyStatus,
    EventStatus,
    GatePosture,
    IncidentStatus,
    IngressStatus,
    LaneStatus,
    PayBasis,
    PlanStatus,
    PostStatus,
    PostType,
    ReadinessPosture,
    ReviewStatus,
    RiskTier,
    Severity,
    SubcontractorStatus,
    VerificationStatus,
)

# ─── Generic structural helpers ───────────────────────


def assert_common_fields(payload: Dict[str, Any]) -> None:
    """Every mutable entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(payload["id"]), f"id is not a UUID: {payload.get('id')!r}"
    assert is_iso8601_timestamp(payload["created_at"]), (
        f"created_at is not ISO 8601: {payload.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(payload["updated_at"]), (
        f"updated_at is not ISO 8601: {payload.get('updated_at')!r}"
    )
    assert isinstance(payload["version"], int), "version must be an integer"
    assert payload["version"] >= 1, "version starts at 1"


def assert_fields_present(payload: Dict[str, Any], field_names: List[str]) -> None:
    missing = [name for name in field_names if name not in payload]
    assert not missing, f"missing declared fields: {missing}"


def assert_enum(value: Any, allowed: List[str], label: str) -> None:
    assert value in allowed, f"{label} must be one of {allowed}, got {value!r}"


def assert_money(actual: Any, expected: int, label: str = "cents") -> None:
    assert isinstance(actual, int), f"{label} must be integer cents, got {actual!r}"
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def assert_decimal(actual: Any, expected: float, label: str = "value") -> None:
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_three_decimals(actual: Any, expected: float, label: str = "density") -> None:
    assert actual == pytest.approx(expected, abs=0.0005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_four_decimals(actual: Any, expected: float, label: str = "rate") -> None:
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Per-entity structural assertions ─────────────────

VENUE_FIELDS = [
    "name",
    "gross_capacity",
    "door_count",
    "egress_capacity_per_minute",
    "perimeter_length_m",
    "alcohol_licensed",
    "prior_incident_rate",
    "status",
]


def assert_venue(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, VENUE_FIELDS)
    assert isinstance(payload["alcohol_licensed"], bool)
    assert_enum(payload["status"], ["ACTIVE", "UNDER_RENOVATION"], "Venue.status")


ZONE_FIELDS = [
    "venue_id",
    "zone_code",
    "zone_type",
    "floor_area_sqm",
    "posted_capacity",
    "exit_units",
    "post_slot_capacity",
    "is_ingress_zone",
    "max_safe_occupancy",
]


def assert_zone(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, ZONE_FIELDS)
    assert is_valid_uuid(payload["venue_id"])
    assert isinstance(payload["is_ingress_zone"], bool)
    assert isinstance(payload["max_safe_occupancy"], int)


EVENT_FIELDS = [
    "venue_id",
    "event_name",
    "event_type",
    "doors_open_at",
    "event_start_at",
    "event_end_at",
    "expected_attendance",
    "ticketed_attendance",
    "alcohol_served",
    "vip_present",
    "status",
    "ingress_status",
    "gate_posture",
    "open_critical_incident_count",
]

EVENT_STATUSES = [
    EventStatus.PLANNING,
    EventStatus.RISK_ASSESSED,
    EventStatus.STAFFED,
    EventStatus.BRIEFED,
    EventStatus.DOORS_OPEN,
    EventStatus.IN_PROGRESS,
    EventStatus.SUSPENDED,
    EventStatus.CLOSED,
    EventStatus.DEBRIEFED,
]


def assert_security_event(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, EVENT_FIELDS)
    assert is_valid_uuid(payload["venue_id"])
    for stamp in ("doors_open_at", "event_start_at", "event_end_at"):
        assert is_iso8601_timestamp(payload[stamp]), f"{stamp} is not ISO 8601"
    assert_enum(payload["status"], EVENT_STATUSES, "SecurityEvent.status")
    assert_enum(
        payload["ingress_status"],
        [IngressStatus.NORMAL, IngressStatus.METERED, IngressStatus.HOLD],
        "SecurityEvent.ingress_status",
    )
    assert_enum(
        payload["gate_posture"],
        [GatePosture.OPEN, GatePosture.RESTRICTED, GatePosture.FROZEN],
        "SecurityEvent.gate_posture",
    )
    assert isinstance(payload["open_critical_incident_count"], int)


ASSESSMENT_FIELDS = [
    "event_id",
    "revision_number",
    "threat_level_input",
    "protest_likelihood",
    "crowd_profile",
    "ingress_door_count",
    "layout_complexity_score",
    "history_incident_rate",
    "attendance_basis",
    "score_basis_attendance",
    "composite_threat_score",
    "risk_tier",
    "required_line_guards",
    "required_perimeter_guards",
    "required_ingress_guards",
    "required_floor_guards",
    "required_exit_guards",
    "required_supervisors",
    "required_total_staff",
    "required_screening_lanes",
    "minimum_staffing_cost_floor_cents",
    "status",
    "submitted_by_user_id",
    "approved_by_user_id",
    "rejection_reason",
]


def assert_risk_assessment(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, ASSESSMENT_FIELDS)
    assert is_valid_uuid(payload["event_id"])
    assert_enum(
        payload["status"],
        [
            AssessmentStatus.DRAFT,
            AssessmentStatus.SUBMITTED,
            AssessmentStatus.APPROVED,
            AssessmentStatus.REJECTED,
            AssessmentStatus.SUPERSEDED,
        ],
        "RiskAssessment.status",
    )
    if payload["risk_tier"] is not None:
        assert_enum(
            payload["risk_tier"],
            [RiskTier.T1, RiskTier.T2, RiskTier.T3, RiskTier.T4],
            "RiskAssessment.risk_tier",
        )


PLAN_FIELDS = [
    "event_id",
    "risk_assessment_id",
    "pinned_risk_assessment_version",
    "supersedes_plan_id",
    "budget_cents",
    "committed_cost_cents",
    "billed_cost_cents",
    "budget_remaining_cents",
    "committed_guard_hours",
    "required_total_staff",
    "filled_total_staff",
    "coverage_ratio",
    "understaffed_post_count",
    "readiness_posture",
    "status",
    "is_current",
]


def assert_staffing_plan(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, PLAN_FIELDS)
    assert is_valid_uuid(payload["event_id"])
    assert isinstance(payload["is_current"], bool)
    assert_enum(
        payload["status"],
        [
            PlanStatus.DRAFT,
            PlanStatus.PUBLISHED,
            PlanStatus.ACTIVATED,
            PlanStatus.LOCKED,
            PlanStatus.CLOSED,
            PlanStatus.SUPERSEDED,
        ],
        "StaffingPlan.status",
    )
    assert_enum(
        payload["readiness_posture"],
        [ReadinessPosture.READY, ReadinessPosture.AT_RISK, ReadinessPosture.BLOCKED],
        "StaffingPlan.readiness_posture",
    )
    assert_budget_conserved(payload)


POST_FIELDS = [
    "staffing_plan_id",
    "zone_id",
    "reports_to_post_id",
    "lane_id",
    "post_code",
    "post_type",
    "required_guard_count",
    "min_credential_level",
    "window_start",
    "window_end",
    "filled_guard_count",
    "status",
]


def assert_post(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, POST_FIELDS)
    assert is_valid_uuid(payload["staffing_plan_id"])
    assert is_valid_uuid(payload["zone_id"])
    assert_enum(
        payload["post_type"],
        [
            PostType.PERIMETER,
            PostType.INGRESS_SCREENING,
            PostType.FLOOR,
            PostType.EMERGENCY_EXIT,
            PostType.SUPERVISOR,
        ],
        "Post.post_type",
    )
    assert_enum(
        payload["status"],
        [
            PostStatus.OPEN,
            PostStatus.PARTIALLY_STAFFED,
            PostStatus.FILLED,
            PostStatus.UNDERSTAFFED,
            PostStatus.CLOSED,
        ],
        "Post.status",
    )


SUBCONTRACTOR_FIELDS = [
    "company_name",
    "license_number",
    "insurance_expires_on",
    "markup_pct",
    "status",
    "verified_guard_count",
]


def assert_subcontractor(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, SUBCONTRACTOR_FIELDS)
    assert_enum(
        payload["status"],
        [
            SubcontractorStatus.PENDING,
            SubcontractorStatus.APPROVED,
            SubcontractorStatus.SUSPENDED,
            SubcontractorStatus.TERMINATED,
        ],
        "Subcontractor.status",
    )


GUARD_FIELDS = [
    "full_name",
    "employment_type",
    "subcontractor_id",
    "credential_level",
    "license_number",
    "credential_expires_on",
    "base_hourly_rate_cents",
    "verification_status",
    "verified_at",
    "is_supervisor_qualified",
]


def assert_guard(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, GUARD_FIELDS)
    assert_enum(payload["employment_type"], ["EMPLOYEE", "SUBCONTRACTED"], "Guard.employment_type")
    assert_enum(
        payload["verification_status"],
        [
            VerificationStatus.UNVERIFIED,
            VerificationStatus.PENDING_REVIEW,
            VerificationStatus.VERIFIED,
            VerificationStatus.REJECTED,
            VerificationStatus.EXPIRED,
            VerificationStatus.DISQUALIFIED,
        ],
        "Guard.verification_status",
    )
    assert isinstance(payload["is_supervisor_qualified"], bool)


ASSIGNMENT_FIELDS = [
    "post_id",
    "guard_id",
    "window_start",
    "window_end",
    "assignment_status",
    "duty_status",
    "scheduled_hours",
    "night_differential_applies",
    "pay_basis",
    "line_cost_cents",
    "billed_hours",
    "billed_cost_cents",
    "radio_channel",
    "training_module_code",
    "briefed_at",
    "check_in_at",
    "relieved_at",
    "cancellation_reason",
]


def assert_post_assignment(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, ASSIGNMENT_FIELDS)
    assert is_valid_uuid(payload["post_id"])
    assert is_valid_uuid(payload["guard_id"])
    assert_enum(
        payload["assignment_status"],
        [
            AssignmentStatus.TENTATIVE,
            AssignmentStatus.CONFIRMED,
            AssignmentStatus.CANCELLED,
            AssignmentStatus.VOIDED,
            AssignmentStatus.COMPLETED,
        ],
        "PostAssignment.assignment_status",
    )
    assert_enum(
        payload["duty_status"],
        [
            DutyStatus.PENDING_BRIEF,
            DutyStatus.BRIEFED,
            DutyStatus.ON_POST,
            DutyStatus.NO_SHOW,
            DutyStatus.RELIEVED,
        ],
        "PostAssignment.duty_status",
    )
    assert_enum(
        payload["pay_basis"],
        [PayBasis.EMPLOYEE_STRAIGHT, PayBasis.EMPLOYEE_OT, PayBasis.SUBCONTRACT],
        "PostAssignment.pay_basis",
    )
    assert isinstance(payload["night_differential_applies"], bool)


LANE_FIELDS = [
    "event_id",
    "zone_id",
    "lane_type",
    "nominal_throughput_pph",
    "operator_capacity",
    "open_from",
    "open_to",
    "status",
    "assigned_operator_count",
    "effective_throughput_pph",
]


def assert_screening_lane(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, LANE_FIELDS)
    assert_enum(
        payload["status"],
        [LaneStatus.PLANNED, LaneStatus.OPEN, LaneStatus.HOLD, LaneStatus.CLOSED],
        "ScreeningLane.status",
    )
    assert isinstance(payload["effective_throughput_pph"], int)


READING_FIELDS = [
    "event_id",
    "zone_id",
    "observed_at",
    "observed_occupancy",
    "reported_by_user_id",
    "density_persons_per_sqm",
    "occupancy_ratio",
    "rolling_mean_persons_per_sqm",
    "instantaneous_level",
    "rolling_level",
    "effective_level",
]

DENSITY_LEVELS = [
    DensityLevel.GREEN,
    DensityLevel.AMBER,
    DensityLevel.RED,
    DensityLevel.CRITICAL,
]


def assert_density_reading(payload: Dict[str, Any]) -> None:
    """Immutable observation: id and created_at only, no updated_at, no version."""
    assert is_valid_uuid(payload["id"]), f"id is not a UUID: {payload.get('id')!r}"
    assert is_iso8601_timestamp(payload["created_at"]), "created_at is not ISO 8601"
    assert "updated_at" not in payload, "DensityReading must not carry updated_at"
    assert "version" not in payload, "DensityReading must not carry version"
    assert_fields_present(payload, READING_FIELDS)
    for level_field in ("instantaneous_level", "rolling_level", "effective_level"):
        assert_enum(payload[level_field], DENSITY_LEVELS, f"DensityReading.{level_field}")


INCIDENT_FIELDS = [
    "event_id",
    "zone_id",
    "category",
    "severity",
    "severity_at_report",
    "description",
    "reported_by_user_id",
    "reported_at",
    "triaged_at",
    "resolved_at",
    "response_minutes",
    "sla_breached",
    "handoff_agency_ref",
    "ejection_patron_ref",
    "resolution_note",
    "status",
]

SEVERITIES = [Severity.MINOR, Severity.MODERATE, Severity.SEVERE, Severity.CRITICAL]


def assert_incident(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, INCIDENT_FIELDS)
    assert_enum(payload["severity"], SEVERITIES, "Incident.severity")
    assert_enum(payload["severity_at_report"], SEVERITIES, "Incident.severity_at_report")
    assert_enum(
        payload["status"],
        [
            IncidentStatus.REPORTED,
            IncidentStatus.TRIAGED,
            IncidentStatus.MEDICAL_HANDOFF,
            IncidentStatus.EJECTION_IN_PROGRESS,
            IncidentStatus.LE_HANDOFF,
            IncidentStatus.RESOLVED,
            IncidentStatus.CLOSED_UNFOUNDED,
        ],
        "Incident.status",
    )
    assert isinstance(payload["sla_breached"], bool)


REVIEW_FIELDS = [
    "event_id",
    "narrative",
    "corrective_action_count",
    "authored_by_user_id",
    "finalized_by_user_id",
    "return_reason",
    "total_incident_count",
    "sla_breach_count",
    "peak_density_level",
    "no_show_rate",
    "coverage_shortfall_minutes",
    "status",
]


def assert_after_action_review(payload: Dict[str, Any]) -> None:
    assert_common_fields(payload)
    assert_fields_present(payload, REVIEW_FIELDS)
    assert_enum(
        payload["status"],
        [
            ReviewStatus.DRAFT,
            ReviewStatus.SUBMITTED,
            ReviewStatus.RETURNED,
            ReviewStatus.FINALIZED,
        ],
        "AfterActionReview.status",
    )
    assert_enum(payload["peak_density_level"], DENSITY_LEVELS, "AfterActionReview.peak_density_level")


def assert_coverage_summary_shape(payload: Dict[str, Any]) -> None:
    """The coverage read is an inline projection of exactly nine keys."""
    assert_fields_present(payload, COVERAGE_SUMMARY_KEYS)
    extra = sorted(set(payload) - set(COVERAGE_SUMMARY_KEYS))
    assert not extra, f"coverage summary carries undeclared keys: {extra}"
    assert isinstance(payload["supervisor_coverage_ok"], bool)


# ─── Invariant checkers ───────────────────────────────


def assert_budget_conserved(plan: Dict[str, Any]) -> None:
    """budget_remaining_cents + committed_cost_cents == budget_cents, always.

    The coverage-summary projection carries the nine derived figures only, and
    ``budget_cents`` is not among them, so the identity is checked whenever the
    authorising total is in the payload at hand.
    """
    if "budget_cents" not in plan:
        return
    total = plan["committed_cost_cents"] + plan["budget_remaining_cents"]
    assert total == plan["budget_cents"], (
        "money is not conserved: committed "
        f"{plan['committed_cost_cents']} + remaining {plan['budget_remaining_cents']} "
        f"!= budget {plan['budget_cents']}"
    )


def assert_ledger(
    plan: Dict[str, Any],
    committed_cost_cents: int,
    committed_guard_hours: float,
    budget_remaining_cents: Optional[int] = None,
) -> None:
    """Both conserved quantities at once: money and labour hours."""
    assert_money(plan["committed_cost_cents"], committed_cost_cents, "committed_cost_cents")
    assert_decimal(plan["committed_guard_hours"], committed_guard_hours, "committed_guard_hours")
    if budget_remaining_cents is not None:
        assert_money(plan["budget_remaining_cents"], budget_remaining_cents, "budget_remaining_cents")
    assert_budget_conserved(plan)


def assert_coverage(
    plan: Dict[str, Any],
    required_total_staff: int,
    filled_total_staff: int,
    coverage_ratio: float,
    readiness_posture: str,
) -> None:
    assert plan["required_total_staff"] == required_total_staff, (
        f"required_total_staff: expected {required_total_staff}, got {plan['required_total_staff']}"
    )
    assert plan["filled_total_staff"] == filled_total_staff, (
        f"filled_total_staff: expected {filled_total_staff}, got {plan['filled_total_staff']}"
    )
    assert_decimal(plan["coverage_ratio"], coverage_ratio, "coverage_ratio")
    assert plan["readiness_posture"] == readiness_posture, (
        f"readiness_posture: expected {readiness_posture}, got {plan['readiness_posture']}"
    )


def assert_post_fill(post: Dict[str, Any], filled_guard_count: int, status: str) -> None:
    assert post["filled_guard_count"] == filled_guard_count, (
        f"filled_guard_count: expected {filled_guard_count}, got {post['filled_guard_count']}"
    )
    assert post["status"] == status, f"Post.status: expected {status}, got {post['status']}"


def assert_assignment_state(
    assignment: Dict[str, Any], assignment_status: str, duty_status: str
) -> None:
    """The two dimensions of the roster row move independently."""
    assert assignment["assignment_status"] == assignment_status, (
        f"assignment_status: expected {assignment_status}, got {assignment['assignment_status']}"
    )
    assert assignment["duty_status"] == duty_status, (
        f"duty_status: expected {duty_status}, got {assignment['duty_status']}"
    )


def assert_assignment_cost(
    assignment: Dict[str, Any], scheduled_hours: float, line_cost_cents: int, pay_basis: str
) -> None:
    assert_decimal(assignment["scheduled_hours"], scheduled_hours, "scheduled_hours")
    assert_money(assignment["line_cost_cents"], line_cost_cents, "line_cost_cents")
    assert assignment["pay_basis"] == pay_basis, (
        f"pay_basis: expected {pay_basis}, got {assignment['pay_basis']}"
    )


def assert_gate(event: Dict[str, Any], gate_posture: str, ingress_status: Optional[str] = None) -> None:
    assert event["gate_posture"] == gate_posture, (
        f"gate_posture: expected {gate_posture}, got {event['gate_posture']}"
    )
    if ingress_status is not None:
        assert event["ingress_status"] == ingress_status, (
            f"ingress_status: expected {ingress_status}, got {event['ingress_status']}"
        )


def assert_error_envelope_meta(response) -> None:
    """An error response still carries the standard meta block."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert isinstance(meta.get("api_request_timestamp"), str), (
        "meta.api_request_timestamp must be a string"
    )
    assert body["data"]["message"].strip(), "data.message must be non-empty"
