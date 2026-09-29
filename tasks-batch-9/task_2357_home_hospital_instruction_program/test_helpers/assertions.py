"""Entity assertions and domain invariant checkers.

These check only what the PRD states about each resource: the id shape, the
system-managed timestamp/version fields it declares for that resource, and the
enum membership of its status fields.
"""

from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssignmentRole,
    AssignmentStatus,
    AttendanceCode,
    CaseFundingStatus,
    CaseServiceStatus,
    CertificationStatus,
    DeliveryMode,
    EntitlementRuleStatus,
    EnrollmentStatus,
    ExtensionRequestStatus,
    GradeBand,
    PacingAckStatus,
    SafetyClearance,
    SafetyReviewStatus,
    ScoringVariant,
    SessionStatus,
    SpecialEdStatus,
    SpedContinuationStatus,
    TeacherClearanceStatus,
    TransitionPlanStatus,
)


# ---------------------------------------------------------------------------
# Rounding helpers (PRD §2.8)
# ---------------------------------------------------------------------------


def round_half_up(value) -> int:
    """Round to a whole number half up — exactly one half rounds away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_to_five(value) -> int:
    """Round half up to the nearest multiple of five minutes."""
    return round_half_up(Decimal(str(value)) / Decimal("5")) * 5


def round_ratio(value) -> float:
    """Round half up to exactly two decimal places."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Shared field checks
# ---------------------------------------------------------------------------


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_versioned_resource(data: dict, label: str = "resource") -> None:
    """`id` + `created_at` + `updated_at` + `version` (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version must start at 1"


def assert_append_only_resource(data: dict, label: str = "ledger entry") -> None:
    """`id` + `created_at` only — no `updated_at`, no `version` (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_student(data: dict) -> None:
    assert_versioned_resource(data, "student")
    assert isinstance(data["student_number"], str) and 1 <= len(
        data["student_number"]
    ) <= 32
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["grade_level"], int) and 0 <= data["grade_level"] <= 12
    assert data["grade_band"] in _values(GradeBand)
    assert isinstance(data["campus_code"], str) and data["campus_code"]
    assert data["special_ed_status"] in _values(SpecialEdStatus)
    assert isinstance(data["iep_service_minutes_weekly"], int)
    assert data["iep_service_minutes_weekly"] >= 0
    assert data["enrollment_status"] in _values(EnrollmentStatus)


def assert_teacher(data: dict) -> None:
    assert_versioned_resource(data, "teacher")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert isinstance(data["credential_areas"], list) and data["credential_areas"]
    assert isinstance(data["grade_bands"], list) and data["grade_bands"]
    assert all(band in _values(GradeBand) for band in data["grade_bands"])
    assert isinstance(data["max_weekly_caseload_minutes"], int)
    assert data["max_weekly_caseload_minutes"] > 0
    assert data["safety_clearance_status"] in _values(TeacherClearanceStatus)
    assert isinstance(data["home_visit_eligible"], bool)
    assert isinstance(data["committed_weekly_minutes"], int)
    assert isinstance(data["over_cap"], bool)
    assert data["over_cap"] == (
        data["committed_weekly_minutes"] > data["max_weekly_caseload_minutes"]
    ), "over_cap must be true only when committed minutes strictly exceed the ceiling"


def assert_entitlement_rule(data: dict) -> None:
    assert_versioned_resource(data, "entitlement rule")
    assert data["grade_band"] in _values(GradeBand)
    assert data["delivery_mode"] in _values(DeliveryMode)
    assert data["base_weekly_minutes"] > 0
    assert data["cap_weekly_minutes"] >= data["base_weekly_minutes"]
    assert data["min_session_minutes"] > 0
    assert data["max_session_minutes"] >= data["min_session_minutes"]
    assert data["max_daily_minutes"] >= data["max_session_minutes"]
    assert data["min_gap_minutes"] >= 0
    assert data["travel_buffer_minutes"] >= 0
    assert data["status"] in _values(EntitlementRuleStatus)


def assert_homebound_case(data: dict) -> None:
    assert_versioned_resource(data, "case")
    assert is_valid_uuid(data["student_id"])
    assert data["delivery_mode"] in _values(DeliveryMode)
    assert data["service_status"] in _values(CaseServiceStatus)
    assert data["funding_status"] in _values(CaseFundingStatus)
    assert isinstance(data["weekly_entitled_minutes"], int)
    assert isinstance(data["certification_count"], int)
    assert isinstance(data["extension_count"], int)
    assert isinstance(data["reported_apportionment_minutes"], int)
    assert isinstance(data["service_gap_minutes"], int)
    assert data["service_gap_minutes"] >= 0
    assert isinstance(data["makeup_obligation_minutes"], int)
    assert isinstance(data["escort_required"], bool)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_physician_certification(data: dict) -> None:
    assert_versioned_resource(data, "certification")
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["physician_npi"], str) and len(data["physician_npi"]) == 10
    assert data["physician_npi"].isdigit()
    assert data["status"] in _values(CertificationStatus)
    assert isinstance(data["is_current"], bool)
    assert data["expected_absence_days"] >= 1
    assert data["certified_end_date"] >= data["certified_start_date"]
    assert isinstance(data["submitted_by_user_id"], str)


def assert_teacher_assignment(data: dict) -> None:
    assert_versioned_resource(data, "assignment")
    assert is_valid_uuid(data["case_id"])
    assert data["role"] in _values(AssignmentRole)
    assert data["status"] in _values(AssignmentStatus)
    assert isinstance(data["weekly_committed_minutes"], int)
    assert data["weekly_committed_minutes"] >= 0
    if data["status"] in ("PROPOSED", "DECLINED", "RELEASED"):
        assert data["weekly_committed_minutes"] == 0, (
            "only ACTIVE assignments participate in the allocation; "
            f"{data['status']} must hold weekly_committed_minutes 0"
        )


def assert_home_visit_safety_review(data: dict) -> None:
    assert_versioned_resource(data, "safety review")
    assert is_valid_uuid(data["case_id"])
    assert data["scoring_variant"] in _values(ScoringVariant)
    assert data["status"] in _values(SafetyReviewStatus)
    assert data["clearance"] in _values(SafetyClearance)
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 100
    assert isinstance(data["hazard_findings"], list)
    assert len(set(data["hazard_findings"])) == len(
        data["hazard_findings"]
    ), "hazard_findings must not contain duplicates"
    assert isinstance(data["escort_available"], bool)
    if data["status"] == "DRAFT":
        assert data["clearance"] == "PENDING", (
            "a DRAFT review's clearance reads PENDING regardless of the score"
        )


def assert_instruction_session(data: dict) -> None:
    assert_versioned_resource(data, "session")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["assignment_id"])
    assert data["status"] in _values(SessionStatus)
    assert data["delivery_mode"] in ("IN_HOME", "VIRTUAL_SYNC")
    assert isinstance(data["scheduled_minutes"], int) and data["scheduled_minutes"] > 0
    assert isinstance(data["credited_minutes"], int)
    assert data["service_date"] == data["scheduled_start"][:10], (
        "service_date is the UTC calendar date of scheduled_start"
    )


def assert_attendance_ledger_entry(data: dict) -> None:
    assert_append_only_resource(data, "attendance entry")
    assert is_valid_uuid(data["case_id"])
    assert data["attendance_code"] in _values(AttendanceCode)
    assert isinstance(data["apportionment_minutes"], int)
    assert isinstance(data["recorded_by_user_id"], str)
    assert data["delivery_mode"] in ("IN_HOME", "VIRTUAL_SYNC")


def assert_extension_request(data: dict) -> None:
    assert_versioned_resource(data, "extension request")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["certification_id"])
    assert data["status"] in _values(ExtensionRequestStatus)
    assert 1 <= data["requested_additional_days"] <= 90
    assert isinstance(data["resubmit_count"], int) and 0 <= data["resubmit_count"] <= 2
    assert isinstance(data["submitted_by_user_id"], str)


def assert_transition_plan(data: dict) -> None:
    assert_versioned_resource(data, "transition plan")
    assert is_valid_uuid(data["case_id"])
    assert data["status"] in _values(TransitionPlanStatus)
    assert isinstance(data["ramp_weeks"], int) and 0 <= data["ramp_weeks"] <= 8
    assert isinstance(data["required_ack_count"], int)
    assert isinstance(data["classroom_ack_count"], int)
    assert data["classroom_ack_count"] <= data["required_ack_count"]


def assert_curriculum_pacing_sync(data: dict) -> None:
    assert_versioned_resource(data, "pacing sync")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["classroom_teacher_id"])
    assert data["ack_status"] in _values(PacingAckStatus)
    if data["ack_status"] != "ACKED":
        assert data.get("acked_at") is None, "acked_at is stamped only on acknowledge"


def assert_sped_service_log(data: dict) -> None:
    assert_versioned_resource(data, "special-education service log")
    assert is_valid_uuid(data["case_id"])
    assert data["continuation_status"] in _values(SpedContinuationStatus)
    assert data["required_weekly_minutes"] > 0
    assert isinstance(data["delivered_cumulative_minutes"], int)
    assert data["delivered_cumulative_minutes"] >= 0
    assert isinstance(data["compensatory_minutes_owed"], int)
    assert data["compensatory_minutes_owed"] >= 0


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_allocation_sums_to_entitlement(case: dict, assignments: list) -> None:
    """The sum of `weekly_committed_minutes` across ACTIVE assignments equals the
    case's `weekly_entitled_minutes` exactly (PRD §3.4)."""
    active = [a for a in assignments if a["status"] == "ACTIVE"]
    has_primary = any(a["role"] == "PRIMARY" for a in active)
    total = sum(a["weekly_committed_minutes"] for a in active)
    if has_primary:
        assert total == case["weekly_entitled_minutes"], (
            f"active allocation sums to {total}, expected the case's "
            f"weekly_entitled_minutes {case['weekly_entitled_minutes']}"
        )
    else:
        assert total == 0, (
            "with no active primary assignment the allocation writes nothing"
        )


def assert_ledger_sums_to(entries: list, expected: int) -> None:
    """Signed sum of `apportionment_minutes` over the supplied ledger rows."""
    total = sum(entry["apportionment_minutes"] for entry in entries)
    assert total == expected, (
        f"signed attendance ledger sum is {total}, expected {expected}"
    )


def assert_case_dimensions(case: dict, service_status: str, funding_status: str) -> None:
    """The two parallel status dimensions of a case (PRD §2.9)."""
    assert case["service_status"] == service_status, (
        f"service_status is {case['service_status']}, expected {service_status}"
    )
    assert case["funding_status"] == funding_status, (
        f"funding_status is {case['funding_status']}, expected {funding_status}"
    )


def assert_teacher_committed(teacher: dict, expected_minutes: int) -> None:
    assert teacher["committed_weekly_minutes"] == expected_minutes, (
        f"teacher committed_weekly_minutes is {teacher['committed_weekly_minutes']}, "
        f"expected {expected_minutes}"
    )
    assert teacher["over_cap"] == (
        expected_minutes > teacher["max_weekly_caseload_minutes"]
    )
