"""
TypedDict shapes for the eleven persisted resource types.

All eleven types carry the same four system-managed properties (`id`,
`created_at`, `updated_at`, `version`), so they all extend `CommonFields`.

These are documentation-grade shapes used for editor support in the test suite;
`total=False` throughout because responses are asserted key by key.
"""

from typing import List, Optional, TypedDict


class CommonFields(TypedDict, total=False):
    """The four properties present on every row of every resource type."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Club(CommonFields, total=False):
    name: str
    market_code: str
    exemption_slots_total: int
    compliance_score: int
    adjudicated_compliance_score: int
    escalation_tier: str
    status: str
    outstanding_fine_cents: int
    open_violation_count: int
    exemption_slots_used: int
    exemption_slots_available: int


class Clinician(CommonFields, total=False):
    full_name: str
    affiliation: str
    club_id: Optional[str]
    license_number: str
    credential_expires_at: str
    status: str
    suspension_reason: Optional[str]
    cases_cleared_count: int


class Player(CommonFields, total=False):
    club_id: str
    full_name: str
    jersey_number: int
    position: str
    baseline_status: str
    availability_status: str
    public_injury_designation: str
    diagnosed_case_count: int


class Game(CommonFields, total=False):
    season_year: int
    week_index: int
    home_club_id: str
    away_club_id: str
    kickoff_at: str
    status: str
    report_window_opens_at: str
    report_window_closes_at: str


class BaselineTest(CommonFields, total=False):
    player_id: str
    administered_by_clinician_id: str
    season_year: int
    composite_score: int
    reaction_time_ms: int
    symptom_score: int
    administered_at: str
    validity_expires_at: str
    status: str
    retest_required_reason: str


class SidelineEvaluation(CommonFields, total=False):
    player_id: str
    game_id: str
    initiating_clinician_id: str
    evaluating_clinician_id: Optional[str]
    inc_clinician_id: Optional[str]
    trigger_source: str
    mandatory_removal: bool
    status: str
    initiated_at: str
    protocol_deadline_at: str
    no_go_signs: List[str]
    screen_symptom_score: Optional[int]
    screened_at: Optional[str]
    exam_started_at: Optional[str]
    inc_block_ends_at: Optional[str]
    exam_completed_at: Optional[str]
    exam_duration_minutes: Optional[int]
    diagnosis_outcome: str


class ConcussionCase(CommonFields, total=False):
    player_id: str
    club_id: str
    sideline_evaluation_id: str
    diagnosing_clinician_id: str
    prior_case_id: Optional[str]
    season_year: int
    diagnosis_at: str
    initial_symptom_score: int
    diagnosis_composite_score: int
    baseline_deviation_points: int
    severity_index: int
    recurrence_count: int
    rtp_stage: int
    case_status: str
    frozen_from_status: Optional[str]
    monitoring_status: str
    roster_exemption_status: str
    heightened_review_required: bool
    projected_return_at: str
    earliest_return_at: Optional[str]
    cleared_for_contact_at: Optional[str]
    last_symptom_check_score: Optional[int]
    last_symptomatic_at: Optional[str]
    days_since_diagnosis: int


class ReturnStep(CommonFields, total=False):
    case_id: str
    stage_index: int
    stage_name: str
    attempt_index: int
    status: str
    started_at: str
    min_start_at: str
    dwell_complete_at: str
    evaluated_at: Optional[str]
    cleared_by_clinician_id: Optional[str]
    evaluation_symptom_score: Optional[int]


class IncClearance(CommonFields, total=False):
    case_id: str
    inc_clinician_id: str
    requested_by_clinician_id: str
    requested_at: str
    decided_at: Optional[str]
    expires_at: Optional[str]
    status: str
    decision_notes: Optional[str]
    documented_stage_count: int


class ProtocolAudit(CommonFields, total=False):
    club_id: str
    case_id: Optional[str]
    sideline_evaluation_id: Optional[str]
    opened_by_user_id: Optional[str]
    auto_opened: bool
    status: str
    violation_codes: List[str]
    exposure_days: int
    escalation_tier_at_issuance: Optional[str]
    assessed_fine_cents: int
    response_round_count: int
    club_response_note: Optional[str]
    findings_issued_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    disposition: str
    findings_issued_at: Optional[str]
    closed_at: Optional[str]


class InjuryReportEntry(CommonFields, total=False):
    game_id: str
    player_id: str
    club_id: str
    practice_participation: str
    designation: str
    required_designation: str
    filed_at: str
    amended_at: Optional[str]
    amended_from_designation: Optional[str]
    status: str


class ComplianceSummary(TypedDict, total=False):
    """Computed read returned by the club compliance-summary endpoint."""

    club_id: str
    compliance_score: int
    adjudicated_compliance_score: int
    escalation_tier: str
    status: str
    outstanding_fine_cents: int
    open_violation_count: int
    exemption_slots_total: int
    exemption_slots_used: int
    exemption_slots_available: int
    frozen_case_count: int


class SweepResult(TypedDict, total=False):
    """Summary object the operational sweep reports what it did through."""

    swept_at: str
    breached_evaluation_ids: List[str]
    auto_opened_audit_ids: List[str]
    expired_baseline_test_ids: List[str]
    expired_inc_clearance_ids: List[str]
    prolonged_watch_case_ids: List[str]
    offseason_monitoring_case_ids: List[str]
    frozen_case_ids: List[str]
    restored_case_ids: List[str]
