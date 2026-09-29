"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    BenefitContinuationStatus,
    CaseReviewStatus,
    ClaimStatus,
    ComplianceStatus,
    CredentialStatus,
    DirectiveStatus,
    EmploymentStatus,
    JobStatus,
    OversightStatus,
    PlacementStatus,
    ReportStatus,
    RestrictionSetStatus,
    ReviewStatus,
    RiskClass,
    RtwPosture,
    TrainingRecordStatus,
    TrainingStatus,
    VoteStatus,
    WageEntryStatus,
)


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every resource carries a server-minted `id` in UUID form and a `created_at`
    ISO 8601 UTC timestamp; mutable resources additionally carry `updated_at` and
    an integer `version` that starts at 1."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a bare UUID"
    assert not str(data.get("id", "")).count("_"), f"{entity_name}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict, entity_name: str = "record"):
    """ComplianceAudit, WageDifferentialEntry and CaseReviewVote carry only `id`
    and `created_at`; `updated_at` and `version` are absent entirely."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "version" not in data, f"{entity_name} must not expose a version field"
    assert "updated_at" not in data, f"{entity_name} must not expose an updated_at field"


def assert_employee(data: dict):
    assert_common_fields(data, "Employee")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_number"], str) and 1 <= len(data["employee_number"]) <= 32
    assert isinstance(data["department_code"], str)
    assert isinstance(data["pre_injury_weekly_wage_cents"], int)
    assert data["pre_injury_weekly_wage_cents"] >= 1
    assert data["pre_injury_weekly_hours"] > 0 and data["pre_injury_weekly_hours"] <= 80
    assert data["benefit_tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert data["employment_status"] in _values(EmploymentStatus)
    assert isinstance(data["open_claim_count"], int) and data["open_claim_count"] >= 0


def assert_claim(data: dict):
    assert_common_fields(data, "Claim")
    assert is_valid_uuid(data["employee_id"])
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert isinstance(data["adjuster_user_id"], str)
    assert isinstance(data["injury_date"], str)
    assert data["claim_status"] in _values(ClaimStatus)
    assert isinstance(data["max_authorized_weekly_cost_cents"], int)
    assert data["max_authorized_weekly_cost_cents"] >= 0
    assert data["rtw_posture"] in _values(RtwPosture)
    assert isinstance(data["cumulative_transitional_days"], int)
    assert isinstance(data["wage_differential_paid_cents"], int)
    if data.get("active_restriction_set_id") is not None:
        assert is_valid_uuid(data["active_restriction_set_id"])


def assert_treating_provider(data: dict):
    assert_common_fields(data, "TreatingProvider")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10
    assert isinstance(data["specialty"], str)
    assert data["credential_status"] in _values(CredentialStatus)


def assert_restriction_set(data: dict):
    assert_common_fields(data, "RestrictionSet")
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["treating_provider_id"])
    assert data["status"] in _values(RestrictionSetStatus)
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["valid_through"], str)
    assert data["valid_through"] >= data["effective_from"]
    assert data["max_lift_lbs"] >= 0
    assert data["max_continuous_standing_minutes"] >= 0
    assert 0 < data["max_hours_per_day"] <= 12
    assert 0 <= data["keyboard_minutes_per_hour"] <= 60
    assert isinstance(data["overhead_reach_allowed"], bool)
    assert isinstance(data["driving_allowed"], bool)
    assert isinstance(data["clarification_round_count"], int)
    assert isinstance(data["severity_index"], int)
    assert 0 <= data["severity_index"] <= 100, "severity_index is clamped to 0..100"
    assert isinstance(data["active_placement_count"], int)


def assert_supervisor(data: dict):
    assert_common_fields(data, "Supervisor")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["department_code"], str)
    assert data["oversight_status"] in _values(OversightStatus)
    assert isinstance(data["compliance_strike_points"], int)
    assert isinstance(data["strike_forgiveness_points"], int)
    assert isinstance(data["effective_strike_points"], int)
    assert data["effective_strike_points"] == max(
        0, data["compliance_strike_points"] - data["strike_forgiveness_points"]
    ), "effective_strike_points is the greater of zero and (strikes - forgiveness)"
    assert data["training_status"] in _values(TrainingStatus)


def assert_training_record(data: dict):
    assert_common_fields(data, "TrainingRecord")
    assert is_valid_uuid(data["supervisor_id"])
    assert data["curriculum_code"] in ("RTW_CORE", "RESTRICTION_HANDLING", "REINJURY_RESPONSE")
    assert isinstance(data["completed_on"], str)
    assert isinstance(data["valid_through"], str)
    assert data["record_status"] in _values(TrainingRecordStatus)
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_transitional_job(data: dict):
    assert_common_fields(data, "TransitionalJob")
    assert is_valid_uuid(data["supervisor_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["department_code"], str)
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["filled_seats"], int) and data["filled_seats"] >= 0
    assert data["demand_lift_lbs"] >= 0
    assert data["demand_standing_minutes"] >= 0
    assert 0 < data["demand_hours_per_day"] <= 12
    assert 0 <= data["demand_keyboard_minutes_per_hour"] <= 60
    assert isinstance(data["requires_overhead_reach"], bool)
    assert isinstance(data["requires_driving"], bool)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 1
    assert data["risk_class"] in _values(RiskClass)
    assert data["job_status"] in _values(JobStatus)


def assert_placement(data: dict):
    assert_common_fields(data, "Placement")
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["restriction_set_id"])
    assert is_valid_uuid(data["transitional_job_id"])
    assert is_valid_uuid(data["supervisor_id"])
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["placement_status"] in _values(PlacementStatus)
    assert data["compliance_status"] in _values(ComplianceStatus)
    assert data["end_date"] >= data["start_date"]
    assert 0 < data["scheduled_hours_per_day"] <= 12
    assert isinstance(data["logged_hours"], list)
    assert isinstance(data["progression_step"], int) and data["progression_step"] >= 0
    assert 0.0 <= data["match_score"] <= 100.0, "match_score is clamped to 0..100"
    assert isinstance(data["reinjury_risk_score"], int)
    assert 0 <= data["reinjury_risk_score"] <= 100, "reinjury_risk_score is clamped to 0..100"
    assert data["reinjury_risk_variant"] in ("BASELINE", "SURVEILLANCE")
    assert isinstance(data["cumulative_days"], int) and data["cumulative_days"] >= 0
    assert isinstance(data["employer_premium_share_cents"], int)
    assert isinstance(data["employee_premium_share_cents"], int)
    assert data["benefit_continuation_status"] in _values(BenefitContinuationStatus)
    assert isinstance(data["projected_weekly_cost_cents"], int)


def assert_adjuster_directive(data: dict):
    assert_common_fields(data, "AdjusterDirective")
    assert is_valid_uuid(data["placement_id"])
    assert data["directive_status"] in _values(DirectiveStatus)
    assert isinstance(data["requested_weekly_cost_cents"], int)
    assert isinstance(data["authorized_weekly_cost_cents"], int)


def assert_progression_review(data: dict):
    assert_common_fields(data, "ProgressionReview")
    assert is_valid_uuid(data["placement_id"])
    assert isinstance(data["step_index"], int) and data["step_index"] >= 1
    assert isinstance(data["due_date"], str)
    assert data["review_status"] in _values(ReviewStatus)
    assert isinstance(data["deferral_count"], int) and data["deferral_count"] >= 0


def assert_compliance_audit(data: dict):
    assert_append_only_fields(data, "ComplianceAudit")
    assert is_valid_uuid(data["placement_id"])
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert isinstance(data["observed_on"], str)
    assert data["finding_severity"] in ("NONE", "MINOR", "MAJOR", "CRITICAL")
    assert data["finding_code"] in (
        "RESTRICTION_DEVIATION", "HOURS_DEVIATION", "SUPERVISION_GAP", "DOCUMENTATION", "NONE",
    )
    assert isinstance(data["restriction_deviation_detected"], bool)


def assert_reinjury_report(data: dict):
    assert_common_fields(data, "ReinjuryReport")
    assert is_valid_uuid(data["placement_id"])
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert isinstance(data["occurred_on"], str)
    assert data["severity"] in ("NEAR_MISS", "MINOR", "SIGNIFICANT", "SEVERE")
    assert isinstance(data["body_part_code"], str)
    assert isinstance(data["mechanism_code"], str)
    assert data["report_status"] in _values(ReportStatus)
    assert isinstance(data["risk_points_applied"], int)


def assert_case_review(data: dict):
    assert_common_fields(data, "CaseReview")
    assert is_valid_uuid(data["placement_id"])
    assert data["trigger_reason"] in (
        "REINJURY", "RESTRICTION_CONFLICT", "DURATION_CAP", "COMPLIANCE_CRITICAL", "ADJUSTER_DENIAL",
    )
    assert data["review_status"] in _values(CaseReviewStatus)
    assert isinstance(data["quorum_required"], int) and 1 <= data["quorum_required"] <= 7
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert isinstance(data["vote_count"], int)
    assert data["vote_count"] == (
        data["continue_votes"] + data["modify_votes"] + data["terminate_votes"]
    ), "vote_count must equal the sum of the three counted-ballot tallies"
    if data["vote_count"] == 0:
        assert data["decision_ratio"] == 0, "a panel with no counted ballots has decision_ratio 0"
        assert data["winning_ballot"] is None, "a panel with no counted ballots has a null winning_ballot"
    else:
        assert data["winning_ballot"] in ("CONTINUE", "MODIFY", "TERMINATE")
        assert 0 < data["decision_ratio"] <= 1


def assert_case_review_vote(data: dict):
    assert_append_only_fields(data, "CaseReviewVote")
    assert is_valid_uuid(data["case_review_id"])
    assert isinstance(data["voter_user_id"], str) and data["voter_user_id"]
    assert data["voter_role"] in (
        "RTWCoordinator", "OccHealthNurse", "ClaimAdjuster", "Supervisor", "TreatingProvider",
    )
    assert data["ballot"] in ("CONTINUE", "MODIFY", "TERMINATE")
    assert data["vote_status"] in _values(VoteStatus)


def assert_wage_entry(data: dict):
    assert_append_only_fields(data, "WageDifferentialEntry")
    assert is_valid_uuid(data["placement_id"])
    assert is_valid_uuid(data["claim_id"])
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["period_end"] >= data["period_start"]
    assert isinstance(data["counted_day_count"], int)
    assert isinstance(data["gross_differential_cents"], int), "money is whole cents"
    assert isinstance(data["offset_cents"], int), "money is whole cents"
    assert isinstance(data["net_amount_cents"], int), "money is whole cents"
    assert data["entry_status"] in _values(WageEntryStatus)


def assert_placement_dimensions_independent(data: dict, placement_status: str,
                                            compliance_status: str):
    """The lifecycle dimension and the monitoring dimension evolve on separate axes."""
    assert data["placement_status"] == placement_status, (
        f"Expected placement_status {placement_status}, got {data['placement_status']}"
    )
    assert data["compliance_status"] == compliance_status, (
        f"Expected compliance_status {compliance_status}, got {data['compliance_status']}"
    )


def assert_seat_ledger(job: dict, expected_filled: int):
    """filled_seats counts the placements on that job whose placement_status is
    ADJUSTER_PENDING, ACTIVE or PROGRESSION_HOLD."""
    assert job["filled_seats"] == expected_filled, (
        f"Expected filled_seats {expected_filled}, got {job['filled_seats']}"
    )
    assert 0 <= job["filled_seats"] <= job["seat_capacity"], (
        "filled_seats must stay inside 0..seat_capacity"
    )
